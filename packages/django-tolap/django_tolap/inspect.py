"""Determine which tables and columns a QuerySet references, or refuse.

The pre-execution checks (connector spec section 5) need every column the query *references*
-- ``WHERE``, ``ORDER BY``, ``GROUP BY``, annotations, projection -- not only those it
returns. Django resolves these to :class:`~django.db.models.expressions.Col` nodes on the
query and its compiler; this module walks them. Anything it cannot see through (``extra()``,
``RawSQL``, set operations, ``only()``/``defer()`` across relations) is refused with
:class:`Uninspectable`: fetching less is never a risk, returning more is, so unknown means
refuse. A ``values("related__field")`` projection is accepted and recorded in
:attr:`Inspection.joined` so the post pass can see which object each column belongs to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Manager, Model, QuerySet
from django.db.models.expressions import Col, RawSQL, ResolvedOuterRef, Star, Subquery, Value
from django.db.models.query import RawQuerySet
from django.db.models.sql import Query
from django.db.models.sql.datastructures import BaseTable, Join
from django.db.models.sql.where import ExtraWhere, NothingNode, WhereNode

from django_tolap.exceptions import Uninspectable


@dataclass(frozen=True, order=True)
class FieldRef:
    """A concrete model field referenced by the query."""

    model: type[Model] = field(compare=False)
    name: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.model._meta.label_lower, self.name)

    def __hash__(self) -> int:
        return hash(self.key)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FieldRef) and self.key == other.key


@dataclass(frozen=True)
class Inspection:
    root: type[Model]
    models: frozenset[type[Model]]
    referenced: frozenset[FieldRef]  # explicit references only; never the default projection
    projected: tuple[str, ...] | None
    annotations: dict[str, frozenset[FieldRef]]
    low_mark: int
    high_mark: int | None
    joined: dict[str, FieldRef] = field(default_factory=dict)
    """Projected ``related__field`` paths and the concrete field each one lands on."""


class _Walker:
    def __init__(self, using: str, *, explicit_select: bool = True) -> None:
        self.using = using
        self.explicit_select = explicit_select
        self.refs: set[FieldRef] = set()
        self.models: set[type[Model]] = set()
        self._tables = {m._meta.db_table: m for m in apps.get_models(include_auto_created=True)}
        self.select: list[Any] = []
        self.annotation_sources: dict[str, frozenset[FieldRef]] = {}

    def query(self, query: Query, *, root: bool = False) -> None:
        """Walk one query (outer or sub) through a compiled clone so nothing is mutated."""
        if query.extra or query.extra_tables or query.extra_order_by or query.extra_select:
            raise Uninspectable("extra() is not supported")
        if query.combinator:
            raise Uninspectable(f"{query.combinator}() is not supported")
        if query.select_for_update:
            raise Uninspectable("select_for_update() is not supported")

        clone = query.clone()
        compiler = clone.get_compiler(using=self.using)
        try:
            _, order_by, _ = compiler.pre_sql_setup()
        except Uninspectable:
            raise
        except Exception as exc:  # noqa: BLE001 - any compiler failure means we cannot inspect
            raise Uninspectable(f"compiler setup failed: {exc}") from exc

        for alias in clone.alias_map.values():
            if isinstance(alias, BaseTable | Join):
                model = self._tables.get(alias.table_name)
                if model is None:
                    raise Uninspectable(f"unknown table {alias.table_name!r}")
                self.models.add(model)
            else:  # pragma: no cover - defensive
                raise Uninspectable(f"unsupported alias {type(alias).__name__}")

        self._node(clone.where)
        for expr, _ in order_by:
            self._node(expr)
        # A default projection (``SELECT *``) is not a reference the caller made: hidden
        # columns are projected out later, as upstream does for ``SELECT *``. An explicit
        # ``values()``/``only()`` names columns and is checked. Subquery selects are always
        # explicit.
        if not root or self.explicit_select:
            for expr, _, _ in compiler.select:
                self._node(expr)
        if isinstance(clone.group_by, tuple):
            for expr in clone.group_by:
                self._node(expr)
        for name, expr in clone.annotations.items():
            sub = _Walker(self.using)
            sub._tables = self._tables
            sub._node(expr)
            self.refs |= sub.refs
            self.models |= sub.models
            if root:
                self.annotation_sources[name] = frozenset(sub.refs)
        if root:
            self.select = list(compiler.select)

    def _node(self, node: Any) -> None:
        if node is None or isinstance(node, Value | Star | NothingNode):
            return
        if isinstance(node, WhereNode):
            for child in node.children:
                self._node(child)
            return
        if isinstance(node, ExtraWhere | RawSQL):
            raise Uninspectable("raw SQL fragments are not supported")
        if isinstance(node, ResolvedOuterRef):
            raise Uninspectable("unresolved OuterRef")
        if isinstance(node, Col):
            target = node.target
            self.refs.add(FieldRef(target.model, target.name))
            return
        if isinstance(node, Subquery):
            self.query(node.query)
            return
        if isinstance(node, Query):
            self.query(node)
            return
        if hasattr(node, "get_source_expressions"):
            for child in node.get_source_expressions():
                self._node(child)
            return
        raise Uninspectable(f"unsupported expression {type(node).__name__}")


def _root_model(query: Query) -> type[Model]:
    if query.model is None:  # pragma: no cover - every QuerySet has a model
        raise Uninspectable("query has no model")
    return query.model


def _related_path(root: type[Model], path: str) -> FieldRef | None:
    """The concrete field a ``values("a__b__c")`` path lands on, following relations."""
    model = root
    parts = path.split("__")
    for part in parts[:-1]:
        try:
            rel = model._meta.get_field(part)
        except FieldDoesNotExist:
            return None
        related = getattr(rel, "related_model", None)
        if not rel.is_relation or related is None or related == "self":
            return None
        model = related
    leaf = parts[-1]
    if leaf == "pk":
        leaf = model._meta.pk.name
    try:
        leaf_field = model._meta.get_field(leaf)
    except FieldDoesNotExist:
        return None
    if not getattr(leaf_field, "concrete", False):
        return None
    return FieldRef(model=model, name=leaf_field.name)


def _projection(
    qs: QuerySet[Any], query: Query
) -> tuple[tuple[str, ...] | None, dict[str, FieldRef]]:
    root = _root_model(query)
    concrete = {f.name for f in root._meta.concrete_fields}
    fields = getattr(qs, "_fields", None)
    joined: dict[str, FieldRef] = {}
    if fields is not None:
        if not fields:
            return None, joined
        names: list[str] = []
        extra = [a for a in query.annotation_select if a not in fields]
        for name in (*fields, *extra):
            if "." in name:
                # Qualified keys are what the post pass sees joined columns under.
                raise Uninspectable(f"projection key {name!r} contains a dot")
            if name in query.annotations:
                names.append(name)
            elif name == "pk":
                names.append(root._meta.pk.name)
            elif name in concrete:
                names.append(name)
            elif "__" in name and (ref := _related_path(root, name)) is not None:
                names.append(name)
                joined[name] = ref
            else:
                raise Uninspectable(f"projection of {name!r} is not a model field")
        return tuple(names), joined
    deferred, is_defer = query.deferred_loading
    if not deferred:
        return None, joined
    if any("__" in name for name in deferred):
        raise Uninspectable("only()/defer() across relations is not supported")
    if is_defer:
        return tuple(f.name for f in root._meta.concrete_fields if f.name not in deferred), joined
    return (
        tuple(f.name for f in root._meta.concrete_fields if f.name in deferred or f.primary_key),
        joined,
    )


def inspect(queryset: QuerySet[Any] | Manager[Any]) -> Inspection:
    """Everything the pre-execution checks need, or raise :class:`Uninspectable`."""
    if isinstance(queryset, RawQuerySet):
        raise Uninspectable("raw() querysets are not supported")
    qs: QuerySet[Any] = queryset.all() if isinstance(queryset, Manager) else queryset
    query = qs.query
    deferred, is_defer = query.deferred_loading
    explicit = getattr(qs, "_fields", None) is not None or (bool(deferred) and not is_defer)
    walker = _Walker(qs.db, explicit_select=explicit)
    walker.query(query, root=True)
    projected, joined = _projection(qs, query)
    return Inspection(
        root=_root_model(query),
        models=frozenset(walker.models),
        referenced=frozenset(walker.refs) | frozenset(joined.values()),
        projected=projected,
        annotations=dict(walker.annotation_sources),
        low_mark=query.low_mark,
        high_mark=query.high_mark,
        joined=joined,
    )
