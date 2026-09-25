# Plan: E5 — Example app, benchmark, README, upstream issue

**Source:** `docs/03-epics.md` E5; FR-14, FR-17, FR-18. **Complexity:** Medium.
**Depends on:** E2-S7, E4-S3.

## Files

```
examples/clinic/manage.py, clinic/settings.py, clinic/urls.py
examples/clinic/patients/{models,admin,tools}.py
examples/clinic/patients/management/commands/seed_patients.py
examples/clinic/patients/management/commands/benchmark.py
examples/clinic/README.md
README.md                      rewritten
docs/upstream-issue.md
Makefile                       (+ demo, bench targets)
```

## Tasks

1. **E5-S1.** `Patient(full_name, email, ssn, date_of_birth, region, status, score)` with an
   index on `region`; `seed_patients --rows N` uses `bulk_create` in batches of 10k with a
   fixed RNG seed; `tools.patients_search` via `@tolap_tool`; two policies seeded (analyst
   us-east-only; auditor all regions, everything masked).
2. **E5-S2 benchmark.** `benchmark --rows N --vendor`: for each policy, run `enforce()` with
   pushdown and with an internal `_pushdown=False` flag (module-private, used only here and
   in differential tests), capturing: SQL (`connection.queries` with `DEBUG` on for the
   capture run only), rows fetched (`cursor.rowcount` via a query-logging wrapper), peak RSS
   (`resource.getrusage`), wall time (`perf_counter`, median of 5). Output Markdown table.
3. **E5-S3 README.** Headline: table from E5-S2 on PostgreSQL at 1M rows; quickstart (E2-S7);
   "what upstream already does" section citing `tolap_core.sql_rewriter`; gap-report summary;
   compatibility table; security model summary linking upstream threat model.
4. **E5-S4 upstream issue.** Sections: context, gap (with gap-report numbers), what the
   adapters do, differential proof, ask (link or host), offer. Halt after commit for the
   owner to post.

## Validation

`make demo` on SQLite in CI (100k rows to keep CI fast); PostgreSQL 1M run locally, output
pasted into README with the command shown.

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| 1M-row seeding slow in CI | High | CI uses 100k; README numbers from a documented local run |
| Memory measurement noisy | Medium | Report peak RSS delta over baseline, median of runs |
