# Status (saved 2026-09-26)

**Where we are.** `django-tolap` 0.2.0 and `sqlalchemy-tolap` 0.2.0 on PyPI (2026-09-26,
tags `django-tolap-v0.2.0` and `sqlalchemy-tolap-v0.2.0`, first real run of the release
workflow: both jobs succeeded after the `pypi` environment approval). Repo public, private
vulnerability reporting on, trusted publishing configured. Upstream issue posted:
https://github.com/awslabs/tolap/issues/31, no maintainer reply yet; a draft update is
below for the owner to post. CI green on every leg (SQLite matrix, PostgreSQL, MySQL 8.4,
quickstart, upstream-main) with a 90% line-and-branch coverage floor; all legs sit at 96%.

**Releasing the next version (owner).** Bump `version` in the package's `pyproject.toml`,
date the changelog heading, `uv lock`, commit, then
`git tag -a <package>-vX.Y.Z -m "<package> X.Y.Z" && git push origin <package>-vX.Y.Z`
and approve the `pypi` environment on the run (`CONTRIBUTING.md` "Releasing").

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

**Draft update for awslabs/tolap#31 (owner posts).**
> Update: `django-tolap` 0.2.0 and `sqlalchemy-tolap` 0.2.0 are on PyPI. New since 0.1:
> joined-column projections in both adapters (`values("patient__email")`,
> `select(Patient.id, Encounter.occurred_at)`), keyed to their own object for the post pass;
> ORM write paths through `validate_write`; raw SQL wrappers over your `prepare_sql_query`;
> drf-spectacular schemas per caller. One thing worth knowing on your side: with rows that
> carry columns of two objects, `_row_field_value`'s bare-name fallback can read the wrong
> object's column when leaf names coincide (`patients.region` vs `encounters.region`). The
> adapters now key every column `object.field` and resolve each filter to exactly one of
> them before calling the pipeline, so the fallback is never reached. Happy to open a
> separate issue if a stricter lookup in core would help.

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
  `object.field` key (`Preparation.key_map`), refuse a table that appears twice in FROM
  (SQLAlchemy) or an object reached twice (Django) and a column projected twice, resolve
  every filter to exactly one column of the result (root or
  joined, case-insensitively) and copy it under the filter's own spelling
  (`Preparation.filter_keys`); a filter whose column is not in the result is refused.
  Keep the property tests' encounter regions different from the patient's; equal regions
  hide this class of bug. The differential harnesses treat "denied in both modes with the
  same reason" as agreement.
- `CLAUDE.md` is untracked on purpose; it is still the project brief.
