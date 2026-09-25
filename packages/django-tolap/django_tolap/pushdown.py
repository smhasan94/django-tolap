"""Compile TOLAP row filters into ``Q`` objects, or decline.

The contract (PRD FR-8, FR-13): a pushed ``Q`` selects **exactly** the rows upstream's
post-execution ``apply_row_filters`` would keep, on the vendor the query will run on. When
that cannot be guaranteed the filter is declined and reported in
``Preparation.unpushable_filters``; the post pass enforces it. Declining is always safe;
approximating never is.

Semantics mirrored from ``tolap_core.enforcement._row_passes_filter`` (1.0.0):

* ``equals``/``notEquals`` use Python equality: ``None == None`` holds, booleans never equal
  numbers. So ``equals null`` is ``IS NULL`` and ``notEquals x`` keeps null rows.
* ``in``/``notIn`` are ``any(equals)``; a ``null`` member matches null rows.
* Ordering operators drop a row whose value is null, boolean, or not comparable.
* ``like`` is case-sensitive with ``\\`` escapes; ``notLike`` keeps null rows.
* ``contains``, ``startsWith``, ``matches`` have no faithful SQL form and are never pushed.

Django's own negation already keeps null rows: ``~Q(f=x)`` on a nullable field compiles to
``NOT (f = x AND f IS NOT NULL)`` (verified in ``tests/test_null_handling.py``), so no extra
``IS NULL`` arm is added for negatives.

Vendor rules: string equality is pushed only where ``=`` is case-sensitive; string ordering
only where the collation orders by code point; ``like`` only where ``LIKE`` is
case-sensitive. A field with an explicit ``db_collation`` disables every string operator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from typing import Any, Literal

from django.db import connections, models
from django.db.models import Manager, Model, Q
from tolap_core import EffectivePolicy, FilterOperator, RowFilter, apply_result_pipeline

from django_tolap.exceptions import Uninspectable
from django_tolap.inspect import inspect
from django_tolap.objects import object_name
from django_tolap.precheck import CANNOT_INSPECT, FieldRules, field_visible, precheck_inspection

_LOG = logging.getLogger(__name__)

Kind = Literal["str", "int", "float", "bool", "other"]

NEVER_PUSHED = frozenset(
    {FilterOperator.contains, FilterOperator.starts_with, FilterOperator.matches}
)
MAX_LIKE_PATTERN_LENGTH = 1024  # upstream's ReDoS guard: longer patterns drop every row


@dataclass(frozen=True)
class VendorRules:
    string_equality: bool
    string_order: bool
    like: bool


VENDORS: dict[str, VendorRules] = {
    # ``=`` and ``LIKE`` case-sensitive; ordering follows the database collation.
    "postgresql": VendorRules(string_equality=True, string_order=False, like=True),
    # BINARY collation: ``=`` and ordering are byte-wise; ``LIKE`` is case-insensitive.
    "sqlite": VendorRules(string_equality=True, string_order=True, like=False),
    # Default collations are case- and accent-insensitive for every string operator.
    "mysql": VendorRules(string_equality=False, string_order=False, like=False),
    "oracle": VendorRules(string_equality=False, string_order=False, like=False),
}
_warned_vendors: set[str] = set()


def vendor_rules(vendor: str) -> VendorRules | None:
    rules = VENDORS.get(vendor)
    if rules is None and vendor not in _warned_vendors:
        _warned_vendors.add(vendor)
        _LOG.warning("TOLAP pushdown disabled: unknown database vendor %r", vendor)
    return rules


def field_kind(field: models.Field[Any, Any]) -> Kind:
    if isinstance(field, models.BooleanField):
        return "bool"
    if isinstance(field, models.CharField | models.TextField):
        return "str"
    if isinstance(field, models.IntegerField):
        return "int"
    if isinstance(field, models.FloatField):
        return "float"
    return "other"


def value_fits(kind: Kind, value: Any) -> bool:
    """Whether the driver would return ``value``'s Python type for this field kind."""
    if isinstance(value, bool):
        return kind == "bool"
    if kind == "str":
        # A NUL byte cannot be bound as a text parameter on PostgreSQL (and can never match a
        # stored value there); the post pass evaluates such a value instead.
        return isinstance(value, str) and "\x00" not in value
    if kind == "int":
        return isinstance(value, int)
    if kind == "float":
        return isinstance(value, int | float)
    return False


def resolve_field(
    rf: RowFilter, model: type[Model], *, include_relations: bool = False
) -> models.Field[Any, Any] | None:
    """The concrete field ``rf.field`` names on ``model``, if any.

    A name qualified with another object belongs to that object. Relation fields are
    excluded by default: their value in ``.values()`` rows is an id under a different key,
    so a filter on one is left to the post pass (they are still projected for it).
    """
    qualifier, _, leaf = rf.field.rpartition(".")
    if qualifier and qualifier.lower() != object_name(model).lower():
        return None
    for field in model._meta.concrete_fields:
        if field.name.lower() == leaf.lower() and (include_relations or not field.is_relation):
            return field
    return None


def _nothing() -> Q:
    return Q(pk__in=[])


def compile_filter(rf: RowFilter, model: type[Model], vendor: str) -> Q | None:
    """A ``Q`` selecting exactly the rows the post pass keeps, or ``None`` to decline."""
    rules = vendor_rules(vendor)
    if rules is None or rf.operator in NEVER_PUSHED:
        return None
    field = resolve_field(rf, model)
    if field is None:
        return None
    name = field.name
    op = rf.operator

    if op is FilterOperator.is_null:
        return Q(**{f"{name}__isnull": True})
    if op is FilterOperator.is_not_null:
        return Q(**{f"{name}__isnull": False})

    kind = field_kind(field)
    if kind == "other":
        return None
    if kind == "str" and getattr(field, "db_collation", None):
        return None

    if op in (FilterOperator.equals, FilterOperator.not_equals):
        negated = op is FilterOperator.not_equals
        if rf.value is None:
            return Q(**{f"{name}__isnull": not negated})
        if not value_fits(kind, rf.value) or (kind == "str" and not rules.string_equality):
            return None
        q = Q(**{name: rf.value})
        return ~q if negated else q

    if op in (FilterOperator.in_, FilterOperator.not_in):
        values = list(rf.values or [])
        has_null = any(v is None for v in values)
        members = [v for v in values if v is not None]
        if any(not value_fits(kind, v) for v in members):
            return None
        if kind == "str" and members and not rules.string_equality:
            return None
        if op is FilterOperator.in_:
            if not values:
                return _nothing()
            q = Q(**{f"{name}__in": members}) if members else _nothing()
            return q | Q(**{f"{name}__isnull": True}) if has_null else q
        if not values:
            return Q()
        q = ~Q(**{f"{name}__in": members}) if members else Q()
        return q & Q(**{f"{name}__isnull": False}) if has_null else q

    if op in _ORDERING:
        if rf.value is None or not value_fits(kind, rf.value) or kind == "bool":
            return _nothing() if rf.value is None else None
        if kind == "str" and not rules.string_order:
            return None
        return Q(**{f"{name}__{_ORDERING[op]}": rf.value})

    if op is FilterOperator.between:
        bounds = list(rf.values or [])
        if len(bounds) < 2 or bounds[0] is None or bounds[1] is None:
            return _nothing()
        if kind == "bool" or not all(value_fits(kind, b) for b in bounds[:2]):
            return None
        if kind == "str" and not rules.string_order:
            return None
        return Q(**{f"{name}__range": (bounds[0], bounds[1])})

    if op in (FilterOperator.like, FilterOperator.not_like):
        if kind != "str" or not rules.like or not value_fits("str", rf.value):
            return None
        if len(rf.value) > MAX_LIKE_PATTERN_LENGTH:
            return None
        q = Q(**{f"{name}__tolap_like": rf.value})
        return ~q if op is FilterOperator.not_like else q

    return None  # pragma: no cover - every enum member is handled above


_ORDERING = {
    FilterOperator.greater_than: "gt",
    FilterOperator.greater_than_or_equal: "gte",
    FilterOperator.less_than: "lt",
    FilterOperator.less_than_or_equal: "lte",
}


# -- Preparing a whole QuerySet --

NO_FIELDS_VISIBLE = "no fields visible"
FILTER_NOT_IN_RESULT = "row filter field not in result: {field}"


class EnforcementMode(Enum):
    """Where the policy is applied, mirroring upstream ``SqlEnforcementMode`` (spec section 4).

    Both modes return the same rows; the post-execution pipeline runs in both. The mode
    decides only how much data the database produces. There is deliberately no mode that
    skips the post pass.
    """

    #: Push row filters, the result limit and the projection into the QuerySet. Default.
    rewrite_and_post = "rewriteAndPost"
    #: Leave filters and limit to the post pass; only the projection is applied (rows must
    #: be dicts for the pipeline, and hidden columns need not be fetched to be stripped).
    post_only = "postOnly"


@dataclass
class Preparation:
    """The outcome of :func:`prepare_queryset`.

    Mirrors upstream ``SqlQueryPreparation``. ``queryset`` is what to execute when ``allowed``;
    it yields dicts (``.values()``) restricted to ``visible_fields`` plus the annotations the
    caller selected. **The post-execution pipeline still MUST run on the rows it returns.**
    """

    allowed: bool
    queryset: Any | None
    denial_reason: str | None = None
    unpushable_filters: list[RowFilter] = dataclass_field(default_factory=list)
    pushed_filters: list[RowFilter] = dataclass_field(default_factory=list)
    visible_fields: tuple[str, ...] = ()
    projection: tuple[str, ...] = ()
    extra_fields: tuple[str, ...] = ()
    """Fields projected only so the post pass can evaluate a row filter; stripped after."""
    key_map: dict[str, str] = dataclass_field(default_factory=dict)
    """Every model field's caller key (root fields, ``patient__email``, filter extras) and
    the ``object.field`` key the post pass sees it under: unique per field, so that object's
    rules match it and no two keys share a bare name by accident. Annotations keep their
    key."""
    filter_keys: dict[str, str] = dataclass_field(default_factory=dict)
    """Row-filter fields and the caller key of the field each one reads, for every filter
    whose spelling is not that field's post-pass key (``REGION``, ``Encounters.Region``).
    Each is copied into the row under the filter's own spelling so upstream's exact lookup
    hits and its bare-name fallback is never reached; stripped after the post pass."""
    max_results: int | None = None
    mode: EnforcementMode = EnforcementMode.rewrite_and_post

    @property
    def fully_pushed_down(self) -> bool:
        return self.allowed and not self.unpushable_filters

    @classmethod
    def denied(cls, reason: str) -> Preparation:
        return cls(allowed=False, queryset=None, denial_reason=reason)


def _root_filter_field(rf: RowFilter, model: type[Model]) -> str | None:
    """Name of the root-model concrete field a row filter reads, for the projection."""
    field = resolve_field(rf, model, include_relations=True)
    return field.name if field is not None else None


def _filter_fields(
    root: type[Model], row_filters: list[RowFilter], key_map: dict[str, str]
) -> tuple[list[str], dict[str, str], dict[str, str], str | None]:
    """Resolve every row filter to exactly one field of the result, for the post pass.

    A bare or root-qualified field names a root field; another qualifier names a joined
    object's field; both are matched case-insensitively against ``key_map``. Returns the
    root fields to add for filters (``extra``), the filter spellings to copy from a caller
    key when they differ from the field's post-pass key (``filter_keys``), the key map
    extended with the additions, or a denial: a filter whose field is not in the result
    and cannot be added cannot be evaluated, and upstream would drop the row or, by
    bare-name fallback, read another object's field of the same name.
    """
    root_obj = object_name(root)
    mapped = dict(key_map)
    lowered = {presented.lower(): key for key, presented in mapped.items()}
    extra: list[str] = []
    keys: dict[str, str] = {}
    for rf in row_filters:
        qualifier, _, leaf = rf.field.rpartition(".")
        name = _root_filter_field(rf, root)
        if name is not None:
            target = f"{root_obj}.{name}"
            caller = lowered.get(target.lower())
            if caller is None:
                caller = name
                extra.append(caller)
                mapped[caller] = target
                lowered[target.lower()] = caller
        else:
            caller = lowered.get(f"{qualifier}.{leaf}".lower()) if qualifier else None
            if caller is None:
                return extra, keys, mapped, FILTER_NOT_IN_RESULT.format(field=rf.field)
        if mapped[caller] != rf.field:
            keys[rf.field] = caller
    return extra, keys, mapped, None


def prepare_queryset(
    queryset: Any,
    policy: EffectivePolicy,
    *,
    mode: EnforcementMode | str = EnforcementMode.rewrite_and_post,
) -> Preparation:
    """Pre-check, then push row filters, projection and limit into a copy of ``queryset``.

    In :attr:`EnforcementMode.post_only` the pre-checks and the projection still apply
    (declining to rewrite never relaxes a denial) but no row filter or limit is pushed and
    every row filter is reported unpushable, as upstream requires.

    Steps: :func:`precheck_inspection`; compute the visible projection (concrete fields minus
    hidden, intersected with ``allowedFields`` and with the caller's own projection); keep
    every field a row filter reads so the post pass can evaluate it (a hidden filtered field
    is projected here and stripped by the post pass, per upstream section 4); compile each
    row filter for the connection's vendor; ``.values(...)``; slice to ``maxResults``.

    A QuerySet the caller already sliced cannot take further filters (Django refuses, and
    filtering before the offset would change which rows the window covers), so its row
    filters are all reported unpushable; only the projection and a narrower limit apply.
    """
    resolved_mode = EnforcementMode(mode) if isinstance(mode, str) else mode
    qs = queryset.all() if isinstance(queryset, Manager) else queryset
    try:
        ins = inspect(qs)
    except Uninspectable as exc:
        return Preparation.denied(CANNOT_INSPECT.format(why=exc.why))
    access = precheck_inspection(ins, policy)
    if not access.allowed:
        return Preparation.denied(access.reason or "access denied")

    root = ins.root
    rules = FieldRules.of(policy)
    obj = object_name(root)
    concrete = [f.name for f in root._meta.concrete_fields]
    visible = tuple(n for n in concrete if field_visible(rules, f"{obj}.{n}"))

    annotation_names = tuple(qs.query.annotation_select)
    if ins.projected is None:
        base = list(visible)
    else:
        # A joined column reached here only if precheck_inspection found it visible.
        pk = root._meta.pk.name
        base = [
            n
            for n in ins.projected
            if n in visible or n in ins.joined or (n == "pk" and pk in visible)
        ]
        annotation_names = tuple(n for n in ins.projected if n in annotation_names)
    if not base:
        return Preparation.denied(NO_FIELDS_VISIBLE)
    key_map = {n: f"{object_name(ref.model)}.{ref.name}" for n, ref in ins.joined.items()}
    key_map.update({n: f"{obj}.{n}" for n in base if n in concrete})
    if "pk" in base:
        key_map["pk"] = f"{obj}.{root._meta.pk.name}"

    row_filters = list(policy.object_rules.row_filters or ()) if policy.object_rules else []
    extra, filter_keys, key_map, denial = _filter_fields(root, row_filters, key_map)
    if denial is not None:
        return Preparation.denied(denial)
    projection = (*base, *extra)

    vendor = connections[qs.db].vendor
    sliced = ins.low_mark != 0 or ins.high_mark is not None
    push = resolved_mode is EnforcementMode.rewrite_and_post and not sliced
    pushed: list[RowFilter] = []
    unpushable: list[RowFilter] = []
    prepared = qs
    for rf in row_filters:
        q = compile_filter(rf, root, vendor) if push else None
        if q is None:
            unpushable.append(rf)
        else:
            pushed.append(rf)
            prepared = prepared.filter(q)

    prepared = prepared.values(*projection, *annotation_names)

    # The limit is pushed only when every row filter was pushed: a database LIMIT applied
    # before a post-pass filter would truncate to fewer than maxResults qualifying rows.
    max_results = policy.limits.max_results if policy.limits else None
    if (
        max_results is not None
        and resolved_mode is EnforcementMode.rewrite_and_post
        and not unpushable
    ):
        low, high = ins.low_mark, ins.high_mark
        cap = low + max_results
        if high is None or cap < high:
            prepared = _reslice(prepared, low, cap)

    return Preparation(
        allowed=True,
        queryset=prepared,
        unpushable_filters=unpushable,
        pushed_filters=pushed,
        visible_fields=visible,
        projection=(*projection, *annotation_names),
        extra_fields=tuple(extra),
        key_map=key_map,
        filter_keys=filter_keys,
        max_results=max_results,
        mode=resolved_mode,
    )


def finalize(
    prep: Preparation,
    rows: list[dict[str, Any]],
    policy: EffectivePolicy,
    hash_salt: str | bytes | None,
) -> list[dict[str, Any]]:
    """The post-execution pipeline (mandatory), then the caller's keys and fields back.

    Model fields are presented as ``object.field`` (``key_map``) and each row filter's
    field is copied under the filter's own spelling (``filter_keys``); afterwards the
    copies and the fields projected only for filters (``extra_fields``) are dropped and
    every other key is the caller's again.
    """
    key_map, copies = prep.key_map, prep.filter_keys
    rows = [
        {
            **{key_map.get(k, k): v for k, v in row.items()},
            **{f: row[c] for f, c in copies.items()},
        }
        for row in rows
    ]
    result: list[dict[str, Any]] = apply_result_pipeline(rows, policy, hash_salt)
    back = {v: k for k, v in key_map.items()}
    extra = set(prep.extra_fields)
    restored: list[dict[str, Any]] = []
    for row in result:
        kept: dict[str, Any] = {}
        for k, v in row.items():
            if k in copies:
                continue
            caller = back.get(k, k)
            if caller not in extra:
                kept[caller] = v
        restored.append(kept)
    return restored


def _reslice(qs: Any, low: int, high: int) -> Any:
    clone = qs._chain()
    clone.query.clear_limits()
    clone.query.set_limits(low, high)
    return clone
