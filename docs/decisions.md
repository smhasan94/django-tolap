# Decisions

Each halt and its answer, newest last. Format: date, question, options, decision, rationale.

## 2026-09-25 — Scope after discovering upstream's SQL rewriter

**Question.** Research showed the upstream Python SDK (`tolap_core.sql_rewriter`, present in
PyPI `tolap-core` 1.0.0) already pushes row filters, the result limit, and hidden-column
projection into raw SQL strings via a regex rewriter with dialect profiles (ansi, postgres,
mysql, trino, sqlserver). The prompt assumed only .NET did this. Upstream's README names
"an ORM owns the SQL" as the case where integrators fall back to `postOnly`. Is the gap
still worth filling, and how should the project be framed?

**Options.**
1. Reframe as ORM-native pushdown for Django QuerySet / SQLAlchemy Select, reusing
   upstream's semantic rules and shared fixtures.
2. Same, plus thin wrappers around upstream's rewriter for `Manager.raw()` / cursor paths.
3. Stop the project.

**Decision.** Option 1, with additions:
1. Keep the rest of the v0.1 scope unchanged: Django-model policy store with admin
   registration, DRF mixin, and the tool helper. Overview/README headline becomes "TOLAP
   policies managed in Django admin and enforced on your QuerySets", with ORM-native
   pushdown as a feature. State honestly that upstream's Python SDK already rewrites raw
   SQL strings.
2. Add a story to measure the gap: build a corpus of realistic QuerySets (related-field
   lookups/joins, annotations, subqueries, combined Q objects, values/only). For each,
   run upstream's rewriter on `str(qs.query)` and record where it declines or produces
   wrong SQL, next to our ORM-native result. Use the results in the README, the
   benchmark, and `docs/upstream-issue.md`.
3. Mirror upstream's semantic rules per database backend, not globally. Django lookups
   differ by vendor (e.g. `contains` is case-insensitive on SQLite). Run the differential
   tests (pushdown + post-pass == post-pass only) on at least SQLite and Postgres.
4. Before adding an `IS NULL` arm on negated filters, verify how Django's `exclude()` /
   `~Q` already handle nullable fields, so NULLs are not double-handled.
5. "Thin wrappers for raw()/cursor paths using upstream's rewriter" goes on the backlog
   as post-v0.1.

**Rationale.** Upstream itself says ORM-owned SQL is out of its rewriter's reach, so the
gap is real, and the admin-managed store plus QuerySet enforcement is the five-minute
value. Measuring the gap keeps the claims honest.

## 2026-09-25 — Which upstream release to depend on

**Question.** PyPI has `tolap-core`, `tolap-store`, `tolap-mcp` 1.0.0 (uploaded
2026-08-11, author "Amazon.com, Inc. or its affiliates"). The repository is at 1.1.0
(purpose binding, `SqlEnforcementMode`) and its README says the SDKs are not on any
registry. 1.0.0 has `apply_result_pipeline`, the `PolicyStore` protocol, signing, and the
SQL rewriter, but not `SqlEnforcementMode` or purpose binding.

**Options.**
1. Depend on PyPI 1.0.0 (`tolap-core>=1.0,<2`), and also test against a source build of
   upstream `main` in CI to catch 1.1 drift. Defer purpose binding to v0.2.
2. Require a source build of 1.1.0.
3. PyPI 1.0.0 only, ignore 1.1.0.

**Decision.** Option 1.

**Rationale.** Honors "depend on published packages" and the five-minute install, while
the source-build CI leg keeps us from being surprised when 1.1 ships.

## 2026-09-25 — Package naming

**Question.** Remote repo is `tolap-django`. Free on PyPI: `django-tolap`, `tolap-django`,
`sqlalchemy-tolap`, `tolap-sqlalchemy`. Amazon publishes `tolap-core`, `tolap-store`,
`tolap-mcp`, so a `tolap-*` name could read as official.

**Options.**
1. `django-tolap` + `sqlalchemy-tolap` (imports `django_tolap`, `sqlalchemy_tolap`).
2. `tolap-django` + `tolap-sqlalchemy`.
3. Single `tolap-orm` with extras.

**Decision.** Option 1. Repository name stays as-is unless the owner renames it.

**Rationale.** Follows the `django-*` convention and avoids the official-looking prefix.

## 2026-09-25 — Repository layout

**Question.** One monorepo or separate repos for the Django and SQLAlchemy packages?

**Options.**
1. Monorepo, uv workspace: `packages/django-tolap`, `packages/sqlalchemy-tolap`, shared
   differential-test harness and fixture loader, one CI.
2. Separate repos.

**Decision.** Option 1.

**Rationale.** Parity tests between the two adapters are easiest with a shared harness.

## 2026-09-25 — Supported versions

**Question.** Which Python, Django, and SQLAlchemy versions does v0.1 support?

**Options.**
1. Python 3.11–3.14, Django 5.2/6.0/6.1, SQLAlchemy 2.0/2.1.
2. Python 3.12–3.14, Django 6.0/6.1, SQLAlchemy 2.1 only.
3. Python 3.10–3.14, Django 4.2/5.2/6.x, SQLAlchemy 2.0/2.1.

**Decision.** Option 1.

**Rationale.** Python 3.10 reaches end-of-life 2026-10. Django 4.2 extended support ended
2026-04. Option 1 covers the current LTS (5.2, supported to 2028-04) and both 6.x lines with
a small CI matrix.

## 2026-09-25 — Schema mismatch behavior

**Question.** A policy references a field or object the Django model does not have. What
does enforcement do?

**Options.**
1. Deny the query with a clear reason; admin shows a validation warning on save.
2. Ignore unknown hidden/masked fields, deny only on unknown row-filter fields.
3. Configurable, default deny.

**Decision.** Option 1.

**Rationale.** Fail closed, consistent with upstream's rule that a row filter on an absent
field drops every row. A typo in a hidden-field name must be visible, not silently harmless.

## 2026-09-25 — Store timing

**Question.** Does the Django-model policy store (models, migrations, admin) ship in v0.1?

**Options.**
1. v0.1.
2. v0.2, with v0.1 using upstream's `InMemoryPolicyStore` or a JSON file.

**Decision.** Option 1.

**Rationale.** The agreed headline is "policies managed in Django admin and enforced on your
QuerySets"; without the store the quickstart has no admin.

## 2026-09-25 — NULL handling for pushed negative filters (E1-S6 study)

**Question.** Upstream requires a pushed-down negative filter to keep rows whose column is
`NULL` (`(col <> 'x' OR col IS NULL)`). Does Django already do this, so we must not add a
second `IS NULL` arm?

**Finding.** Django compiles `~Q(f=x)`, `exclude(f=x)`, `~Q(f__in=[...])`, `~Q(f__gt=x)`,
`~Q(f__range=...)` on a nullable field to `NOT (f = x AND f IS NOT NULL)`, which keeps null
rows. On a `NOT NULL` column it emits plain `NOT (f = x)`. Row sets on SQLite match
upstream `apply_row_filters` for `notEquals` and `notIn` with null rows present. A plain
`f__in=[..., None]` drops the `None` member, so `in` with a null member gets an explicit
`| Q(f__isnull=True)`, and `equals null` compiles to `f__isnull=True`.

**Decision.** Do not add an `IS NULL` arm to negated lookups; rely on Django's negation.
Add the arm only for `in` with a null member. Pinned by `tests/test_null_handling.py` on
every vendor in CI.

**Also decided while writing the compiler (stricter than upstream where noted).**
- String equality (`equals`, `notEquals`, `in`, `notIn`) is pushed only where `=` is
  case-sensitive: PostgreSQL and SQLite. Upstream pushes it on MySQL; we decline there.
- String ordering (`greaterThan`…, `between`) is pushed only on SQLite (byte-wise `BINARY`
  collation matches Python's code-point ordering). PostgreSQL's locale collation can order
  `'a' < 'B'`, which Python does not, so it is declined there. Upstream pushes it.
- A field with an explicit `db_collation` disables every string operator.
- Only `str`, `int`, `float`, `bool` field kinds are pushed for value operators; a policy
  value whose Python type the driver would not return for that field (e.g. `"10"` on an
  integer column, a string on a date column) is declined, because the post pass drops such
  rows as non-comparable and SQL might not.

## 2026-09-25 — The result limit is pushed only when every row filter was pushed

**Question.** Hypothesis (SQLAlchemy adapter, PostgreSQL) found a policy with an unpushable
filter (`startsWith`) and `maxResults` where pushdown returned fewer rows than post-pass
only: `LIMIT n` truncated the database result before the post pass removed non-matching
rows, so fewer than `n` qualifying rows came back.

**Options.**
1. Push the limit only when `unpushable_filters` is empty (both adapters).
2. Push the limit always, as upstream's string rewriter does.
3. Push an inflated limit.

**Decision.** Option 1. The caller's own slice is still honoured as written (it is their
semantics), and it is narrowed to `maxResults` only when all filters were pushed.

**Rationale.** Upstream's spec says the limit runs last "so filtering never yields fewer rows
than maxResults when more qualifying rows exist"; pushing it ahead of an unpushed filter
breaks exactly that. Option 3 changes which rows are returned. The differential property is
the arbiter and it now holds on both adapters and both databases.

## 2026-09-25 — MySQL: assignment unique key shrunk to fit 3072 bytes

**Question.** The first MySQL run of the suite failed in migration `0001`: the unique
constraint on `PolicyAssignment` (`policy` 128 + `assignee_type` 32 + `assignee_identifier`
255 + `tenant_id` 255 + `source_connection_id` 255 = 925 characters) is 3700 bytes under
`utf8mb4`, over InnoDB's 3072-byte key limit. `django-tolap` 0.1.0 therefore cannot be
installed on MySQL 8 (utf8mb4 default) or MariaDB. Fixing it changes a released schema.

**Options.**
1. `tenant_id` and `source_connection_id` 255 → 128 (key 2684 bytes); edit `0001` so fresh
   installs work on MySQL and add `0002` (`AlterField`) so existing PostgreSQL/SQLite installs
   converge on the same schema.
2. Add `0002` only, leaving `0001` as released. Does not fix MySQL: `0001` still fails there.
3. Keep the widths and put the unique constraint on a SHA-256 `scope_key` column.

**Decision.** Option 1, released as 0.1.1. Upstream `tolap-core` places no length on tenant or
connection ids; 128 characters covers every real identifier we have seen. Rows with longer
values would block `0002`, which is the correct failure.

**Rationale.** `0001` never succeeded on MySQL, so editing it cannot strand a MySQL install.
For PostgreSQL and SQLite the end state after `0002` is identical whether `0001` ran at 255
or 128. Option 3 hides the constraint from the admin's error messages and needs a data
migration for no benefit.

## 2026-09-25 — Differential harness: a limit under a non-total ORDER BY compares counts only

**Question.** Hypothesis on MySQL found `SELECT id, full_name ... ORDER BY full_name` with
`maxResults` returning different rows with pushdown than without: several rows share an
empty `full_name`, and MySQL's `LIMIT` plan (priority-queue filesort) orders ties differently
from the unlimited plan. SQL does not define the order among ties, so both are correct.

**Decision.** `assert_differential` in both harnesses compares only the row count when a limit
was pushed and the statement's `ORDER BY` does not include the primary key (`total_order`).
Previously only the no-`ORDER BY` case was treated this way. The corpus keeps the
`ORDER BY full_name` statements so the count check still runs on them.

**Rationale.** The property is "pushdown never changes what the post pass returns"; among tied
rows the post pass itself has no defined answer. Requiring a total order in the corpus
would hide that real queries are written this way.

## 2026-09-25 — MySQL test driver: mysqlclient

**Decision.** The dev dependency for the MySQL leg is `mysqlclient`, Django's recommended
driver and what users run, rather than pure-Python PyMySQL. CI installs
`default-libmysqlclient-dev`; macOS needs `brew install mysql-client` and, when the Python is
a universal2 build, the environment in `CONTRIBUTING.md`. The SQLAlchemy fixtures use
`mysql+mysqldb` and a second throwaway database `test_tolap_sa`, since MySQL has no schemas
below a database.
