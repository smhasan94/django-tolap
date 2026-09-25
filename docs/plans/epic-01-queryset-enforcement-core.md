# Plan: E1 — QuerySet enforcement core

**Source:** `docs/03-epics.md` E1, `docs/02-prd.md` FR-1, FR-2, FR-7 to FR-13, FR-20.
**Complexity:** Large (11 stories).
**Written:** 2026-09-25 against Django 5.2 internals (verified in `django/db/models/sql/query.py`,
`where.py`, `expressions.py`, `lookups.py`) and `tolap-core` 1.0.0.

## Requirements restatement

Given a signed TOLAP `SecurityContext` and a Django `QuerySet`, return the rows the policy
allows as `list[dict]`, having (1) refused before any SQL if the context, object, referenced
fields, or QuerySet shape fail the checks, (2) pushed row filters, projection and limit into
the QuerySet where a faithful translation exists for the current vendor, (3) executed, and
(4) run upstream's `apply_result_pipeline` on the rows. Prove (2) never changes the result
of (4) with upstream fixtures and Hypothesis on SQLite and PostgreSQL.

## Patterns to mirror

No project code exists yet. Patterns come from upstream `tolap-core` and are recorded here so
later epics mirror them:

| Category | Source | Pattern |
| --- | --- | --- |
| Naming | `tolap_core/sql_rewriter.py` `prepare_sql_query`, `SqlQueryPreparation` | `prepare_*` returns a dataclass with `allowed`, `denial_reason`, `unpushable_filters`, `fully_pushed_down` |
| Errors | `tolap_core/enforcement.py` `AccessResult(allowed, reason)`; `UnenforceableResultError(PermissionError)` | Decisions are values; denials raised as `PermissionError` subclasses with reason only, never data |
| Fail-closed | `sql_rewriter.py` "narrow or leave alone, never widen"; `_coerce_mode` raises on unknown | Unknown → decline/deny, never default |
| Logging | `_LOG = logging.getLogger(__name__)`, `debug` on declines, `warning` on bypasses | Same |
| Tests | `sdk/python/tests/test_row_filter_operator_corpus.py` walks shared fixtures; `test_enforcement_mode_parity.py` compares both modes | Fixture-walk + parity assertion |

## Files to create

```
pyproject.toml                         # uv workspace root, ruff/mypy/pytest config
Makefile                               # test, lint, type, check
LICENSE, NOTICE, README.md
.github/workflows/ci.yml
packages/django-tolap/pyproject.toml
packages/django-tolap/django_tolap/__init__.py        # enforce, TolapDenied, __version__
packages/django-tolap/django_tolap/apps.py
packages/django-tolap/django_tolap/conf.py            # settings access + defaults
packages/django-tolap/django_tolap/checks.py          # Django system checks (E001–E003)
packages/django-tolap/django_tolap/exceptions.py      # TolapDenied, TolapSchemaMismatch, Uninspectable
packages/django-tolap/django_tolap/objects.py         # model -> object name, source id
packages/django-tolap/django_tolap/inspect.py         # referenced_fields, touched_models, inspectability
packages/django-tolap/django_tolap/precheck.py        # precheck(qs, policy) -> AccessResult
packages/django-tolap/django_tolap/pushdown.py        # compile_filter, prepare_queryset, Preparation
packages/django-tolap/django_tolap/lookups.py         # Like / NotLike lookups (registered per vendor)
packages/django-tolap/django_tolap/enforce.py         # enforce(qs, context, ...)
packages/django-tolap/django_tolap/py.typed
tests/conftest.py                                     # pytest-django settings, DATABASE_URL switch
tests/settings.py
tests/testapp/{__init__,models,apps}.py               # Patient, Encounter (FK), Region (FK)
tests/harness/__init__.py
tests/harness/fixtures.py                             # upstream fixture loader
tests/harness/seed.py                                 # rows matching upstream schema.sql
tests/harness/strategies.py                           # Hypothesis strategies
tests/harness/differential.py                         # assert_differential(qs, policy)
tests/fixtures/upstream/SOURCE                        # upstream commit + file list
tests/fixtures/upstream/**.json
tests/test_settings_checks.py
tests/test_inspect.py
tests/test_precheck.py
tests/test_compile_filter.py
tests/test_prepare_queryset.py
tests/test_enforce.py
tests/test_differential_fixtures.py
tests/test_differential_hypothesis.py
tests/test_null_handling.py
scripts/quickstart_check.sh
```

## Interfaces

```python
# django_tolap/objects.py
def object_name(model: type[Model]) -> str            # TOLAP object name (db_table default)
def source_id(model: type[Model]) -> str              # "db:<prefix>:<db_table>"

# django_tolap/inspect.py
@dataclass(frozen=True)
class FieldRef: model: type[Model]; name: str        # name is the column-level field name
@dataclass(frozen=True)
class Inspection:
    root: type[Model]
    models: frozenset[type[Model]]                    # every table the query touches (alias_map + subqueries)
    referenced: frozenset[FieldRef]                    # WHERE/ORDER/GROUP/annotations/values/only
    projected: tuple[str, ...] | None                  # caller's explicit projection, None = default cols
def inspect(qs: QuerySet) -> Inspection               # raises Uninspectable(reason)

# django_tolap/precheck.py
def precheck(qs: QuerySet, policy: EffectivePolicy) -> AccessResult
#   order: can_query -> validate_access(root, then each joined model) -> schema mismatch
#          -> validate_field_access(referenced as "<object>.<field>") -> inspectable

# django_tolap/pushdown.py
def compile_filter(rf: RowFilter, model: type[Model], vendor: str) -> Q | None
@dataclass
class Preparation:
    allowed: bool
    queryset: QuerySet | None
    denial_reason: str | None
    unpushable_filters: list[RowFilter]
    visible_fields: tuple[str, ...]
    @property fully_pushed_down -> bool
def prepare_queryset(qs: QuerySet, policy: EffectivePolicy) -> Preparation

# django_tolap/enforce.py
def enforce(qs: QuerySet | Manager, context: SecurityContext, *, hash_salt=None) -> list[dict]
```

Field-name convention: TOLAP field references are checked as `"<object>.<field>"` using the
model's `db_column`-independent field name (`field.name`), because upstream matching treats
`ssn` and `patients.ssn` as the same and matches case-insensitively in both directions. Rows
returned by `.values()` are keyed by field name, so the post pass sees the same names.

## Tasks

### Task 1 — E1-S1 scaffold
- Root `pyproject.toml`: `[tool.uv.workspace] members = ["packages/*"]`, dev deps
  (`pytest`, `pytest-django`, `hypothesis`, `ruff`, `mypy`, `django-stubs`, `psycopg[binary]`,
  `dj-database-url`), `[tool.ruff]` (py311, line 100, rules E,F,I,B,UP), `[tool.mypy]`
  strict with `django_stubs_ext`, `[tool.pytest.ini_options]` `DJANGO_SETTINGS_MODULE=tests.settings`.
- `packages/django-tolap/pyproject.toml`: hatchling, `requires-python >=3.11`,
  deps `Django>=5.2,<6.2`, `tolap-core>=1.0,<2`, `tolap-store>=1.0,<2`; extras `drf`.
- CI: matrix `{3.11,3.12,3.13,3.14} × {5.2,6.0,6.1}` minus invalid (6.x needs ≥3.12);
  steps `uv sync`, `make lint type test`.
- Validate: `uv sync && make check` green with a placeholder test.

### Task 2 — E1-S2 conf and checks
- `conf.py`: `DEFAULTS = {"HASH_SALT": None, "IDENTITY_RESOLVER": "django_tolap.identity.DjangoGroupsIdentityResolver", "OBJECT_NAME": "db_table", "CONTEXT_TTL": 3600, "SOURCE_PREFIX": None}`; `settings.SIGNING_KEY` property raises `ImproperlyConfigured`.
- `checks.py` registered in `apps.ready()`; tests use `override_settings`.
- Validate: `pytest tests/test_settings_checks.py`.

### Task 3 — E1-S3 fixtures and test models
- `tests/harness/fixtures.py`: `load_operator_corpus()`, `load_integration_scenarios(name)`;
  policies built with upstream `deserialize_effective_policy` after wrapping the fixture's
  bare policy in the required envelope fields (`userId`, `tenantId`, `sourceConnectionId`,
  `resolvedAt`, `expiresAt`, `sourceProfiles`, `integrity` placeholder) — record this wrapper
  in one helper so fixtures stay verbatim.
- `tests/testapp/models.py`: `Patient(id, full_name, email, ssn, date_of_birth, region
  null=True, status, score null=True)`, `Encounter(patient FK, kind, notes)`, `Region(code,
  name)` for join tests. `db_table="patients"` etc. to match upstream object names.
- Validate: fixture count test equals upstream file counts.

### Task 4 — E1-S4 inspect
- Refuse early: `qs.query.extra` non-empty, `qs.query.extra_tables`, `qs.query.combinator`,
  `RawQuerySet`, any `RawSQL` node encountered, `select_for_update` (writes are out of scope).
- Walk `qs.query.where` recursively: `WhereNode.children` → `Lookup` (`lhs`, `rhs`), nested
  `WhereNode`, `NothingNode` (fine), `ExtraWhere` (refuse), `SubqueryConstraint` (walk inner
  query). For any expression call `get_source_expressions()` recursively; collect `Col`
  (`col.target.model`, `col.target.name`), `Ref` (resolve via `query.annotations`),
  `Subquery`/`Exists` (recurse into `.query`), `OuterRef`/`ResolvedOuterRef` (resolve
  against outer), `RawSQL` (refuse), `Value`/`Star` (ignore; `Star` in `Count("*")` fine).
- `order_by`: strings → `query.resolve_ref` after stripping `-`; expressions → walk.
  `extra_order_by` → refuse.
- `group_by`: `True` → the selected cols; tuple → walk.
- `annotations`: walk each; annotation names are not model fields and are not checked
  against the policy, but their source columns are.
- `values_select` / `select` → `Col`s; `deferred_loading` → resolves `only()`/`defer()` to
  concrete names.
- `models`: root plus `join.join_field.related_model` for each `Join` in `alias_map`, plus
  subquery models.
- Validate: `tests/test_inspect.py` one test per construct, including a joined filter
  `filter(encounter__kind="x")` yielding `FieldRef(Encounter, "kind")`.

### Task 5 — E1-S5 precheck
- Reasons: upstream strings from `validate_access`; `"query references fields you do not
  have permission to access"` (upstream text) for field denial; `"policy references unknown
  field: <name>"` for schema mismatch; `"query cannot be inspected: <why>"`.
- Schema mismatch scope: for the root model only, each non-wildcard name in `rowFilters`,
  `hiddenFields`, `allowedFields`, `maskedFields` whose qualified object matches the root
  object name (or is bare) must resolve to a concrete field. Names qualified with another
  object are skipped (they belong to another source).
- Validate: `tests/test_precheck.py`.

### Task 6 — E1-S6 compile_filter and NULL study
- Operator table per FR-8. Vendor keyed: `{"postgresql": {like: True}, "sqlite": {like:
  False}, "mysql": {like: False}, "oracle": {like: False}}`; unknown vendor → `None` for
  every filter (post-only), logged once at warning.
- Coercion: `model_field.to_python(value)`; `ValidationError`/`TypeError` → `None`.
  `between` requires `values` of length 2, both coercible. `in` requires a list; empty →
  `Q(pk__in=[])`.
- `like`: `django_tolap/lookups.py` defines `Like(PatternLookup)` with `lookup_name="tolap_like"`
  emitting `%s LIKE %s` and `NotLike`; registered on `Field` at app ready. `rhs` passed
  verbatim (TOLAP `like` patterns already use SQL wildcards; `\` escape per spec §7). Only
  compiled when vendor is `postgresql`.
- NULL study (`tests/test_null_handling.py`): capture SQL for `exclude(region="x")`,
  `~Q(region="x")`, `~Q(region__in=[...])` on nullable `region` per vendor and assert row
  sets against upstream `apply_row_filters` for records with `region=None`. Decide from the
  result whether `compile_filter` adds `| Q(field__isnull=True)`; either way the differential
  test is the acceptance. Record the finding in `docs/decisions.md` under a dated entry.
- Validate: `tests/test_compile_filter.py` parametrized over operator × vendor.

### Task 7 — E1-S7 prepare_queryset
- Steps: `precheck` (deny → `Preparation(allowed=False)`), compile each filter, `qs.filter(q)`
  for each pushed `Q`, compute `visible_fields`:
  `concrete = [f.name for f in model._meta.concrete_fields]` → drop those denied by
  `validate_field_access([f"{obj}.{name}" ...])` → intersect with caller projection if any
  → union with fields named by any row filter (pushed or not) so the post pass can evaluate
  → if empty: deny `"no fields visible"`. Then `.values(*visible)`; slice
  `[:min(existing, max_results)]` respecting `low_mark`.
- `.values()` ordering: preserve caller order, then appended filter fields.
- Validate: `tests/test_prepare_queryset.py` asserts `str(prep.queryset.query)` contains the
  expected `WHERE`/`LIMIT` and projection on SQLite.

### Task 8 — E1-S8 enforce
- `validate_context` (skip when `enforce_signatures=False` is **not** offered: always verify),
  `validate_expiry`, then `prepare_queryset`, `list(prep.queryset)`, `apply_result_pipeline
  (rows, policy, hash_salt or settings.HASH_SALT)`. Single public function; `Manager`
  accepted via `.all()`.
- `TolapDenied(reason)`; message is the reason only.
- Validate: `tests/test_enforce.py` including a test that scans `django_tolap.__all__` for any
  callable that executes a QuerySet without the post pass (module-level assertion listing
  the only executing function).

### Task 9 — E1-S9 differential on SQLite
- `assert_differential(qs, policy)`: `left = apply_result_pipeline(list(prepare(qs).queryset),
  policy)`, `right = apply_result_pipeline(list(qs.values()), policy)`; compare as lists of
  dicts (order by `id` first). Also compare with the fixture's expected ids.
- Hypothesis: `policies()` builds `EffectivePolicy` from operator, field ∈ {region, status,
  score, full_name}, value strategies matching field type plus `None`; `hidden`/`allowed`
  subsets; `max_results` ∈ {None, 0..10}. `rows()` seeds ≤ 30 rows with nullable columns.
  Use `django_db` transactional fixture; Hypothesis profile `ci` = 500 examples, default 50.
- Validate: both test files green on SQLite.

### Task 10 — E1-S10 PostgreSQL leg
- `tests/settings.py` reads `DATABASE_URL` (dj-database-url); CI job with `postgres:17`
  service; `like` assertions vendor-conditional.
- Validate: CI green on both.

### Task 11 — E1-S11 README quickstart (in-code policy)
- README: install from git subdirectory, policy dict → `deserialize_effective_policy`, sign
  with `sign_context(build_security_context(...))`, `enforce()`.
- `scripts/quickstart_check.sh`: creates a temp project, installs the package, runs the
  snippet, asserts a dict list is printed. Wired into CI.

## Validation

```bash
uv sync
make lint        # ruff check . && ruff format --check .
make type        # mypy packages/django-tolap
make test        # pytest -q
DATABASE_URL=postgres://... make test
HYPOTHESIS_PROFILE=ci make test
scripts/quickstart_check.sh
```

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Django private internals (`query.where`, `alias_map`) differ across 5.2/6.0/6.1 | Medium | Matrix CI; inspection tests per construct; any `AttributeError` → `Uninspectable` (fail closed) |
| Django's `exclude()` NULL handling double-counts with an added `IS NULL` arm | Medium | Task 6 study before deciding; differential is the arbiter |
| `.values()` on joined fields returns `related__field` keys that upstream field matching does not map to `object.field` | Medium | v0.1 projects root-model fields only; joins allowed in filters, refused in projection unless explicitly `values("related__x")`, which is checked as `(Related, x)` and returned under its own key; documented |
| `tolap-core` 1.0.0 vs `main` API drift (e.g. `SqlEnforcementMode` absent in 1.0.0) | Low for E1 | We do not import the rewriter in package code; E4-S4 CI leg |
| Hypothesis finds a real divergence late | Medium | That is its job; removing a translation is always allowed |
| Fixture envelope wrapping drifts from upstream schema | Low | Wrapper in one helper; schema-validate wrapped policies in a test |

## Acceptance

- [ ] All eleven stories done and marked in `docs/03-epics.md`
- [ ] `make check` green on every matrix cell and on PostgreSQL
- [ ] Every upstream fixture case passes the differential assertion
- [ ] `scripts/quickstart_check.sh` passes in CI
