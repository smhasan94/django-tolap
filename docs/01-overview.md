# django-tolap: project overview

*Phase 1 deliverable. Written 2026-09-25 against `awslabs/tolap` at 1.1.0 (main) and the
PyPI releases `tolap-core`, `tolap-store`, `tolap-mcp` 1.0.0.*

**One line.** TOLAP policies managed in Django admin and enforced on your QuerySets, with
ORM-native pushdown so the database does the filtering instead of your process.

---

## 1. The problem

### Who has it

Teams exposing Django (or SQLAlchemy) data to an AI agent through a tool: an MCP server, a
LangChain/Pydantic AI/Strands tool, a Bedrock Agent action group, a DRF endpoint the agent
calls. The tool holds a live ORM connection. The agent decides what to ask for.

### What goes wrong today

Application authorization (`django-guardian`, `rules`, DRF permission classes) answers "may
this user call this view?" It does not answer "which rows and columns may this call return?"
That second question is what an agent tool needs, because the agent composes its own request
and the tool code never anticipated every shape.

AWS open-sourced TOLAP (Tool-Object Level Access Protocol) on 2026-09-22 to answer exactly
that question: a signed, merged, most-restrictive-wins policy that says which objects, fields
and rows a principal may see through a tool, and how fields are masked
([announcement](https://aws.amazon.com/blogs/opensource/introducing-tolap-object-level-access-control-for-ai-agent-tools/),
[repo](https://github.com/awslabs/tolap)). Its post-execution pass is the security boundary
and always runs. It ships fourteen agent-framework integrations. It ships **no data-layer
integration**.

For Python, TOLAP does ship a SQL rewriter (`tolap_core.sql_rewriter`) that pushes row filters
into `WHERE`, the result limit into `LIMIT`, and hidden columns out of `SELECT`. It works on a
**raw SQL string**, with a regex scanner and no SQL grammar. Upstream's own docs say when it
does not apply
([implementation guide](https://github.com/awslabs/tolap/blob/main/docs/implementation-guide-python.md)):

> Choose `post_only` when you will not have your SQL edited: a statement the rewriter's parser
> does not handle, a stored procedure, **an ORM that owns its own SQL**, or a reviewer who needs
> the query that ran to be the query they wrote. The cost is that the database returns rows and
> columns the post pass then discards.

So a Django tool today has three choices, all bad:

1. **Post-only.** `Patient.objects.all()` runs unrestricted. Every row and every column crosses
   the wire, lands in memory, possibly in logs and APM traces, and is then discarded. Upstream's
   threat model files this as D2, "Integrator responsibility — push limits into the query
   where possible" ([threat model](https://github.com/awslabs/tolap/blob/main/docs/security/threat-model.md)).
2. **Hand-written filters.** Translate the policy into `Q` objects yourself, per tool, per
   model. Drift between your translation and the post pass is a silent correctness bug; drift
   in the wrong direction is a disclosure until the post pass catches it.
3. **`str(qs.query)` into the upstream rewriter.** `str(query)` is not executable SQL (unquoted
   parameters, backend-specific rendering), and the rewriter declines joins, subqueries, CTEs
   and set operations. Story 1.x of this project measures exactly how often that path fails.

### Worked example

A clinic runs Django. `Patient` has `id, full_name, email, ssn, date_of_birth, region, status`.
An analyst agent gets a `patients_search` tool. The analyst's effective TOLAP policy:

```json
{
  "permissions": { "canQuery": true, "readOnly": true },
  "objectRules": {
    "allowedObjects": ["patients"],
    "fieldRules": {
      "hiddenFields": ["patients.ssn", "patients.date_of_birth"],
      "maskedFields": [
        { "field": "patients.email", "maskType": "hash", "parameters": { "algorithm": "sha256" } },
        { "field": "patients.full_name", "maskType": "partial", "parameters": { "showFirst": 1 } }
      ]
    },
    "rowFilters": [
      { "field": "region", "operator": "in", "values": ["us-east", "us-west"] },
      { "field": "status", "operator": "notEquals", "value": "deleted" }
    ]
  },
  "limits": { "maxResults": 500 }
}
```

The tool body is `Patient.objects.filter(full_name__icontains=q)`.

**Without this project** (post-only): the SQL is `SELECT id, full_name, email, ssn,
date_of_birth, region, status FROM patients WHERE full_name ILIKE '%q%'`. On a 1M-row table
with a common name fragment, hundreds of thousands of rows including SSNs are fetched, then the
post pass keeps 500 and strips the SSN column. Correct output, terrible resource profile, and
the SSNs were in process memory.

**With this project:**

```sql
SELECT id, full_name, email, region, status
FROM patients
WHERE full_name ILIKE '%q%'
  AND region IN ('us-east', 'us-west')
  AND (status <> 'deleted' OR status IS NULL)
LIMIT 500
```

Then the same TOLAP post pass runs over the 500 rows and hashes `email` and masks
`full_name`. Same output. The database did the work. The SSN column never left the database.

---

## 2. Existing solutions and where they fall short

| Project | What it does | Why it does not solve this |
| --- | --- | --- |
| [TOLAP Python SDK](https://github.com/awslabs/tolap) (`tolap-core` 1.0.0) | Policy schema, merge, signing, post-execution pipeline, raw-SQL rewriter | No ORM integration; rewriter is string-based and declines joins, subqueries, CTEs; no Django store, no admin |
| [TOLAP policy server + console](https://github.com/awslabs/tolap/blob/main/docs/policy-server.md) | Reference central store (Node + PostgreSQL + Cognito + CDK) | Infrastructure to deploy; not a Django app; most Django shops already have an admin |
| [Oso open-source library](https://github.com/osohq/oso) (`django-oso`) | Polar policies compiled to Django `Q` filters | Deprecated by Oso (README, 2023); `django-oso` last release 0.27.0, 2023-04-03; its own policy language, not TOLAP's schema; no masking |
| [Cerbos query-plan adapters](https://github.com/cerbos/query-plan-adapters) | Cerbos PDP query plan to ORM filter (Prisma, Drizzle, SQLAlchemy, Ent, pgx …) | Requires a Cerbos PDP; no Django adapter; row filtering only, no column hiding or masking; not TOLAP |
| [`django-rls`](https://pypi.org/project/django-rls/) | PostgreSQL row-level security from Django | Postgres-only, session-variable based; rows only; no masking, no limits, no signed cross-process policy; not portable to SQLite/MySQL tests |
| [`django-guardian`](https://pypi.org/project/django-guardian/), [`rules`](https://pypi.org/project/rules/) | Per-object / predicate permissions | Yes/no on objects the app already fetched; no filtering, hiding, masking or limits of tool results |
| Data-platform governance (Dremio, Snowflake MCP gateway, Strac) | Row/column policies at the warehouse or a proxy | Not for an application database behind an ORM; vendor-hosted |

Nothing found translates a TOLAP effective policy into ORM constructs, and nothing found
stores TOLAP policies in Django. Both gaps are the point of this project.

---

## 3. How the project works

### 3.1 Components

```
┌──────────────────────────── your Django process ────────────────────────────┐
│                                                                              │
│  Django admin ──▶ django_tolap.models (PolicyDefinition, PolicyAssignment)   │
│                         │  DjangoPolicyStore implements tolap_store.PolicyStore
│                         ▼                                                    │
│  resolve(user, tenant, source) ──▶ EffectivePolicy ──▶ sign_context (HMAC)   │
│                                                          │                   │
│  @tolap_tool / enforce(qs, context)                      ▼                   │
│     1. validate_context, validate_expiry        (tolap_core)                 │
│     2. validate_access(model → object name)     (tolap_core)                 │
│     3. refuse if QuerySet references hidden/non-allowed fields   (ours)      │
│     4. pushdown: Q filters, .values(visible), [:max_results]      (ours)      │
│     5. execute                                                   (Django)    │
│     6. apply_result_pipeline(rows, policy, hash_salt)   (tolap_core, always) │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

Packages (uv workspace monorepo, both Apache-2.0):

- **`django-tolap`** (`django_tolap`): QuerySet enforcement, Django-model policy store with
  admin, DRF mixin, tool helper.
- **`sqlalchemy-tolap`** (`sqlalchemy_tolap`): the same pushdown for `Select`, sharing the
  translation rules and the differential test harness. Built after the Django package.

Dependencies: `tolap-core` (zero-dependency), `tolap-store` (for the `PolicyStore` protocol),
Django. `tolap-mcp` and DRF are optional extras. No infrastructure for the core use case:
policies live in your existing database, edited in your existing admin.

### 3.2 Data flow for one tool call

1. **Identity.** The tool has an authenticated `user_id` and `tenant_id`. How it got them is
   the integrator's concern (TOLAP trust boundary TB1). The helper takes them as arguments.
2. **Resolve.** `DjangoPolicyStore.resolve_policy(user_id, tenant_id, source_connection_id)`
   loads active assignments (direct, by group, by role via an `IdentityResolver` that defaults
   to Django groups) and calls upstream `tolap_core.resolve`, which merges most-restrictive-wins.
   We never reimplement the merge.
3. **Sign.** `build_security_context` + `sign_context` with the deployment's signing key.
   Optional when resolution and enforcement are in the same process, required across a
   boundary. The helper does it either way so the enforcement entry point only ever sees a
   signed context.
4. **Pre-checks (fail closed).** Signature and expiry via upstream `validate_context` and
   `validate_expiry`. `can_query`. Object access via upstream `validate_access` with the
   model's TOLAP object name (default `db_table`, overridable). Then our check: every field
   the QuerySet *references* in its `WHERE`, `ORDER BY`, `GROUP BY`, annotations and explicit
   projection is run through upstream `validate_field_access`. A hidden or non-allowed
   reference **refuses the query**, exactly as upstream's connector spec §5 requires. It does
   not silently narrow.
5. **Pushdown (optimization).** Row filters compile to a `Q` per filter, ANDed. The result
   limit becomes a slice. The projection becomes `.values(*visible_fields)`. Filters we cannot
   translate faithfully for the *current database vendor* are left to the post pass and
   reported, never approximated.
6. **Execute.** Django runs the query.
7. **Post pass (security boundary).** `tolap_core.apply_result_pipeline(rows, policy, hash_salt)`
   over the returned dicts. Always. This is the same function upstream's own wrappers call.

### 3.3 Translation rules (Django)

Mirrors `tolap_core.sql_rewriter` semantics, expressed as ORM lookups instead of SQL text,
and decided **per database vendor** (`connection.vendor`) rather than globally.

| TOLAP operator | Django lookup | Notes |
| --- | --- | --- |
| `equals` | `field=value` | type checked against the model field before pushing |
| `notEquals` | `~Q(field=value)` plus explicit null handling | see §3.4 |
| `in` / `notIn` | `field__in=values` / negated with null handling | empty `values` → deny-all `Q(pk__in=[])` |
| `greaterThan` … `lessThanOrEqual` | `__gt`, `__gte`, `__lt`, `__lte` | non-comparable value → not pushed |
| `between` | `__range=(lo, hi)` | inclusive, matching upstream |
| `isNull` / `isNotNull` | `__isnull=True/False` | |
| `like` / `notLike` | `__like` is not a Django lookup; rendered via custom lookup **only on vendors with case-sensitive `LIKE`** (postgres) | mysql, sqlite, oracle: not pushed |
| `contains` / `startsWith` / `matches` | **never pushed** | upstream never pushes these; `contains` is case-insensitive on SQLite in Django too |

Rows are returned as dicts via `.values()`. This is deliberate: TOLAP's post pass accepts only
records (dicts) or lists of records and **denies** any other shape, including model instances
(spec §5). It also closes a leak: a model instance with `.defer("ssn")` would lazily load the
SSN on attribute access; a dict cannot.

### 3.4 Null handling, decided empirically

Upstream requires a pushed-down negative filter to keep rows whose value is `NULL`
(`(col <> 'x' OR col IS NULL)`) so both paths select the same rows. Django's `exclude()` and
`~Q` already emit their own null-aware SQL for nullable fields. Story 1.x tests what Django
emits per vendor before we add anything; the differential tests are the arbiter. We do not
double-handle NULLs by assumption.

### 3.5 Differential correctness

The property that makes pushdown safe to offer: for every policy and every dataset,

```
post_pass(execute(pushdown(qs, policy)))  ==  post_pass(execute(qs))
```

Tested three ways:

1. **Upstream fixtures.** `fixtures/enforcement/apply-row-filters-all-operators.json` (16
   operators, absent-vs-null cases) and `fixtures/integration-scenarios/postgres-*.json`,
   loaded verbatim from the pinned upstream tag and run through both paths.
2. **Hypothesis.** Generated policies (operators, values, nullable fields, hidden/allowed
   sets, limits) against generated rows, on SQLite and PostgreSQL in CI.
3. **Corpus of realistic QuerySets** (joins, annotations, subqueries, combined `Q`,
   `values`/`only`). Each is run through both our path and upstream's string rewriter on
   `str(qs.query)`, recording where the rewriter declines or emits wrong SQL. Published in the
   README and the upstream issue.

Any translation that fails a differential test is removed, not patched with a looser filter.

### 3.6 Policy store and admin

`django_tolap.models.PolicyDefinition` and `PolicyAssignment` mirror upstream's JSON schema:
the definition body is stored as validated JSON (so the whole schema is supported without a
column per rule), with indexed columns for `name`, `active`, `assignee`, `scope`, `expires_at`,
`revoked_at`. `DjangoPolicyStore` implements `tolap_store.PolicyStore` and delegates
resolution to upstream `resolve`. Admin registration gives list/filter/search, a JSON editor
with schema validation on save, and a read-only "resolve preview" action. Audit events use
upstream's `PolicyAuditEvent` shape and land in a `PolicyAuditLog` table.

### 3.7 Design decisions and rejected alternatives

| Decision | Alternative rejected | Why |
| --- | --- | --- |
| Reuse `tolap_core` for merge, signing, post pass, field matching | Reimplement in Django terms | Any divergence is a security defect; upstream has cross-language fixtures for these |
| Pushdown as `Q` + `.values()` + slice on the caller's QuerySet | Rewrite `str(qs.query)` with upstream's rewriter | `str(query)` is not executable SQL; rewriter declines ORM shapes; we keep the ORM as the SQL owner |
| Refuse queries naming hidden fields | Silently drop the field | Upstream connector spec §5: a hidden column in `WHERE`/`ORDER BY` still influences which rows return |
| Return dicts, not model instances | Return instances with `defer()` | Post pass denies non-record shapes; deferred loading is a leak path |
| Per-vendor translation decisions | One portable rule set | `LIKE` and `contains` case-sensitivity differ by backend; upstream declines `like` on MySQL for the same reason |
| Store the definition body as JSON with a few indexed columns | Fully normalized tables | Whole upstream schema supported on day one; admin edits stay close to the fixture format users already read |
| Depend on PyPI `tolap-core` 1.0.0, CI also against upstream `main` | Require source build of 1.1.0 | Five-minute install; catch drift early |
| Django first, SQLAlchemy second | Both at once | Time-to-first-value; the harness is shared, the second adapter is cheaper |

### 3.8 Trust boundaries and threat model

Inherits upstream's STRIDE model. What this project adds or changes:

- **TB3 (store → DB) becomes the Django database.** Policies are rows in the app's own
  database. Anyone with admin write access to `PolicyDefinition` authors policy. That is the
  intended authoring path; protect it with Django's permission system and, in production, an
  audit trail (we log every change). Signing keys never live in the database.
- **TB4 (signed context) is often intra-process.** When resolve and enforce are the same
  process, the signature adds tamper evidence against bugs, not against a network attacker.
  The helper still signs and verifies so the same code works when the context crosses a
  boundary (e.g. issued by a central policy server, verified in the tool).
- **TB5 (tool → data source) is the ORM.** Pushdown narrows what the database produces. It is
  not the boundary; the post pass is. An integrator who calls our pushdown and skips the post
  pass is unprotected. `enforce()` is the documented entry point and always runs the post
  pass. The lower-level `prepare_queryset()` exists for inspection and benchmarks, carries the
  same warning upstream puts on `prepare_sql_query`, and is not shown in the quickstart.
- **New: schema drift.** A policy can reference a field or object the Django model does not
  have. Behavior is a halt decision (see §6); the default is fail closed.
- **New: lookups that widen.** A caller's QuerySet can contain `.extra()`, raw SQL
  annotations, or `RawSQL` expressions our field extraction cannot see. The pre-check
  refuses QuerySets containing constructs it cannot inspect, and the post pass still runs
  on whatever comes back, so the worst case is fetching too much, never returning too much.
- **Unchanged from upstream:** masking has no SQL form and always runs post-pass; an unknown
  operator, mask type or dialect fails closed; `[]` allow-lists deny everything; `null`
  allow-lists mean unrestricted; empty policies are permissive by upstream design (E3), so
  the store ships a deny-by-default baseline example.

---

## 4. How developers will use it

### 4.1 Install

```bash
pip install django-tolap            # pulls tolap-core, tolap-store
pip install "django-tolap[drf]"     # + DRF mixin
pip install sqlalchemy-tolap        # SQLAlchemy adapter (later)
```

### 4.2 Five-minute quickstart (Django)

```python
# settings.py
INSTALLED_APPS += ["django_tolap"]
TOLAP = {
    "SIGNING_KEY": env("TOLAP_SIGNING_KEY"),   # any secret; rotate like SECRET_KEY
    "HASH_SALT": env("TOLAP_HASH_SALT", default=None),
}
```

```bash
python manage.py migrate django_tolap
python manage.py createsuperuser   # then add a policy in /admin/django_tolap/
```

Or seed one from the shell using the upstream example policy:

```python
from django_tolap.store import DjangoPolicyStore
store = DjangoPolicyStore()
store.save_definition_json({
    "version": "1.0", "name": "analyst",
    "permissions": {"canQuery": True, "readOnly": True},
    "objectRules": {
        "allowedObjects": ["patients"],
        "fieldRules": {"hiddenFields": ["ssn"],
                       "maskedFields": [{"field": "email", "maskType": "hash"}]},
        "rowFilters": [{"field": "region", "operator": "in", "values": ["us-east"]}],
    },
    "limits": {"maxResults": 500},
})
store.assign("analyst", user_id="alice", tenant_id="clinic", granted_by="admin", reason="demo")
```

Then the tool:

```python
from django_tolap import tolap_tool

@tolap_tool(source="db:clinic:patients")
def patients_search(q: str, *, tolap) -> list[dict]:
    return tolap.enforce(Patient.objects.filter(full_name__icontains=q))
```

`tolap` is a per-call context object the decorator injects after resolving, signing and
verifying. `enforce` runs pre-checks, pushdown, execution and the post pass, and returns
dicts the agent may see. Rows the policy excludes never leave the database.

### 4.3 Integration examples

**MCP server (upstream `tolap-mcp` alongside ours).** Resolve and sign with our store, hand
the context to upstream's `SecureMcpToolWrapper` for the tool-level pre/post checks, and use
`enforce()` inside the tool body for the QuerySet. The two do not overlap: upstream governs
the tool call, we govern the query.

**DRF endpoint used as an agent tool.**

```python
class PatientViewSet(TolapViewSetMixin, ReadOnlyModelViewSet):
    queryset = Patient.objects.all()
    serializer_class = PatientSerializer
    tolap_source = "db:clinic:patients"
```

The mixin resolves the policy for `request.user`, enforces on `get_queryset()`, and applies
masking to serializer output. Hidden fields are removed from the response schema.

**Cross-process.** A central resolver (upstream's policy server or your own) issues a signed
context; the Django tool receives it in a header and calls `enforce(qs, context=ctx)`. No
store needed in the tool process.

**SQLAlchemy.**

```python
from sqlalchemy_tolap import enforce
rows = enforce(select(Patient).where(Patient.full_name.ilike(f"%{q}%")), context, session)
```

### 4.4 Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `TOLAP["SIGNING_KEY"]` | required | HMAC key for contexts |
| `TOLAP["HASH_SALT"]` | `None` | Keyed `hash` masking; treat as a secret |
| `TOLAP["IDENTITY_RESOLVER"]` | Django groups → TOLAP groups; no roles | Dotted path to an `IdentityResolver` |
| `TOLAP["OBJECT_NAME"]` | `db_table` | How a model maps to a TOLAP object name |
| `TOLAP["ON_SCHEMA_MISMATCH"]` | `"deny"` | Policy references an unknown field/model (halt decision pending) |
| `TOLAP["CONTEXT_TTL"]` | 1 hour | Signed context lifetime |

---

## 5. Non-goals

- **Not a replacement for TOLAP's framework integrations.** Use `tolap-mcp`, the LangChain
  example, etc. for the tool boundary; we sit under them at the data layer.
- **Not a policy server.** No HTTP resolve endpoint, no console, no CDK. The Django admin is
  the authoring surface; upstream's server remains the option for a central, multi-service
  deployment.
- **No rewrite-only mode.** Same as upstream: the post pass cannot be skipped through our API.
- **No raw-SQL or cursor wrappers in v0.1.** Backlogged: thin wrappers around upstream's
  string rewriter for `Manager.raw()` and `connection.cursor()`.
- **No purpose binding, delegation chains or judge in v0.1.** They are in upstream 1.1.0, which
  is not on PyPI yet. Designed for, added when published.
- **No write-path enforcement in v0.1.** `readOnly` is honored by refusing non-read tools;
  `canInsert`/`canUpdate`/`canDelete` validation of ORM writes is later.
- **No attempt to secure the agent runtime, prompt injection, or the model itself.**

---

## 6. Open items carried to the PRD

Halt decisions still owed by the owner, in the order they block work:

1. Supported versions. Data as of today: Python 3.10 reaches end-of-life 2026-10; Django 5.2
   LTS (extended support to 2028-04), 6.0 (to 2027-04), 6.1 (current, to 2027-12), both 6.x
   require Python ≥ 3.12; SQLAlchemy 2.1.0 released 2026-09-24 (Python ≥ 3.11), 2.0 still
   current; DRF 3.18 supports Django 5.2/6.0/6.1; `tolap-core` requires Python ≥ 3.10.
2. Schema mismatch behavior (policy names a field or object the model lacks).
3. Whether the Django-model store ships in v0.1 or v0.2.

---

## 7. Success signals

**Adoption**
- A developer can go from `pip install` to an enforced QuerySet in under five minutes using
  only the README (measured with a fresh-project script in CI).
- Linked from, or hosted under, `awslabs/tolap` (the upstream issue in `docs/upstream-issue.md`).
- External issues and PRs within the first month; at least one non-author integration.

**Quality**
- Differential tests green on SQLite and PostgreSQL for every upstream fixture and for
  Hypothesis runs, on every commit.
- Benchmark at ~1M rows shows rows fetched, peak memory and latency reduced by the ratio the
  policy's selectivity predicts, with the emitted SQL shown in the README.
- Zero known cases where pushdown returns a row or field the post pass alone would not.
- CI against upstream `main` catches API drift before users do.
