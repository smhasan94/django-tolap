# Plan: E6 — SQLAlchemy adapter

**Source:** `docs/03-epics.md` E6; FR-19. **Complexity:** Large. **Depends on:** E4-S3.

## Requirements restatement

`sqlalchemy_tolap.enforce(select, context, session)` with the same pre-checks, pushdown,
mandatory post pass and differential proof as Django, keyed by `dialect.name`.

## Patterns to mirror

Django package module layout and names (`inspect`, `precheck`, `pushdown`, `enforce`),
shared `tests/harness`.

## Files

```
packages/sqlalchemy-tolap/pyproject.toml            deps: SQLAlchemy>=2.0,<2.2, tolap-core
packages/sqlalchemy-tolap/sqlalchemy_tolap/{__init__,objects,inspect,precheck,pushdown,enforce,exceptions}.py
tests/harness/*                                      moved to a shared location importable by both test suites
tests/sqlalchemy/{conftest,models,test_inspect,test_precheck,test_pushdown,test_enforce,test_differential_*}.py
```

## Interfaces

```python
def inspect(stmt: Select) -> Inspection          # tables via stmt.get_final_froms() + subqueries; columns via
                                                # sqlalchemy.sql.visitors.iterate over whereclause, _order_by_clauses,
                                                # _group_by_clauses, selected columns; TextClause/literal_column -> Uninspectable
def precheck(stmt, policy) -> AccessResult
def compile_filter(rf, table: Table, dialect: str) -> ColumnElement | None
def prepare_select(stmt, policy, dialect) -> Preparation   # stmt.where(...), stmt.with_only_columns(...), stmt.limit(n)
def enforce(stmt, context, session, *, hash_salt=None) -> list[dict]
# rows = session.execute(prep.stmt).mappings().all() -> dicts keyed by column name
```

Object name: `Table.name`; field name: `Column.name`. ORM entities (`select(Patient)`) are
reduced to their mapped `Table` via `inspect(entity).local_table`; projection uses
`with_only_columns` of the visible `Column`s so results are mappings, never ORM instances.

## Tasks

1. **E6-S1.** Scaffold package; extract harness so Django tests and SQLAlchemy tests share
   fixture loading, strategies and `assert_differential`.
2. **E6-S2.** `inspect`/`precheck`; refuse `text()`, `literal_column`, CTE, `union`.
3. **E6-S3.** `compile_filter` (`==`, `!=` with `or_(col.is_(None))` per the NULL decision,
   `in_`, `not_in`, comparisons, `between`, `is_`, `is_not`, `like` on `postgresql` only);
   projection; limit.
4. **E6-S4.** `enforce`; differential on SQLite and PostgreSQL with the shared fixtures and
   strategies.
5. **E6-S5.** README section, FastAPI-style example; gap corpus for `str(stmt.compile())`.

## Validation

`make check`; both test suites on both vendors.

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| SQLAlchemy 2.0 vs 2.1 internals (`_raw_columns`, `_where_criteria`) | Medium | Use public accessors (`whereclause`, `selected_columns`, `get_final_froms`); CI on both |
| ORM-instance results leaking hidden attributes | Low | Always `with_only_columns` + `.mappings()` |

## Updated after E1–E5 (2026-09-25)

- No third shared package: ``matching.py`` is copied (parity-tested against upstream) and the
  field-rule helpers live in ``sqlalchemy_tolap/rules.py``. The test harness is shared from
  ``tests/harness`` (fixture loader, seed lists, strategies); the differential assertion is
  per adapter because the executors differ.
- SQLAlchemy does not add a null arm to negations the way Django does, so ``notEquals``,
  ``notIn`` and ``notLike`` render ``(col <> x OR col IS NULL)`` explicitly.
- PostgreSQL tests reuse Django's throwaway test database under schema ``tolap_sa``; SQLite
  uses an in-memory engine on a ``StaticPool``. Nothing touches a real database.
- Entity selects (``select(Entity)``, ``select(table)``) are the default projection; named
  columns and labels are explicit references, as in django-tolap. Tables are normalised to
  the MetaData-registered instance because the ORM hands out annotated copies.
