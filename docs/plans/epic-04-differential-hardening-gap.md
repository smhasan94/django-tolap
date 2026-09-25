# Plan: E4 — Differential hardening and gap measurement

**Source:** `docs/03-epics.md` E4; FR-8 (mysql), FR-13, FR-14, FR-20. **Complexity:** Medium.
**Depends on:** E1-S10.

## Requirements restatement

Extend the differential proof to PostgreSQL under Hypothesis and to joined-field filters;
measure where upstream's string rewriter fails on ORM SQL; add an upstream-`main` CI leg;
implement MySQL rules without claiming test coverage.

## Files

```
tests/harness/strategies.py       (+ related-field policies)
tests/gap/corpus.py               ~20 QuerySets over testapp
tests/gap/report.py               runs both paths, renders Markdown
docs/gap-report.md                generated
.github/workflows/ci.yml          (+ upstream-main job, gap-report staleness check)
django_tolap/pushdown.py          (+ mysql vendor row)
```

## Tasks

1. **E4-S1.** Add `related.field` filters to strategies (policy field `"encounters.kind"`
   qualified with the joined object); assert differential; run `HYPOTHESIS_PROFILE=ci` on the
   PostgreSQL job.
2. **E4-S2 corpus.** For each QuerySet: `sql = str(qs.query)`; `prep = prepare_sql_query(sql,
   policy, dialect=SqlDialect.postgres)`; try executing `prep.query` on PostgreSQL via cursor
   (expect failures from unquoted params); record `allowed`, `rewritten`, `unpushable`,
   `executes`, and our `Preparation` summary. Never modify the upstream result.
3. **E4-S3 report.** `python -m tests.gap.report > docs/gap-report.md`; CI diff check.
4. **E4-S4 CI leg.** `pip install "tolap-core @ git+https://github.com/awslabs/tolap#subdirectory=sdk/python/tolap-core"` (+store); `continue-on-error`.
5. **E4-S5 mysql.** Vendor row; unit tests assert `Q`/`None` only; README marks untested.

## Validation

PostgreSQL CI job with `HYPOTHESIS_PROFILE=ci`; `docs/gap-report.md` regenerated and
committed; upstream-main job reports.

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| `str(qs.query)` unfairly penalizes upstream (it never claimed ORM support) | — | Report states this explicitly; the point is the gap, not a flaw |
| Executing rewritten SQL on Postgres needs a schema matching `str(query)` table names | Low | Use the test database itself |
| Upstream-main leg red for long periods | Medium | Allowed to fail; summary annotation names the drift |
