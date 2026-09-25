# Status (saved 2026-09-25, end of day)

**Where we are.** v0.1 complete and released; post-v0.1 backlog in progress. Both packages
on PyPI: `django-tolap` 0.1.1 (tag `v0.1.1`), `sqlalchemy-tolap` 0.1.0 (tag `v0.1.0`).
Repo public, private vulnerability reporting on, trusted publishing configured (PyPI
publishers and the `pypi` GitHub environment exist). Upstream issue posted:
https://github.com/awslabs/tolap/issues/31, no maintainer reply yet. CI green on every leg
(SQLite matrix, PostgreSQL, MySQL 8.4, quickstart, upstream-main) with a 90% line-and-branch
coverage floor; all legs sit at 96%.

**Unreleased on `main` (see `CHANGELOG.md` "Unreleased").**
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

Release it as `django-tolap` 0.2.0 when ready: bump `version` in
`packages/django-tolap/pyproject.toml`, date the changelog heading, `uv lock`, commit, then
`git tag -a django-tolap-v0.2.0 -m "django-tolap 0.2.0" && git push origin django-tolap-v0.2.0`.
The release workflow does the rest (`CONTRIBUTING.md` "Releasing"). The workflow has not run
for real yet; watch its first run.

**Waits on the owner.** One decision from the joined-projection work, made fail-closed in
code pending an answer: a policy row filter on an object that is not in the query at all
(`encounters.region` on a patients-only query) is now refused as `row filter field not in
result`. Before, upstream's post pass evaluated it against the root's column of the same
leaf name (`region`) or, absent one, dropped every row. Alternatives: leave it to upstream
(status quo, silently reads the wrong object), or ignore filters on absent objects (never:
that loosens). Recommended: keep the refusal. Record in `docs/decisions.md` once answered.

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
- Purpose binding, delegation chains, judge: when `tolap-core` 1.1 reaches PyPI. Four merge
  scenario fixtures are skipped until then; the upstream-`main` CI leg reports drift.
- Reply on awslabs/tolap#31 when a maintainer answers.

**Things to remember.**
- Never run scripts against the configured `DATABASE_URL` directly; use Django's test
  database setup (`tests/gap/report.py`) or a throwaway `createdb`.
- The Bash tool wrapper ignores `set -e`; chain with `&&`.
- Upstream fixtures are pinned to commit `e5c92107…` (`tests/fixtures/upstream/SOURCE`).
- Upstream's field matcher lets a bare or table-wildcard rule (`encounters.*`) match any
  object's leaf key, by design; over-masks, never under-masks.
- Upstream's row-filter lookup (`_row_field_value`) hits the exact key first, then the first
  key in row order whose bare form matches. With joined columns in the row (`patients.email`
  keys) a qualified or differently-cased root filter could read the wrong object's column.
  Both adapters now present every model field to the post pass under a unique
  `object.field` key (`Preparation.key_map`), refuse a column projected twice or through an
  alias of the root, resolve every filter to exactly one column of the result (root or
  joined, case-insensitively) and copy it under the filter's own spelling
  (`Preparation.filter_keys`); a filter whose column is not in the result is refused.
  Keep the property tests' encounter regions different from the patient's; equal regions
  hide this class of bug. The differential harnesses treat "denied in both modes with the
  same reason" as agreement.
- `CLAUDE.md` is untracked on purpose; it is still the project brief.
