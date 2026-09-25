# Status (saved 2026-09-25, end of day)

**Where we are.** v0.1 complete and released; post-v0.1 backlog in progress. Both packages
on PyPI: `django-tolap` 0.1.1 (tag `v0.1.1`), `sqlalchemy-tolap` 0.1.0 (tag `v0.1.0`).
Repo public, private vulnerability reporting on, trusted publishing configured (PyPI
publishers and the `pypi` GitHub environment exist). Upstream issue posted:
https://github.com/awslabs/tolap/issues/31, no maintainer reply yet. CI green on every leg
(SQLite matrix, PostgreSQL, MySQL 8.4, quickstart, upstream-main) with a 90% line-and-branch
coverage floor; all legs sit at 96%.

**Unreleased on `main` (django-tolap, see `CHANGELOG.md` "Unreleased").**
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
- drf-spectacular schema integration beyond serializer-field hiding (~1 day).
- SQLAlchemy: projecting a non-root entity or column (`select(Patient.id, Encounter.status)`)
  is still refused; Django's `values("related__x")` landed by presenting joined keys as
  `object.field` to the post pass. SQLAlchemy row keys collide (`status` twice) without
  labels, so it needs a labelling rule first (~1 day).
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
- `CLAUDE.md` is untracked on purpose; it is still the project brief.
