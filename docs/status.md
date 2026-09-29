# Status (saved 2026-09-29)

**Where we are.** `django-tolap` 0.2.1 and `sqlalchemy-tolap` 0.2.1 on PyPI (2026-09-26,
tags `django-tolap-v0.2.1` and `sqlalchemy-tolap-v0.2.1`; release workflow green both times
after the `pypi` environment approval). Nothing unreleased on `main`. Repo public, private
vulnerability reporting on, trusted publishing configured. Upstream issue
https://github.com/awslabs/tolap/issues/31 answered by a maintainer on 2026-09-29 (see
"Upstream 1.2.0" below); a reply is drafted at the end of `docs/upstream-issue.md` and
waits for the owner to post. CI green on every leg (SQLite matrix, PostgreSQL, MySQL 8.4,
quickstart, upstream-main) with a 90% line-and-branch coverage floor; all legs sit at 96%.

**Upstream 1.2.0 (2026-09-29, tag only; PyPI still 1.0.0).** The maintainer's reply on
#31 and the release notes, verified against the tag:
- Both adapters are listed in upstream's README under "Community integrations" (#35, #41).
  Hosting under `awslabs` is undecided; they will follow up on #31.
- `EnforcedResult.for_context(data, context)` (#33, #40): a tool returns it and
  `execute_with_enforcement` skips the result pipeline, which closes the double-hash
  interop. Honoured only under signature enforcement when the marker names the context's
  exact signature; otherwise unwrapped and fully enforced. An honoured marker skips masking
  and the size ceiling; row filters, hidden-field removal, allowed-field projection,
  `maxResults` and tag rules still run. It is a claim, not proof: return one only after
  `apply_result_pipeline` ran (pushdown alone does not qualify). Fixture
  `fixtures/enforcement/already-enforced-results.json`.
- Row-filter lookup fixed (#32, #37): a filter never reads a key qualified with another
  object; a bare filter matching several qualified keys counts as absent and drops the row.
  Same lookup for the update/delete target-row check. Fixture `row-filter-qualified-lookup.json`.
- `allowedFields` no longer crosses objects (#36, #38): `patients.name` no longer admits
  `encounters.name`. Fixture `allowed-fields-qualified.json`.
- SQL pre-check (#39) resolves every table and column through aliases and refuses what it
  cannot resolve (CTEs, set operations, subqueries outside FROM, LATERAL, non-SELECT);
  exported as `validate_query_references`. Affects `enforce_sql` / `enforce_raw`. Fixture
  `sql-multi-table.json`.
- New `objectRules.toolRules` and `filter_tools`; schema stays v1.0, all optional.
- Release channel (#34) still open.
- Behaviour changes checked on the upstream-main CI leg against main `6a4cc0d` (the tag
  plus dependency bumps, README and examples): 1040 tests pass. The only difference from
  1.0.0 is raw SQL: an `IN (SELECT ...)` subquery and a `UNION` are now refused by
  upstream's pre-check; `tests/test_raw.py` branches on the installed version. The
  qualified-lookup and `allowedFields` changes needed nothing.
- Found while doing that: the upstream-main leg had never tested upstream. `uv run`
  re-synced the venv from `uv.lock` after the git install and quietly restored 1.0.0.
  Fixed with `UV_NO_SYNC` on the job plus an assertion that the version moved
  (commit `41bf3c8`). Every earlier "upstream-main green" was really 1.0.0.

**Releasing the next version (owner).** Bump `version` in the package's `pyproject.toml`,
date the changelog heading, `uv lock`, commit, then
`git tag -a <package>-vX.Y.Z -m "<package> X.Y.Z" && git push origin <package>-vX.Y.Z`
and approve the `pypi` environment on the run (`CONTRIBUTING.md` "Releasing").

**In 0.2.1 (2026-09-26).**
- Both adapters: a row filter on a joined object whose column is not projected now adds
  that column for the post pass (through the projected column's relation or FROM element)
  instead of refusing; refusal remains for absent objects, WHERE-only joins and unknown
  columns.
- Gap report: a "Documented limits" section lists every shape each adapter refuses by
  design with the reason it gives (`tests/gap/corpus.py` `REFUSED`, `sa_corpus.py`
  `SA_REFUSED`); `tests/test_gap_report.py` asserts each is refused, so the list cannot
  drift from the code.
- Example app: the clinic policies over a DRF endpoint (`patients/api.py`) with a per-caller
  schema, login users alice/bob from the seed, `manage.py test patients` smoke test run by
  `make demo` (CI quickstart leg).

**In 0.2.0 (see `CHANGELOG.md`).**
- sqlalchemy-tolap: joined and labelled column projections (`select(Patient.id,
  Encounter.occurred_at)`, `Encounter.region.label("er")`), keyed to their own table for the
  post pass. Ships as `sqlalchemy-tolap` 0.2.0 by the same bump-and-tag flow
  (`sqlalchemy-tolap-v0.2.0`).
- drf-spectacular: `TolapAutoSchema`, set by the viewset mixin when installed. Per-caller
  schemas omit hidden fields and refused writes, annotate masks; public schema generation no
  longer crashes on the serializer mixin.
- `enforce_sql` / `enforce_raw`: raw SQL paths with our vendor rules over upstream's rewriter.
- `manage.py tolap_resolve`: effective policy, assignments, or a signed context from the shell.
- `enforce_save` / `enforce_delete` / `enforce_update` / `enforce_queryset_delete` and the
  `ToolContext` shortcuts: ORM write paths through upstream `validate_write`.
- `values("related__field")` projections accepted; joined columns keyed as `object.field`
  for the post pass. Gap report: 48 of 48 corpus pairs prepare.
- `__version__` from package metadata.

**Adoption signals.** `make signals` prints PyPI downloads, repo stats, the upstream issue's
state and whether tolap-core has moved past 1.0.0. Baseline 2026-09-26, day one of 0.2.0:
django-tolap 162 and sqlalchemy-tolap 91 downloads (mostly CI and mirrors),
0 stars, 0 issues; upstream tolap 8 stars, our #31 its only open issue, no maintainer reply.
Check weekly. The next piece of work should come from a user report, a maintainer reply, or
tolap-core 1.1, not from guessing.

**Workflow.** Direct commits on `main` (owner's call after PRs #1 to #5). Branches and PRs
return when the owner asks.

**How to resume.** `uv sync && make check` (SQLite). PostgreSQL:
`DATABASE_URL=postgres://localhost/postgres HYPOTHESIS_PROFILE=ci make test` (Homebrew
PostgreSQL 17, binaries at `/opt/homebrew/opt/postgresql@17/bin`). MySQL: start Docker
Desktop, `docker run -d --name tolap-mysql -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=tolap
-p 3307:3306 mysql:8.4` (or `docker start tolap-mysql` if it still exists), then
`DATABASE_URL=mysql://root:root@127.0.0.1:3307/tolap HYPOTHESIS_PROFILE=ci make test`.
`mysqlclient` needs the Command Line Tools toolchain on this Mac; env in `CONTRIBUTING.md`.
Regenerate the gap report with `DATABASE_URL=<postgres> make gap-report`.

**Backlog (in rough priority order).**
- Owner: post the drafted reply on awslabs/tolap#31 (`docs/upstream-issue.md`, "Reply
  draft"). The CI result it cites is in.
- When `tolap-core` 1.2 reaches PyPI (#34): return `EnforcedResult.for_context` from
  `@tolap_tool` and the DRF mixins when the caller runs `execute_with_enforcement`, retire
  the `pre_execute` composition note in the READMEs and `tests/test_tool_mcp_interop.py`,
  raise the pin, refresh `tests/fixtures/upstream` to the 1.2.0 commit and run the four new
  enforcement fixtures through both adapters (E7-S13, E7-S14).
- Purpose binding, delegation chains, judge: same trigger. Four merge scenario fixtures are
  skipped until then; the upstream-`main` CI leg reports drift.

**Things to remember.**
- Never run scripts against the configured `DATABASE_URL` directly; use Django's test
  database setup (`tests/gap/report.py`) or a throwaway `createdb`.
- The Bash tool wrapper ignores `set -e`; chain with `&&`.
- Upstream fixtures are pinned to commit `e5c92107…` (`tests/fixtures/upstream/SOURCE`).
- Upstream's field matcher lets a bare or table-wildcard rule (`encounters.*`) match any
  object's leaf key, by design; over-masks, never under-masks.
- Upstream's row-filter lookup (`_row_field_value`) in PyPI 1.0.0 hits the exact key first,
  then the first key in row order whose bare form matches (fixed upstream in 1.2.0, #37;
  the notes below still hold and are the pattern the fix assumes). With joined columns in the row (`patients.email`
  keys) a qualified or differently-cased root filter could read the wrong object's column.
  Both adapters now present every model field to the post pass under a unique
  `object.field` key (`Preparation.key_map`), refuse a table that appears twice in FROM
  (SQLAlchemy) or an object reached twice (Django) and a column projected twice, resolve
  every filter to exactly one column of the result (root or
  joined, case-insensitively) and copy it under the filter's own spelling
  (`Preparation.filter_keys`); a filter whose column is not in the result is added when
  the object is projected, refused otherwise.
  Keep the property tests' encounter regions different from the patient's; equal regions
  hide this class of bug. The differential harnesses treat "denied in both modes with the
  same reason" as agreement.
- `CLAUDE.md` is untracked on purpose; it is still the project brief.
