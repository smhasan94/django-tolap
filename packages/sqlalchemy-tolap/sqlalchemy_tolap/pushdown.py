"""Compile TOLAP row filters into SQLAlchemy criteria, or decline; prepare a whole Select.

Same contract and semantics as ``django_tolap.pushdown`` (a pushed predicate selects exactly
the rows upstream's post pass keeps, on this dialect). Unlike Django's ORM, SQLAlchemy does
not add a null arm to negations, so ``notEquals``/``notIn``/``notLike`` are rendered as
``(col <> x OR col IS NULL)`` here, as upstream's own rewriter does.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from typing import Any, Literal

from sqlalchemy import Column, Table, and_, false, or_, true
from sqlalchemy import types as sa_types
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Select
from tolap_core import EffectivePolicy, FilterOperator, RowFilter, apply_result_pipeline

from sqlalchemy_tolap.exceptions import Uninspectable
from sqlalchemy_tolap.inspect import inspect
from sqlalchemy_tolap.precheck import CANNOT_INSPECT, precheck_inspection
from sqlalchemy_tolap.rules import FieldRules, field_visible

_LOG = logging.getLogger(__name__)

Kind = Literal["str", "int", "float", "bool", "other"]
NEVER_PUSHED = frozenset(
    {FilterOperator.contains, FilterOperator.starts_with, FilterOperator.matches}
)
MAX_LIKE_PATTERN_LENGTH = 1024


class EnforcementMode(Enum):
    rewrite_and_post = "rewriteAndPost"
    post_only = "postOnly"


@dataclass(frozen=True)
class DialectRules:
    string_equality: bool
    string_order: bool
    like: bool


DIALECTS: dict[str, DialectRules] = {
    "postgresql": DialectRules(string_equality=True, string_order=False, like=True),
    "sqlite": DialectRules(string_equality=True, string_order=True, like=False),
    "mysql": DialectRules(string_equality=False, string_order=False, like=False),
    "mariadb": DialectRules(string_equality=False, string_order=False, like=False),
    "oracle": DialectRules(string_equality=False, string_order=False, like=False),
    "mssql": DialectRules(string_equality=False, string_order=False, like=False),
}
_warned: set[str] = set()


def dialect_rules(name: str) -> DialectRules | None:
    rules = DIALECTS.get(name)
    if rules is None and name not in _warned:
        _warned.add(name)
        _LOG.warning("TOLAP pushdown disabled: unknown dialect %r", name)
    return rules


def column_kind(column: Column[Any]) -> Kind:
    t = column.type
    if isinstance(t, sa_types.Boolean):
        return "bool"
    if isinstance(t, sa_types.String):
        return "str"
    if isinstance(t, sa_types.Integer):
        return "int"
    if isinstance(t, sa_types.Float):
        return "float"
    return "other"


def value_fits(kind: Kind, value: Any) -> bool:
    if isinstance(value, bool):
        return kind == "bool"
    if kind == "str":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int)
    if kind == "float":
        return isinstance(value, int | float)
    return False


def resolve_column(rf: RowFilter, table: Table) -> Column[Any] | None:
    qualifier, _, leaf = rf.field.rpartition(".")
    if qualifier and qualifier.lower() != table.name.lower():
        return None
    for column in table.columns:
        if column.name.lower() == leaf.lower():
            return column
    return None


def _nothing() -> ColumnElement[bool]:
    return false()


_ORDERING = {
    FilterOperator.greater_than: "__gt__",
    FilterOperator.greater_than_or_equal: "__ge__",
    FilterOperator.less_than: "__lt__",
    FilterOperator.less_than_or_equal: "__le__",
}


def compile_filter(
    rf: RowFilter, table: Table, dialect: str, *, source: Any = None
) -> ColumnElement[bool] | None:
    """Criteria for ``rf`` on ``table``'s column, taken from ``source`` (an alias) if given."""
    rules = dialect_rules(dialect)
    if rules is None or rf.operator in NEVER_PUSHED:
        return None
    resolved = resolve_column(rf, table)
    if resolved is None or resolved.foreign_keys:
        return None
    col: Column[Any] = source.c[resolved.name] if source is not None else resolved
    op = rf.operator
    if op is FilterOperator.is_null:
        return col.is_(None)
    if op is FilterOperator.is_not_null:
        return col.is_not(None)

    kind = column_kind(col)
    if kind == "other":
        return None
    if kind == "str" and getattr(col.type, "collation", None):
        return None

    if op in (FilterOperator.equals, FilterOperator.not_equals):
        negated = op is FilterOperator.not_equals
        if rf.value is None:
            return col.is_not(None) if negated else col.is_(None)
        if not value_fits(kind, rf.value) or (kind == "str" and not rules.string_equality):
            return None
        return or_(col != rf.value, col.is_(None)) if negated else col == rf.value

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
            crit = col.in_(members) if members else _nothing()
            return or_(crit, col.is_(None)) if has_null else crit
        if not values:
            return true()
        crit = col.not_in(members) if members else true()
        return and_(crit, col.is_not(None)) if has_null else or_(crit, col.is_(None))

    if op in _ORDERING:
        if rf.value is None:
            return _nothing()
        if not value_fits(kind, rf.value) or kind == "bool":
            return None
        if kind == "str" and not rules.string_order:
            return None
        result: ColumnElement[bool] = getattr(col, _ORDERING[op])(rf.value)
        return result

    if op is FilterOperator.between:
        bounds = list(rf.values or [])
        if len(bounds) < 2 or bounds[0] is None or bounds[1] is None:
            return _nothing()
        if kind == "bool" or not all(value_fits(kind, b) for b in bounds[:2]):
            return None
        if kind == "str" and not rules.string_order:
            return None
        return col.between(bounds[0], bounds[1])

    if op in (FilterOperator.like, FilterOperator.not_like):
        if kind != "str" or not rules.like or not isinstance(rf.value, str):
            return None
        if len(rf.value) > MAX_LIKE_PATTERN_LENGTH:
            return None
        if op is FilterOperator.like:
            return col.like(rf.value, escape="\\")
        return or_(col.not_like(rf.value, escape="\\"), col.is_(None))

    return None  # pragma: no cover


NO_FIELDS_VISIBLE = "no fields visible"


@dataclass
class Preparation:
    allowed: bool
    statement: Select[Any] | None
    denial_reason: str | None = None
    unpushable_filters: list[RowFilter] = dataclass_field(default_factory=list)
    pushed_filters: list[RowFilter] = dataclass_field(default_factory=list)
    visible_fields: tuple[str, ...] = ()
    projection: tuple[str, ...] = ()
    extra_fields: tuple[str, ...] = ()
    """Fields projected only so the post pass can evaluate a row filter; stripped after."""
    key_map: dict[str, str] = dataclass_field(default_factory=dict)
    """Caller keys of joined or labelled columns and the ``table.column`` name the post pass
    sees them under, so that table's rules match them."""
    max_results: int | None = None
    mode: EnforcementMode = EnforcementMode.rewrite_and_post

    @property
    def fully_pushed_down(self) -> bool:
        return self.allowed and not self.unpushable_filters

    @classmethod
    def denied(cls, reason: str) -> Preparation:
        return cls(allowed=False, statement=None, denial_reason=reason)


def prepare_select(
    stmt: Any,
    policy: EffectivePolicy,
    *,
    dialect: str,
    mode: EnforcementMode | str = EnforcementMode.rewrite_and_post,
) -> Preparation:
    """Pre-check, then push filters, projection and limit into a new Select."""
    resolved_mode = EnforcementMode(mode) if isinstance(mode, str) else mode
    try:
        ins = inspect(stmt)
    except Uninspectable as exc:
        return Preparation.denied(CANNOT_INSPECT.format(why=exc.why))
    access = precheck_inspection(ins, policy)
    if not access.allowed:
        return Preparation.denied(access.reason or "access denied")

    root = ins.root
    rules = FieldRules.of(policy)
    by_name = {c.name: ins.root_from.c[c.name] for c in root.columns}  # alias-aware
    visible = tuple(c.name for c in root.columns if field_visible(rules, f"{root.name}.{c.name}"))

    if ins.projected is None:
        base: list[Any] = [by_name[n] for n in visible]
        names = list(visible)
    else:
        base = []
        names = []
        for col in ins.selected:
            # Joined and labelled columns (ins.renamed) and Labels reached here only if the
            # pre-check found every column they read visible.
            if isinstance(col, Column) and col.name not in ins.renamed and col.name not in visible:
                continue
            base.append(col)
            names.append(col.name)
    key_map = {key: f"{ref.table}.{ref.name}" for key, ref in ins.renamed.items()}
    if not base:
        return Preparation.denied(NO_FIELDS_VISIBLE)

    row_filters = list(policy.object_rules.row_filters or ()) if policy.object_rules else []
    extra: list[str] = []
    for rf in row_filters:
        col = resolve_column(rf, root)
        if col is not None and col.name not in names and col.name not in extra:
            extra.append(col.name)
    for name in extra:
        base.append(by_name[name])

    sliced = ins.limit is not None or ins.offset is not None
    push = resolved_mode is EnforcementMode.rewrite_and_post and not sliced
    pushed: list[RowFilter] = []
    unpushable: list[RowFilter] = []
    prepared: Select[Any] = stmt
    for rf in row_filters:
        crit = compile_filter(rf, root, dialect, source=ins.root_from) if push else None
        if crit is None:
            unpushable.append(rf)
        else:
            pushed.append(rf)
            prepared = prepared.where(crit)

    prepared = prepared.with_only_columns(*base, maintain_column_froms=True)

    # The limit is pushed only when every row filter was pushed (see django_tolap.pushdown).
    max_results = policy.limits.max_results if policy.limits else None
    if (
        max_results is not None
        and resolved_mode is EnforcementMode.rewrite_and_post
        and not unpushable
    ):
        if ins.limit is None or max_results < ins.limit:
            prepared = prepared.limit(max_results)

    return Preparation(
        allowed=True,
        statement=prepared,
        unpushable_filters=unpushable,
        pushed_filters=pushed,
        visible_fields=visible,
        projection=(*names, *extra),
        extra_fields=tuple(extra),
        key_map=key_map,
        max_results=max_results,
        mode=resolved_mode,
    )


def finalize(
    prep: Preparation,
    rows: list[dict[str, Any]],
    policy: EffectivePolicy,
    hash_salt: str | bytes | None,
) -> list[dict[str, Any]]:
    """The post-execution pipeline (mandatory), then drop fields projected only for filters.

    Joined and labelled columns are presented to the pipeline as ``table.column`` so that
    table's rules match them, and handed back under the caller's key.
    """
    if prep.key_map:
        rows = [{prep.key_map.get(k, k): v for k, v in row.items()} for row in rows]
    result: list[dict[str, Any]] = apply_result_pipeline(rows, policy, hash_salt)
    if prep.key_map:
        back = {v: k for k, v in prep.key_map.items()}
        result = [{back.get(k, k): v for k, v in row.items()} for row in result]
    if not prep.extra_fields:
        return result
    extra = set(prep.extra_fields)
    return [{k: v for k, v in row.items() if k not in extra} for row in result]
