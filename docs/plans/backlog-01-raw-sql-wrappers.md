# Backlog 01: `enforce_sql` / `enforce_raw` for the raw SQL paths (Django)

**Source:** `docs/status.md` backlog; decision 2026-09-25 item 5; decision 2026-09-25 "raw
strictness" (our vendor rules, model required). **Branch:** `raw-sql-wrappers`.

## Goal

Tools that hand Django a SQL string (`Manager.raw()`, `connection.cursor()`) get the same
guarantees as `enforce()`: signed-context verification, object and field checks, faithful
pushdown, mandatory post pass, dicts out. Upstream's `prepare_sql_query` does the text
rewriting; we decide *what* it may push.

## Design

- `django_tolap.raw.prepare_sql(sql, params, policy, *, model, vendor, mode)` →
  `RawPreparation(allowed, sql, params, denial_reason, rewritten, pushed_filters,
  unpushable_filters, max_results, mode)`.
  1. Refuse anything but a `SELECT` (upstream lets `INSERT` through).
  2. Refuse when upstream's `extract_table_name` is not the model's object name: the
     policy must be applied to the table the statement actually reads.
  3. Upstream's `prepare_sql_query` with `object_name=object_name(model)` runs the object
     and hidden/allowed-field checks. It receives a **reduced policy**: only row filters
     `compile_filter(rf, model, vendor)` accepts (same rules as the QuerySet path), and
     `limits` only when every filter survived. `mode=postOnly`, an unknown vendor, or a
     statement with `JOIN`, a comma `FROM`, a subquery or a set operation gets an empty
     filter list and no limit: checks run, nothing is pushed (upstream injects unqualified
     columns, wrong across tables).
  4. Placeholders: `%s` and `%(name)s` are counted before and after the rewrite; a changed
     count (a pushed literal contained a placeholder-shaped string) falls back to the
     unpushed rewrite. Otherwise every `%` outside a placeholder is doubled when `params` is
     not `None`, so a pushed `LIKE 'J%'` survives Django's parameter interpolation.
- `enforce_sql(sql, params=None, context, *, model, using=None, hash_salt, signing_key,
  mode)`: validate context (signature then expiry), prepare, execute through the
  connection's cursor, rows as dicts keyed by `cursor.description`, `apply_result_pipeline`.
- `enforce_raw(raw_queryset, context, **same)`: `raw_query`, `params`, `db`, `model` from
  the `RawQuerySet`, then `enforce_sql`. Never instantiates models.

## Tests (`tests/test_raw.py`)

- README policy through `enforce_raw` equals `enforce` on the same rows.
- Placeholders: list and dict params; `%` escaping unit-tested on a rewritten string and
  end to end on PostgreSQL where `like` is pushed.
- Denials: non-SELECT, table/model mismatch, object not allowed, hidden field referenced.
- Not rewritten but allowed: joins, subquery, `postOnly`, unknown vendor (monkeypatched).
- Limit pushed only when all filters pushed.
- Hypothesis differential on a raw-statement corpus with the shared `policies()` and
  `patient_rows()` strategies, on every CI vendor.

## Risks

- Upstream's regex field extraction: a `True` from `validate_query` is not a guarantee; the
  post pass remains the boundary, as everywhere.
- A pushed filter on a column the statement does not select yields zero rows on both paths
  (upstream's documented caveat); documented, not worked around.
