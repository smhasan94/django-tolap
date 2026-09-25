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
    columns: dict[str, ColRef]  # every projected key that is a plain column, by caller key
    renamed: dict[str, ColRef]  # the subset that is a column of another table or a label
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
        self.leaves: list[str] = []  # post-pass table name of every FROM leaf walked

    def table(self, table: Table) -> None:
        table = canonical(table)
        self.tables[table.name] = table

    def leaf(self, table: Table) -> None:
        """A Table or Alias in the FROM list itself, as opposed to a column reference."""
        self.table(table)
        self.leaves.append(canonical(table).name)

    def froms(self, froms: Iterable[FromClause]) -> None:
        for f in froms:
            self.from_(f)

    def from_(self, f: FromClause) -> None:
        if isinstance(f, Table):
            self.leaf(f)
        elif isinstance(f, Join):
            self.from_(f.left)
            self.from_(f.right)
            if f.onclause is not None:
                self.nodes(f.onclause)
        elif isinstance(f, Alias) and isinstance(f.element, Table):
            self.leaf(f.element)
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
            # visit FROM tables as nodes), but it is not part of the statement's own FROM.
            inner = _Walker()
            inner.tables = self.tables
            inner.froms(node.get_final_froms())
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


def _each_table_once(leaves: list[str]) -> None:
    """Refuse a post-pass table name that two FROM leaves share.

    The post pass sees every plain column as ``table.column``, so a second copy of a table
    (a self-join, two aliases of one table, two schemas' tables of one name) would be
    indistinguishable from the first, and a row filter on that name could only be evaluated
    against one of them.
    """
    seen: set[str] = set()
    for name in leaves:
        if name in seen:
            raise Uninspectable(f"two FROM entries share the post-pass name {name}")
        seen.add(name)


def _once(columns: dict[str, ColRef], key: str, ref: ColRef) -> None:
    """Record a plain column under the caller's key; a column projected twice is refused.

    Two keys for one column would collide on the ``table.column`` key the post pass sees.
    """
    for other, seen in columns.items():
        if seen == ref:
            raise Uninspectable(
                f"column {ref.table}.{ref.name} is projected twice ({other!r} and {key!r})"
            )
    columns[key] = ref


def _no_shadow(key: str, ref: ColRef | None, root: Table) -> None:
    """Refuse a projection key named like a root column unless it is that very column.

    A row filter on that column would otherwise be evaluated against the other value in
    the post pass, and a filtered root column added to the projection would collide with
    it. Django refuses the same shadowing.
    """
    if "." in key:
        # Qualified keys are what the post pass sees renamed columns under (``table.column``).
        raise Uninspectable(f"projection key {key!r} contains a dot")
    root_names = {c.name.lower(): c.name for c in root.columns}
    own = root_names.get(key.lower())
    if own is not None and ref != ColRef(root.name, own):
        raise Uninspectable(f"projection key {key!r} shadows a column of {root.name}; label it")


def inspect(stmt: Any) -> Inspection:
    if not isinstance(stmt, Select):
        raise Uninspectable(f"{type(stmt).__name__} is not a Select")
    walker = _Walker()
    froms = stmt.get_final_froms()
    if not froms:
        raise Uninspectable("statement has no FROM")
    walker.froms(froms)
    _each_table_once(walker.leaves)  # the statement's own FROM list, walked just above
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
    columns: dict[str, ColRef] = {}
    renamed: dict[str, ColRef] = {}
    annotations: dict[str, frozenset[ColRef]] = {}
    if explicit:
        for col in selected:
            if isinstance(col, Column):
                ref = ColRef(base_table(col).name, col.name)
                if ref.table != root.name:
                    # The row's key is the column name; it must not collide with a root
                    # column the post pass may need (a filtered field is projected too).
                    _no_shadow(col.name, ref, root)
                    renamed[col.name] = ref
                _once(columns, col.name, ref)
                walker.refs.add(ref)
                projected.append(col.name)
            elif isinstance(col, Label) and isinstance(col.element, Column):
                # A plain column under another key is still that column: pre-checked and
                # masked as such, never treated as a derived value.
                ref = ColRef(base_table(col.element).name, col.element.name)
                _no_shadow(col.name, ref, root)
                _once(columns, col.name, ref)
                walker.refs.add(ref)
                renamed[col.name] = ref
                projected.append(col.name)
            elif isinstance(col, Label):
                _no_shadow(col.name, None, root)
                sub = _Walker()
                sub.tables = walker.tables
                sub.nodes(col.element)
                walker.refs |= sub.refs
                annotations[col.name] = frozenset(sub.refs)
                projected.append(col.name)
            else:
                raise Uninspectable("an unlabelled expression in the projection is not supported")
        duplicates = sorted({n for n in projected if projected.count(n) > 1})
        if duplicates:
            raise Uninspectable(f"projection key {duplicates[0]!r} is used twice; label it")

    return Inspection(
        root=root,
        root_from=root_from,
        tables=dict(walker.tables),
        referenced=frozenset(walker.refs),
        projected=tuple(projected) if explicit else None,
        selected=selected,
        columns=columns,
        renamed=renamed,
        annotations=annotations,
        limit=stmt._limit,
        offset=stmt._offset,
    )
