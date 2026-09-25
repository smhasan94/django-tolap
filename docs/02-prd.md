# django-tolap: product requirements

*Phase 2 deliverable, 2026-09-25. Depends on `docs/01-overview.md` and the decisions in
`docs/decisions.md`.*

## 1. Goals

- **G1.** A Django developer installs one package and has TOLAP policies authored in Django
  admin and enforced on QuerySets within five minutes of reading the README.
- **G2.** Pushdown makes the database return only what the policy allows, so rows the policy
  excludes never cross the wire, and the result is provably identical to post-pass-only.
- **G3.** Reuse upstream `tolap-core` for every security-relevant computation (merge, signing,
  field matching, post pass). This project adds translation and Django plumbing, not policy
  semantics.
- **G4.** Fail closed everywhere upstream's spec says to, and in every new place this project
  introduces (schema drift, uninspectable QuerySets).
- **G5.** Ship a second adapter for SQLAlchemy `Select` on the same harness.

## 2. Non-goals

Listed in `docs/01-overview.md` §5. In short: no policy server, no console, no rewrite-only
mode, no raw-SQL wrappers in v0.1, no purpose binding/judge until upstream publishes 1.1, no
ORM write-path validation in v0.1, no agent-runtime security.

## 3. Personas

| Persona | Situation | Needs |
| --- | --- | --- |
| **Tool author** (backend dev) | Exposing a Django model to an agent via MCP/LangChain/DRF | A decorator and one `enforce()` call; clear denial errors; no policy code in the tool |
| **Policy admin** (security/platform) | Owns who may see what | Author and assign policies in Django admin, see what a user resolves to, audit changes |
| **Platform integrator** | Runs a central TOLAP policy server already | Verify externally signed contexts in Django tools without a local store |
| **SQLAlchemy user** | FastAPI or plain SQLAlchemy service | Same pushdown for `Select`; no Django |
| **Upstream maintainer** | awslabs/tolap | Evidence the ORM gap is real; an adapter they can link to |

## 4. Functional requirements

Acceptance criteria (AC) are testable statements. "Upstream" means `tolap-core` 1.0.0
functions unless stated. "Vendor" means `connection.vendor` (`sqlite`, `postgresql`, `mysql`,
`oracle`).

### Install and configuration

**FR-1. Installable app.** `pip install django-tolap`, add `django_tolap` to
`INSTALLED_APPS`, set `TOLAP["SIGNING_KEY"]`, run `migrate`.
- AC1: A fresh `startproject` with those steps passes `manage.py check` and `migrate`.
- AC2: Missing `SIGNING_KEY` raises an `ImproperlyConfigured` at startup, not at first call.
- AC3: Runtime dependencies are exactly `Django`, `tolap-core`, `tolap-store`.

**FR-2. Settings.** `TOLAP` dict with `SIGNING_KEY` (required), `HASH_SALT`,
`IDENTITY_RESOLVER`, `OBJECT_NAME`, `CONTEXT_TTL`, `SOURCE_PREFIX`.
- AC1: Every key has a documented default and is validated on startup via a system check.
- AC2: `OBJECT_NAME` accepts `"db_table"` (default) or a dotted callable `(model) -> str`.

### Policy store and admin

**FR-3. Django-model policy store.** Models `PolicyDefinition`, `PolicyAssignment`,
`PolicyAuditLog`; `DjangoPolicyStore` implementing `tolap_store.PolicyStore`.
- AC1: `DjangoPolicyStore` type-checks against the `PolicyStore` protocol (mypy).
- AC2: `save_definition` rejects a body that upstream `deserialize_policy_definition` rejects,
  with the upstream message.
- AC3: `resolve_policy` delegates to upstream `resolve` with assignments, definitions,
  groups and roles; result is byte-identical (canonical serialization) to
  `InMemoryPolicyStore` for the same inputs, checked against upstream `fixtures/assignments`
  and `fixtures/merge-scenarios`.
- AC4: Inactive, expired and revoked assignments are excluded by the query and still
  re-filtered by upstream `resolve` (defense in depth per upstream E2a).
- AC5: Every create/update/delete/resolve writes a `PolicyAuditLog` row with upstream's
  `PolicyAuditEvent` fields.

**FR-4. Admin registration.** Both models registered; definition body edited as JSON.
- AC1: Save with an invalid body shows the validation error inline; nothing is stored.
- AC2: A "resolve preview" admin action takes user, tenant, source and shows the effective
  policy JSON.
- AC3: List views filter by `active`, `assignee type`, `tenant`, and search by name.
- AC4: Schema-drift warnings (FR-11) appear as non-blocking messages on save.

**FR-5. Identity resolver.** Default maps Django `Group` names to TOLAP groups; roles empty.
- AC1: `TOLAP["IDENTITY_RESOLVER"]` dotted path replaces it; must satisfy
  `tolap_store.IdentityResolver`.
- AC2: A user id that is not a Django user resolves to no groups (not an error).

### Contexts

**FR-6. Context issuance and acceptance.** Build and sign a context from the store, or
accept an externally signed one.
- AC1: `issue_context(user_id, tenant_id, source)` returns a context that upstream
  `validate_context` accepts with the configured key.
- AC2: `enforce(qs, context=...)` accepts a context deserialized with upstream
  `deserialize_context`; a tampered or expired context is refused with upstream's reason.
- AC3: Signature is checked before expiry (upstream ordering).

### Enforcement

**FR-7. Pre-execution checks, fail closed.** Before any SQL runs: signature, expiry,
`can_query`, object access, referenced fields, inspectability.
- AC1: Object name derives from the QuerySet's model via FR-2 `OBJECT_NAME`; upstream
  `validate_access` decides; denial reason is upstream's string.
- AC2: Every field referenced in `WHERE`, `ORDER BY`, `GROUP BY`, annotations, `values()`,
  `only()` is collected (including across joins as `related.field`) and checked with upstream
  `validate_field_access`; any denied field refuses the query with reason
  `query references fields you do not have permission to access`.
- AC3: A QuerySet containing `.extra()`, `RawSQL`, `.raw()`, or an expression whose
  referenced columns cannot be resolved is refused with reason `query cannot be inspected`.
- AC4: `distinct()`, `select_related`, `prefetch_related`, `union`/`intersection`/
  `difference`, `.values()` with expressions: each is either supported with tests or refused.
  None is silently passed through.

**FR-8. Row-filter pushdown.** Each `rowFilters` entry compiles to a `Q` or is reported
unpushable. Vendor-specific decisions.
- AC1: `equals`, `notEquals`, `in`, `notIn`, `greaterThan`, `greaterThanOrEqual`, `lessThan`,
  `lessThanOrEqual`, `between`, `isNull`, `isNotNull` push on all vendors.
- AC2: `like`/`notLike` push only on `postgresql`; never on `sqlite`, `mysql`, `oracle`.
- AC3: `contains`, `startsWith`, `matches` are never pushed.
- AC4: A value that cannot be coerced to the model field's Python type is not pushed.
- AC5: Negative operators keep rows whose column is `NULL`; verified by differential tests
  on every vendor in CI (decision 2026-09-25 item 4: check Django's own null handling first).
- AC6: A filter on a field absent from the model is a schema mismatch (FR-11), denied.
- AC7: `Preparation.unpushable_filters` lists every filter not pushed; `fully_pushed_down`
  is `True` only when the list is empty.

**FR-9. Projection restriction.** Results are dicts from `.values(*visible)`.
- AC1: Visible fields = model concrete fields minus `hiddenFields`, intersected with
  `allowedFields` when not `None`, using upstream `_field_name_matches` semantics via
  `validate_field_access`.
- AC2: `allowedFields: []` yields no visible fields and the query is refused with reason
  `no fields visible`.
- AC3: A caller-supplied `.values()`/`.only()` is intersected, never widened.
- AC4: Fields named by a pushed or unpushed row filter are kept in the projection so the post
  pass can evaluate them; if a field is both hidden and filtered, it is projected for the
  post pass and stripped by it (upstream §4 rule).

**FR-10. Result limit.** `limits.maxResults` applied as a slice.
- AC1: An existing narrower slice is kept; a wider one is narrowed.
- AC2: `maxResults` absent means no slice added.

**FR-11. Schema mismatch.** Policy names a field or object not on the model.
- AC1: Unknown field in `rowFilters`, `hiddenFields`, `allowedFields`, `maskedFields` for
  this model → query denied with reason `policy references unknown field: <name>`.
  Wildcard patterns are exempt (they match nothing rather than fail).
- AC2: Admin save shows a warning listing unknown fields for each model whose object name
  the policy targets, when that model is registered with `django_tolap`.

**FR-12. Post pass, always.** `enforce()` calls upstream `apply_result_pipeline(rows,
policy, hash_salt)` on the executed rows.
- AC1: There is no public function that executes a prepared QuerySet without the post pass.
- AC2: `hash_salt` comes from settings and is passed explicitly.
- AC3: `enforce()` returns `list[dict]`; never model instances.

**FR-13. Differential correctness.** `post(execute(pushdown(qs)))` equals `post(execute(qs))`.
- AC1: Every case in upstream `fixtures/enforcement/apply-row-filters-all-operators.json`
  and `fixtures/integration-scenarios/postgres-row-filters.json`,
  `postgres-field-rules.json`, `postgres-healthcare-analyst.json`,
  `permissions-and-limits.json` passes on SQLite and PostgreSQL.
- AC2: A Hypothesis suite generates policies (all operators, nullable fields, hidden/allowed
  sets, limits) and row sets; both paths compared on SQLite every run and PostgreSQL in CI.
- AC3: Fixtures are downloaded from the pinned upstream tag at test time or vendored under
  `tests/fixtures/upstream/` with the tag recorded; never edited.

**FR-14. Gap measurement.** A corpus of realistic QuerySets compared against upstream's
string rewriter.
- AC1: At least 20 QuerySets: joins, reverse relations, annotations, aggregates, subqueries,
  `Exists`, combined `Q`, `values`/`only`, `order_by` across relations, `distinct`.
- AC2: For each: upstream `prepare_sql_query(str(qs.query), policy, dialect=...)` result
  (allowed/denied/rewritten/unpushable) and whether the rewritten text is executable, next to
  our result.
- AC3: Output is a Markdown table committed to `docs/gap-report.md` and summarized in the
  README and `docs/upstream-issue.md`.

### Tool surface

**FR-15. Tool helper.** `@tolap_tool(source=...)` decorator and `tolap_context(...)`
context manager.
- AC1: The decorated function receives a `ToolContext` with `.policy`, `.context`,
  `.enforce(qs)`, `.deny(reason)`.
- AC2: Identity comes from keyword arguments `user_id`, `tenant_id` or a configured callable;
  missing identity denies.
- AC3: Works with an upstream `SecureMcpToolWrapper` wrapping the same function (example
  test using `tolap-mcp`).
- AC4: Denials raise `TolapDenied(PermissionError)` with the upstream reason string; no row
  data in the message.

**FR-16. DRF integration.** `TolapViewSetMixin` and `TolapSerializerMixin`.
- AC1: `get_queryset()` is enforced; list and retrieve return post-passed dicts.
- AC2: Hidden fields are absent from responses and from the OpenAPI schema for that view.
- AC3: Write methods are refused when the policy is `readOnly` or lacks the write permission.
- AC4: DRF is an optional extra; importing `django_tolap` without DRF works.

### Delivery

**FR-17. Example app and benchmark.** `examples/clinic/` with `Patient` across regions.
- AC1: `make demo` seeds ~1M rows in SQLite or PostgreSQL, runs one agent tool both ways.
- AC2: Prints SQL emitted, rows fetched, peak RSS, wall time for pushdown vs post-only.
- AC3: README headline table generated from this output.

**FR-18. Upstream proposal.** `docs/upstream-issue.md` drafted, not posted.

**FR-19. SQLAlchemy adapter.** `sqlalchemy-tolap` with `enforce(select, context, session)`
and `prepare_select()`.
- AC1: FR-7 to FR-13 equivalents on `Select`, same harness, same fixtures, dialect from
  `bind.dialect.name`.
- AC2: No Django import.

**FR-20. CI.** Matrix per decisions; plus one leg installing upstream `main` from source.
- AC1: Python 3.11–3.14 × Django 5.2/6.0/6.1 (valid combinations), SQLite and PostgreSQL.
- AC2: Upstream-main leg is allowed to fail but reports.
- AC3: `ruff`, `mypy --strict` on package code, `pytest` with coverage ≥ 80 %.

## 5. Non-functional requirements

**Performance.**
- Pushdown preparation adds under 1 ms per call for a policy with ≤ 20 filters on a model
  with ≤ 50 fields (measured, not asserted).
- No additional queries at enforcement time beyond the caller's; resolution is one query
  per table (definitions, assignments) plus group lookup.
- Benchmark at ~1M rows demonstrates rows fetched proportional to policy selectivity.

**Security.**
- Every denial path listed in upstream connector spec §3.3 is preserved verbatim.
- New fail-closed paths: schema mismatch, uninspectable QuerySet, empty visible projection,
  unknown vendor (no pushdown, post pass only).
- Signing key and hash salt only from settings; never stored in models; never logged.
- Denial messages never contain row values.
- Post pass cannot be skipped through any public API.

**Compatibility.**
- Python 3.11–3.14; Django 5.2, 6.0, 6.1; SQLAlchemy 2.0, 2.1; DRF ≥ 3.16 as extra.
- Vendors: SQLite and PostgreSQL tested in CI; MySQL rules implemented per upstream but
  marked "untested" until a CI leg exists; Oracle falls back to post-only.
- `tolap-core>=1.0,<2`, `tolap-store>=1.0,<2`.

**Dependency budget.**
- `django-tolap`: Django, tolap-core, tolap-store. Nothing else.
- `sqlalchemy-tolap`: SQLAlchemy, tolap-core.
- Test/dev: pytest, pytest-django, hypothesis, psycopg, ruff, mypy, django-stubs.

## 6. Public API surface (v0.1)

```python
# django_tolap
enforce(queryset, context, *, hash_salt=None) -> list[dict]
issue_context(user_id, tenant_id, source, *, store=None, ttl=None) -> SecurityContext
tolap_tool(source, *, identity=None) -> decorator
tolap_context(user_id, tenant_id, source) -> context manager yielding ToolContext
class ToolContext: policy, context, enforce(qs), deny(reason)
class TolapDenied(PermissionError)
class TolapSchemaMismatch(TolapDenied)

# django_tolap.pushdown  (optimization layer; carries upstream's "post pass still mandatory" warning)
prepare_queryset(queryset, policy) -> Preparation
class Preparation: allowed, queryset, denial_reason, unpushable_filters, fully_pushed_down,
                   visible_fields

# django_tolap.store
class DjangoPolicyStore(PolicyStore): + save_definition_json(dict), assign(...)
# django_tolap.identity
class DjangoGroupsIdentityResolver(IdentityResolver)
# django_tolap.models
PolicyDefinition, PolicyAssignment, PolicyAuditLog
# django_tolap.drf  (extra)
TolapViewSetMixin, TolapSerializerMixin

# settings
TOLAP = {"SIGNING_KEY", "HASH_SALT", "IDENTITY_RESOLVER", "OBJECT_NAME", "CONTEXT_TTL",
         "SOURCE_PREFIX"}
```

Source connection ids follow upstream's `category:namespace:name`; the default for a model is
`db:<SOURCE_PREFIX or app_label>:<db_table>`.

## 7. Scope

**v0.1 (django-tolap):** FR-1 to FR-18, FR-20 (Django legs).
**v0.2:** FR-19 (sqlalchemy-tolap), FR-20 SQLAlchemy legs, raw()/cursor wrappers over
upstream's rewriter, `tolap_resolve` management command.
**Later / upstream-gated:** purpose binding, delegation chains, judge (upstream 1.1 on PyPI);
ORM write-path validation; MySQL CI leg.

## 8. Open questions (non-blocking)

1. Tenant id for DRF requests: default to a `TOLAP["TENANT_RESOLVER"]` callable with a
   `"default"` fallback. Assumed unless the owner objects.
2. Whether admin should offer a catalog of model fields per object name for autocomplete.
   Deferred; JSON editing with warnings is enough for v0.1.
3. Whether `enforce()` should accept a `Manager` as well as a `QuerySet`. Assumed yes.
