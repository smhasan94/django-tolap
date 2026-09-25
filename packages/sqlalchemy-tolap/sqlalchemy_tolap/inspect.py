"""Determine which tables and columns a ``Select`` references, or refuse.

Walks the statement's FROM list, WHERE, ORDER BY, GROUP BY, HAVING and projection with
``sqlalchemy.sql.visitors.iterate`` (which descends into correlated subqueries and EXISTS).
Anything opaque -- ``text()``, ``literal_column()``, unattached ``column()``, derived tables
(subquery/CTE/lateral in FROM), set operations -- is refused: fetching less is never a risk,
returning more is.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Column, Table
from sqlalchemy.sql import visitors
from sqlalchemy.sql.elements import ColumnClause, Label, TextClause
from sqlalchemy.sql.selectable import Alias, CompoundSelect, FromClause, Join, Select, TextualSelect

from sqlalchemy_tolap.exceptions import Uninspectable


@dataclass(frozen=True, order=True)
class ColRef:
    table: str
    name: str


@dataclass(frozen=True)
class Inspection:
    root: Table
    root_from: FromClause  # the FROM element itself: the Table, or an Alias of it
    tables: dict[str, Table]
    referenced: frozenset[ColRef]  # explicit references only; never a default projection
    projected: tuple[str, ...] | None  # names in the caller's explicit projection, else None
    selected: tuple[Any, ...]  # the selected column elements, in order
    annotations: dict[str, frozenset[ColRef]]
    limit: int | None
    offset: int | None


def canonical(table: Table) -> Table:
    """The MetaData-registered Table (ORM and aliasing hand out annotated copies)."""
    registered = table.metadata.tables.get(table.key)
    return registered if registered is not None else table


def base_table(column: Column[Any]) -> Table:
    owner = column.table
    if isinstance(owner, Table):
        return canonical(owner)
    if isinstance(owner, Alias) and isinstance(owner.element, Table):
        return canonical(owner.element)
    raise Uninspectable(f"column {column.name!r} belongs to a derived table")


class _Walker:
    def __init__(self) -> None:
        self.refs: set[ColRef] = set()
        self.tables: dict[str, Table] = {}

    def table(self, table: Table) -> None:
        table = canonical(table)
        self.tables[table.name] = table

    def froms(self, froms: Iterable[FromClause]) -> None:
        for f in froms:
            self.from_(f)

    def from_(self, f: FromClause) -> None:
        if isinstance(f, Table):
            self.table(f)
        elif isinstance(f, Join):
            self.from_(f.left)
            self.from_(f.right)
            if f.onclause is not None:
                self.nodes(f.onclause)
        elif isinstance(f, Alias) and isinstance(f.element, Table):
            self.table(f.element)
        else:
            raise Uninspectable(f"{type(f).__name__} in FROM is not supported")

    def nodes(self, element: Any) -> None:
        for node in visitors.iterate(element):
            self.node(node)

    def node(self, node: Any) -> None:
        if isinstance(node, TextClause | TextualSelect | CompoundSelect):
            raise Uninspectable(f"{type(node).__name__} is not supported")
        if isinstance(node, Select):
            # A nested select: its FROM list must be inspectable too (iterate does not
            # visit FROM tables as nodes).
            self.froms(node.get_final_froms())
            return
        if isinstance(node, Column):
            table = base_table(node)
            self.table(table)
            self.refs.add(ColRef(table.name, node.name))
            return
        if isinstance(node, ColumnClause):
            if node.is_literal and node.name == "*":
                return  # the ``SELECT *`` inside ``exists()``; discloses nothing by itself
            what = "literal_column()" if node.is_literal else "an unattached column()"
            raise Uninspectable(f"{what} is not supported")


def _entity_tables(stmt: Select[Any]) -> tuple[list[Table], int]:
    """Tables selected whole (``select(Entity)``, ``select(table)``) and the raw column count."""
    raw = list(stmt._raw_columns)
    tables: list[Table] = []
    for rc in raw:
        if isinstance(rc, Table):
            tables.append(canonical(rc))
        elif isinstance(rc, Alias) and isinstance(rc.element, Table):
            tables.append(canonical(rc.element))
    return tables, len(raw)


def inspect(stmt: Any) -> Inspection:
    if not isinstance(stmt, Select):
        raise Uninspectable(f"{type(stmt).__name__} is not a Select")
    walker = _Walker()
    froms = stmt.get_final_froms()
    if not froms:
        raise Uninspectable("statement has no FROM")
    walker.froms(froms)
    root_from: FromClause = froms[0]
    while isinstance(root_from, Join):
        root_from = root_from.left
    if isinstance(root_from, Table):
        root = canonical(root_from)
    elif isinstance(root_from, Alias) and isinstance(root_from.element, Table):
        root = canonical(root_from.element)
    else:
        raise Uninspectable(f"{type(root_from).__name__} as the root FROM is not supported")

    if stmt.whereclause is not None:
        walker.nodes(stmt.whereclause)
    for clause in (*stmt._order_by_clauses, *stmt._group_by_clauses, *stmt._having_criteria):
        walker.nodes(clause)

    # Projection: an entity/table select is a default projection (checked at prepare time,
    # like SELECT *); named columns and labelled expressions are explicit references.
    entity_tables, raw_count = _entity_tables(stmt)
    explicit = not entity_tables
    if entity_tables and raw_count != len(entity_tables):
        raise Uninspectable("mixing an entity with columns in the projection is not supported")
    if entity_tables and any(t is not root for t in entity_tables):
        raise Uninspectable("projection of an entity other than the root table is not supported")

    selected = tuple(stmt.selected_columns)
    projected: list[str] = []
    annotations: dict[str, frozenset[ColRef]] = {}
    if explicit:
        for col in selected:
            if isinstance(col, Column):
                table = base_table(col)
                if table is not root:
                    raise Uninspectable(
                        f"projection of {table.name}.{col.name} is not a root-table column"
                    )
                walker.refs.add(ColRef(table.name, col.name))
                projected.append(col.name)
            elif isinstance(col, Label):
                if col.name in root.columns:
                    # A row filter on that column would otherwise be evaluated against the
                    # label's value in the post pass. Django refuses the same shadowing.
                    raise Uninspectable(f"label {col.name!r} shadows a column of {root.name}")
                sub = _Walker()
                sub.tables = walker.tables
                sub.nodes(col.element)
                walker.refs |= sub.refs
                annotations[col.name] = frozenset(sub.refs)
                projected.append(col.name)
            else:
                raise Uninspectable("an unlabelled expression in the projection is not supported")

    return Inspection(
        root=root,
        root_from=root_from,
        tables=dict(walker.tables),
        referenced=frozenset(walker.refs),
        projected=tuple(projected) if explicit else None,
        selected=selected,
        annotations=annotations,
        limit=stmt._limit,
        offset=stmt._offset,
    )
