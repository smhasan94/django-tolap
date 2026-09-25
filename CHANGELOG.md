# Changelog

## Unreleased

### django-tolap

- drf-spectacular: `TolapViewSetMixin` generates its schema with
  `django_tolap.spectacular.TolapAutoSchema` when drf-spectacular is installed. Operations
  on a TOLAP view carry `x-tolap-source` and a description note. A schema generated for an
  authenticated caller (whatever `SERVE_PUBLIC` says) omits hidden fields, annotates masked
  fields with `x-tolap-mask`, omits write methods the caller's policy refuses, and omits
  every operation on an object the policy cannot query. Fixes schema generation with no
  caller, which `TolapSerializerMixin` broke with `identity not established`: no caller now
  means no policy and an unchanged serializer (`TolapViewSetMixin.tolap_policy_or_none()`).
  `TolapSerializerMixin` now hides by the column a field reads (`source`) and by the owning
  serializer's `Meta.model`.
- `values("related__field")` projections are accepted. The joined column is pre-checked
  against its own object's hidden and allowed fields, presented to the post pass as
  `object.field` so that object's masking rules apply, and returned under the caller's key.
  Gap report: 48 of 48 corpus pairs now prepare.
- `enforce_save`, `enforce_delete`, `enforce_update` and `enforce_queryset_delete`: the ORM
  write paths under a policy, through upstream `validate_write` with the target row read
  under the policy first. Fail closed: one unwritable field or one invisible target row
  refuses the whole write; bulk writes are all-or-nothing. A save without `update_fields` is
  a full replace. `ToolContext` gains `save`, `delete`, `update`, `delete_queryset`.
- `manage.py tolap_resolve USER [--tenant T] [--source S]` prints the effective policy a user
  resolves to as JSON; `--assignments` adds the assignments considered, `--context [--ttl N]`
  prints a signed serialized context instead, `--audit` records the resolution (off by
  default, a preview is not a grant).
- `enforce_sql(sql, params, context, model=...)` and `enforce_raw(Model.objects.raw(...),
  context)`: the raw SQL paths. Upstream's `prepare_sql_query` rewrites the text; the wrapper
  hands it only the row filters the QuerySet path's vendor rules accept (spelled as database
  columns), pushes the limit only when every filter was pushed, leaves joins, subqueries and
  set operations unrewritten, preserves `%s`/`%(name)s` placeholders and escapes pushed `%`
  literals. Refuses non-`SELECT` statements and statements reading a different table than
  `model`. Same differential proof, on every CI vendor.

## 0.1.1 — 2026-09-25 (django-tolap only)

### django-tolap

- **Schema:** `PolicyAssignment.tenant_id` and `source_connection_id` are `max_length=128`
  (were 255). The unique constraint over the assignment scope exceeded MySQL's 3072-byte key
  limit under `utf8mb4`, so 0.1.0 could not migrate on MySQL 8 or MariaDB. Migration `0002`
  narrows existing PostgreSQL and SQLite installs; `0001` now creates the columns at 128 so
  fresh installs work everywhere. Run `python manage.py migrate django_tolap`.
- MySQL 8.4 is tested in CI: the full suite, the differential fixtures and the Hypothesis
  property pass with the `mysql` vendor rules (string operators left to the post pass).

### sqlalchemy-tolap

- No release; 0.1.0 is unchanged. MySQL 8.4 (`mysql+mysqldb`) is now tested in CI with the
  same differential proof.

## 0.1.0 — 2026-09-25

First release of `django-tolap` and `sqlalchemy-tolap`. Depends on the published
`tolap-core` and `tolap-store` 1.0.0.

### django-tolap

- `enforce(queryset, context)`: signed-context verification, pre-execution checks (object
  access for every table touched, referenced columns against hidden/allowed sets, refusal
  rather than narrowing), ORM-native pushdown of row filters, projection and result limit,
  then upstream's mandatory post-execution pipeline. `EnforcementMode` mirrors upstream's
  `SqlEnforcementMode`.
- `DjangoPolicyStore`: upstream's `PolicyStore` protocol on Django models, with migrations,
  admin registration (validation through upstream's deserializer, schema-drift warnings,
  resolve preview), and an audit log.
- `issue_context` / `accept_context`, the `@tolap_tool` decorator, `tolap_context`, and
  Django REST Framework viewset and serializer mixins with write gating.
- Differential correctness against upstream's shared fixtures and a Hypothesis property on
  SQLite and PostgreSQL.

### sqlalchemy-tolap

- `enforce(select, context, session, signing_key=...)` with the same checks, pushdown rules
  and post pass for SQLAlchemy 2.x `Select` statements; same differential proof.

### Known limitations

- Purpose binding, delegation chains and the judge (upstream 1.1) are not supported until
  `tolap-core` 1.1 is on PyPI.
- MySQL pushdown rules are implemented but not tested in CI; Oracle and MSSQL fall back to
  the post pass for every filter.
- `hash` masking is applied twice when a tool is wrapped by upstream's
  `execute_with_enforcement`; compose with `pre_execute` instead.
