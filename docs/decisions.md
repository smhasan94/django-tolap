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
