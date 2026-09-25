"""Determine which tables and columns a QuerySet references, or refuse.

The pre-execution checks (connector spec section 5) need every column the query *references*
-- ``WHERE``, ``ORDER BY``, ``GROUP BY``, annotations, projection -- not only those it
returns. Django resolves these to :class:`~django.db.models.expressions.Col` nodes on the
query and its compiler; this module walks them. Anything it cannot see through (``extra()``,
``RawSQL``, set operations, joined projections) is refused with :class:`Uninspectable`:
fetching less is never a risk, returning more is, so unknown means refuse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.apps import apps
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
    referenced: frozenset[FieldRef]
    projected: tuple[str, ...] | None
    annotations: dict[str, frozenset[FieldRef]]
    low_mark: int
    high_mark: int | None


class _Walker:
    def __init__(self, using: str) -> None:
        self.using = using
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


def _projection(qs: QuerySet[Any], query: Query) -> tuple[str, ...] | None:
    root = _root_model(query)
    concrete = {f.name for f in root._meta.concrete_fields}
    fields = getattr(qs, "_fields", None)
    if fields is not None:
        if not fields:
            return None
        names: list[str] = []
        extra = [a for a in query.annotation_select if a not in fields]
        for name in (*fields, *extra):
            if name in query.annotations:
                names.append(name)
            elif name == "pk":
                names.append(root._meta.pk.name)
            elif name in concrete:
                names.append(name)
            else:
                raise Uninspectable(f"projection of {name!r} is not a root-model field")
        return tuple(names)
    deferred, is_defer = query.deferred_loading
    if not deferred:
        return None
    if any("__" in name for name in deferred):
        raise Uninspectable("only()/defer() across relations is not supported")
    if is_defer:
        return tuple(f.name for f in root._meta.concrete_fields if f.name not in deferred)
    return tuple(f.name for f in root._meta.concrete_fields if f.name in deferred or f.primary_key)


def inspect(queryset: QuerySet[Any] | Manager[Any]) -> Inspection:
    """Everything the pre-execution checks need, or raise :class:`Uninspectable`."""
    if isinstance(queryset, RawQuerySet):
        raise Uninspectable("raw() querysets are not supported")
    qs: QuerySet[Any] = queryset.all() if isinstance(queryset, Manager) else queryset
    query = qs.query
    walker = _Walker(qs.db)
    walker.query(query, root=True)
    return Inspection(
        root=_root_model(query),
        models=frozenset(walker.models),
        referenced=frozenset(walker.refs),
        projected=_projection(qs, query),
        annotations=dict(walker.annotation_sources),
        low_mark=query.low_mark,
        high_mark=query.high_mark,
    )
