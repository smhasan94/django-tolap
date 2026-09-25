# Epics and stories

*Phase 3 deliverable, 2026-09-25. Status values: todo / in progress / done / reviewed.
Keep this file current after every story.*

Ordering: by dependency, then time-to-first-value. Epic 1 ends with something a developer
can `pip install` from a git URL and demo. Each story is sized for about one day.

| Epic | Title | Status |
| --- | --- | --- |
| E1 | QuerySet enforcement core (installable, demoable) | reviewed |
| E2 | Django-model policy store, admin, contexts | reviewed |
| E3 | Tool helper and DRF integration | reviewed |
| E4 | Differential hardening and gap measurement | reviewed |
| E5 | Example app, benchmark, README, upstream issue | reviewed |
| E6 | SQLAlchemy adapter | in progress |

---

## E1. QuerySet enforcement core — status: reviewed

Outcome: `pip install git+…#subdirectory=packages/django-tolap`, then
`enforce(Patient.objects.filter(...), context)` returns post-passed dicts with pushdown, on
SQLite and PostgreSQL, proven equal to post-pass-only against upstream fixtures.

| Story | Title | FRs | Depends on | Status |
| --- | --- | --- | --- | --- |
| E1-S1 | Monorepo scaffold and CI skeleton | FR-1, FR-20 | — | done |
| E1-S2 | App config, settings, system checks | FR-1, FR-2 | E1-S1 | done |
| E1-S3 | Upstream fixture loader and test models | FR-13 | E1-S1 | done |
| E1-S4 | QuerySet field extraction and inspectability | FR-7 | E1-S2 | done |
| E1-S5 | Pre-execution checks | FR-7, FR-11 | E1-S4 | done |
| E1-S6 | Row-filter compiler (vendor rules) | FR-8 | E1-S3, E1-S5 | done |
| E1-S7 | Projection, limit, `Preparation` | FR-9, FR-10 | E1-S6 | done |
| E1-S8 | `enforce()` with mandatory post pass | FR-12 | E1-S7 | done |
| E1-S9 | Differential suite: fixtures + Hypothesis on SQLite | FR-13 | E1-S8 | done |
| E1-S10 | PostgreSQL CI leg and `like` pushdown proof | FR-8, FR-13, FR-20 | E1-S9 | done |
| E1-S11 | README quickstart (in-code policy) | FR-1 | E1-S8 | done |

**E1-S1 Monorepo scaffold and CI skeleton.**
AC: `uv sync` works; `packages/django-tolap/pyproject.toml` (name `django-tolap`, import
`django_tolap`, deps Django/tolap-core/tolap-store, Python ≥ 3.11); root `pyproject.toml` uv
workspace; `ruff`, `mypy --strict` (django-stubs), `pytest-django` configured; GitHub Actions
matrix Python 3.11–3.14 × Django 5.2/6.0/6.1 (valid pairs only) on SQLite; LICENSE
(Apache-2.0), NOTICE; `make test lint type`.

**E1-S2 App config, settings, system checks.**
AC: `django_tolap.apps.DjangoTolapConfig`; `TOLAP` settings read through
`django_tolap.conf.settings` with defaults; system check `django_tolap.E001` for missing
`SIGNING_KEY`, `E002` for bad `IDENTITY_RESOLVER` path, `E003` for bad `OBJECT_NAME`;
tests for each check.

**E1-S3 Upstream fixture loader and test models.**
AC: `tests/fixtures/upstream/` populated from upstream tag `v1.0.0`-equivalent commit
(recorded in `tests/fixtures/upstream/SOURCE`); loader yields `(name, EffectivePolicy,
records, expected)` for `apply-row-filters-all-operators.json` and integration scenarios;
test app `tests/testapp` with `Patient` matching upstream `schema.sql` columns and a nullable
`region`; seed helper replicating upstream's seeded rows.

**E1-S4 QuerySet field extraction and inspectability.**
AC: `django_tolap.inspect.referenced_fields(qs) -> set[str]` returns dotted names for
`WHERE` (walks `query.where`), `ORDER BY`, `GROUP BY`, annotations, `values()`/`only()`
including joined paths as `related.field`; raises `Uninspectable` for `.extra()`, `RawSQL`,
`RawQuerySet`, combinators; tests per construct; `distinct`, `select_related`,
`prefetch_related` documented as supported or refused with tests.

**E1-S5 Pre-execution checks.**
AC: `django_tolap.checks.precheck(qs, policy) -> AccessResult` runs `can_query`, upstream
`validate_access(object_name)`, upstream `validate_field_access(referenced)`, and schema
mismatch (unknown non-wildcard field names in any rule for this model); reasons are upstream
strings or the FR-11 string; unit tests for each denial and for precedence.

**E1-S6 Row-filter compiler (vendor rules).**
AC: `django_tolap.pushdown.compile_filter(rf, model, vendor) -> Q | None`; operator table
per FR-8 AC1–AC4; value coercion via `model_field.to_python`; empty `in` → `Q(pk__in=[])`;
`between` → `__range`; `like`/`notLike` via a registered `Like` lookup only on `postgresql`;
never `contains`/`startsWith`/`matches`; unit tests per operator per vendor
(vendor parametrized, SQLite executes, others assert the `Q` or `None`).
Include the NULL investigation: a test that prints and asserts Django's SQL for
`exclude(region="x")` on nullable `region` per vendor before deciding whether to add
`| Q(region__isnull=True)`; record the finding in the story notes and `docs/decisions.md`.

**E1-S7 Projection, limit, `Preparation`.**
AC: `prepare_queryset(qs, policy) -> Preparation` applies compiled `Q`s, computes
`visible_fields` (FR-9), keeps filtered fields projected, applies `.values(*visible)`, slices
to `maxResults` (narrowest wins); `allowedFields: []` → denied `no fields visible`;
`unpushable_filters`, `fully_pushed_down`; `str(prep.queryset.query)` shown in tests.

**E1-S8 `enforce()` with mandatory post pass.**
AC: `django_tolap.enforce(qs, context, *, hash_salt=None)` validates context (signature,
expiry) via upstream, then `precheck`, `prepare_queryset`, executes, then upstream
`apply_result_pipeline`; returns `list[dict]`; `TolapDenied` on any denial with reason;
no public path executes without the post pass (test greps public API); accepts a `Manager`.

**E1-S9 Differential suite: fixtures + Hypothesis on SQLite.**
AC: For every upstream fixture case: `post(execute(prepare(qs)))` == `post(execute(qs))`
and equals the fixture's expected ids; Hypothesis strategies for policies (all operators,
values incl. None, hidden/allowed sets, limits) and rows (nullable region/score/name);
`hypothesis` profile `ci` with ≥ 500 examples; failures shrink to a minimal policy.

**E1-S10 PostgreSQL CI leg and `like` pushdown proof.**
AC: CI job with a `postgres` service runs the full suite with `DATABASE_URL`; `like`/
`notLike` shown pushed on PostgreSQL and unpushed on SQLite; NULL-arm differential passes on
both vendors.

**E1-S11 README quickstart (in-code policy).**
AC: README shows install from git, a policy dict deserialized with upstream
`deserialize_effective_policy`, `sign_context`, and `enforce()`; a script in
`scripts/quickstart_check.sh` executes the README snippet against a fresh project in CI.

---

## E2. Django-model policy store, admin, contexts — status: reviewed

Outcome: policies authored in Django admin; `issue_context()` resolves, merges (upstream),
signs; quickstart no longer needs an in-code policy.

| Story | Title | FRs | Depends on | Status |
| --- | --- | --- | --- | --- |
| E2-S1 | Models and migrations | FR-3 | E1-S2 | done |
| E2-S2 | `DjangoPolicyStore` and identity resolver | FR-3, FR-5 | E2-S1 | done |
| E2-S3 | Store conformance against upstream fixtures | FR-3 | E2-S2 | done |
| E2-S4 | Admin registration and validation | FR-4, FR-11 | E2-S2 | done |
| E2-S5 | Audit log | FR-3 | E2-S2 | done |
| E2-S6 | `issue_context()` and external contexts | FR-6 | E2-S2 | done |
| E2-S7 | README quickstart on the admin store | FR-1 | E2-S4, E2-S6 | done |

**E2-S1 Models and migrations.**
AC: `PolicyDefinition(name unique, body JSONField, description, priority, active,
created/updated)`, `PolicyAssignment(policy FK, assignee_type, assignee_identifier,
tenant_id, source_connection_id, active, expires_at, revoked_at, granted_by, granted_at,
reason)`, `PolicyAuditLog`; unique `(policy, assignee_type, assignee_identifier, tenant_id,
source_connection_id)`; migration `0001`; `makemigrations --check` clean in CI.

**E2-S2 `DjangoPolicyStore` and identity resolver.**
AC: all `PolicyStore` methods; `get_assignments` filters active/unexpired/unrevoked in SQL;
`resolve_policy` calls upstream `resolve`; `save_definition_json(dict)` validates via upstream
deserializer; `assign(...)` convenience; `DjangoGroupsIdentityResolver`; mypy protocol
conformance test.

**E2-S3 Store conformance against upstream fixtures.**
AC: Load `fixtures/policies`, `fixtures/assignments`, `fixtures/merge-scenarios` into the
store; resolved policies' canonical bytes equal `InMemoryPolicyStore` output for the same
inputs.

**E2-S4 Admin registration and validation.**
AC: `ModelAdmin`s with list filters/search; JSON body validated on save with upstream
errors inline; schema-drift warnings per registered model (`django_tolap.registry.register
(Model, object_name=...)`); "resolve preview" action form.

**E2-S5 Audit log.**
AC: Every store mutation and resolve writes a row with upstream `PolicyAuditEvent` fields;
admin read-only view; optional `on_audit` callback.

**E2-S6 `issue_context()` and external contexts.**
AC: `issue_context(user_id, tenant_id, source, *, store=None, ttl=None)` returns a signed
`SecurityContext`; `enforce()` accepts one produced by upstream `deserialize_context`;
tests for tampered/expired refusal ordering.

**E2-S7 README quickstart on the admin store.**
AC: README quickstart is the §4.2 flow from the overview; `scripts/quickstart_check.sh`
updated; time-to-first-value walkthrough measured under five minutes by the script's steps.

---

## E3. Tool helper and DRF integration — status: reviewed

| Story | Title | FRs | Depends on | Status |
| --- | --- | --- | --- | --- |
| E3-S1 | `tolap_tool` decorator and `tolap_context` | FR-15 | E2-S6 | done |
| E3-S2 | Interop test with upstream `tolap-mcp` wrapper | FR-15 | E3-S1 | done |
| E3-S3 | DRF viewset and serializer mixins | FR-16 | E3-S1 | done |
| E3-S4 | DRF write-method refusal and schema hiding | FR-16 | E3-S3 | done |

**E3-S1.** AC: `ToolContext` with `.policy`, `.context`, `.enforce(qs)`, `.deny(reason)`;
identity from kwargs or `TOLAP["IDENTITY"]` callable; missing identity denies;
`TolapDenied` carries reason only.
**E3-S2.** AC: example test wraps the same function with upstream `SecureMcpToolWrapper`
(`tolap-mcp` as a test dependency) and shows both layers enforce without conflict.
**E3-S3.** AC: `TolapViewSetMixin.get_queryset()` enforced; list/retrieve return dicts;
`TolapSerializerMixin` drops hidden fields; tenant from `TOLAP["TENANT_RESOLVER"]`.
**E3-S4.** AC: `readOnly` policy refuses POST/PUT/PATCH/DELETE with 403 and upstream
reason; OpenAPI schema (drf-spectacular if installed, else DRF's) omits hidden fields.

---

## E4. Differential hardening and gap measurement — status: reviewed

| Story | Title | FRs | Depends on | Status |
| --- | --- | --- | --- | --- |
| E4-S1 | Hypothesis on PostgreSQL in CI, joined-field filters | FR-13 | E1-S10 | done |
| E4-S2 | Realistic QuerySet corpus vs upstream rewriter | FR-14 | E1-S8 | done |
| E4-S3 | `docs/gap-report.md` generator | FR-14 | E4-S2 | done |
| E4-S4 | Upstream-`main` CI leg | FR-20 | E1-S1 | done |
| E4-S5 | MySQL rules implemented, marked untested | FR-8 | E1-S6 | done (landed in E1-S6: `VENDORS["mysql"]`, per-vendor tests, README says untested) |

**E4-S1.** AC: Hypothesis `ci` profile on the PostgreSQL job; strategies extended with
policies filtering on `related.field` through a FK; differential holds.
**E4-S2.** AC: ≥ 20 QuerySets per FR-14 AC1; harness records upstream `prepare_sql_query`
outcome on `str(qs.query)` with `dialect=postgres` and whether the output executes.
**E4-S3.** AC: `python -m tests.gap_report` writes `docs/gap-report.md`; committed; CI fails
if the file is stale.
**E4-S4.** AC: job installs `tolap-core` from `git+https://github.com/awslabs/tolap` subdir,
runs the suite, `continue-on-error: true`, summary annotation.
**E4-S5.** AC: `mysql` vendor table matches upstream's mysql profile (`like` not pushed);
tests assert the `Q`/`None` without executing; README compatibility table says "untested".

---

## E5. Example app, benchmark, README, upstream issue — status: reviewed

| Story | Title | FRs | Depends on | Status |
| --- | --- | --- | --- | --- |
| E5-S1 | `examples/clinic` app with seed command | FR-17 | E2-S7 | done |
| E5-S2 | Benchmark script: SQL, rows fetched, RSS, latency | FR-17 | E5-S1 | done |
| E5-S3 | README rewrite with benchmark headline and gap summary | FR-17, FR-14 | E5-S2, E4-S3 | done |
| E5-S4 | `docs/upstream-issue.md` | FR-18 | E5-S3 | done |

**E5-S1.** AC: `Patient` across regions; `manage.py seed_patients --rows 1000000`; one
`patients_search` tool via `@tolap_tool`.
**E5-S2.** AC: `manage.py benchmark` runs pushdown vs post-only (post-only = `enforce()`
with pushdown disabled via an internal flag used only here), prints SQL, rows fetched
(`connection.queries` + cursor rowcount), peak RSS (`resource`), wall time; SQLite and
PostgreSQL.
**E5-S3.** AC: README headline table from E5-S2 output; honest statement about upstream's
string rewriter; compatibility table; quickstart intact.
**E5-S4.** AC: Draft issue: problem, what the adapters do, gap-report numbers, ask whether
upstream would link or host; halt for the owner to post.

---

## E6. SQLAlchemy adapter — status: in progress

| Story | Title | FRs | Depends on | Status |
| --- | --- | --- | --- | --- |
| E6-S1 | Package scaffold, shared harness extraction | FR-19 | E4-S3 | done |
| E6-S2 | `Select` inspection and pre-checks | FR-19 | E6-S1 | done |
| E6-S3 | Filter compiler and projection for `Select` | FR-19 | E6-S2 | todo |
| E6-S4 | `enforce()` + differential suite on SQLite/PostgreSQL | FR-19 | E6-S3 | todo |
| E6-S5 | README and gap corpus for SQLAlchemy | FR-19, FR-14 | E6-S4 | todo |

**E6-S1.** AC: `packages/sqlalchemy-tolap`; shared `tests/harness` (fixture loader,
Hypothesis strategies, differential assertion) importable by both packages.
**E6-S2.** AC: referenced columns from `whereclause`, `order_by`, `group_by`, selected
columns, joins; refuse `text()` fragments and CTE/union.
**E6-S3.** AC: same operator table keyed by `dialect.name`; `.with_only_columns()` for
projection; `.limit()`.
**E6-S4.** AC: FR-13 equivalents pass on both vendors.
**E6-S5.** AC: quickstart for FastAPI-style usage; gap table for `str(select.compile())`.
