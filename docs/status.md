# Status (saved 2026-09-25)

**Where we are.** All six epics implemented and reviewed (`docs/03-epics.md`). v0.1.0 is
prepared, not published: versions bumped, `CHANGELOG.md` written, wheels build with
`uv build --all-packages` and pass `twine check` with LICENSE and NOTICE inside. Publish
polish done 2026-09-25: badges, `CONTRIBUTING.md`, `SECURITY.md`, issue and PR templates,
PyPI-facing package READMEs. Repo is public with private vulnerability reporting on;
CI green on every leg.

Upstream issue posted 2026-09-25: https://github.com/awslabs/tolap/issues/31.

**Released.** `django-tolap` and `sqlalchemy-tolap` 0.1.0 published to PyPI 2026-09-25,
tagged `v0.1.0`. Fresh-venv install and import verified. Commit history rewritten the same
day to use the GitHub noreply email; `CLAUDE.md` untracked.

**Since 0.1.0.** MySQL 8.4 CI leg added 2026-09-25; it exposed that 0.1.0's assignment unique
key cannot be created on MySQL, fixed by migration `0002` (see `CHANGELOG.md`, unreleased
0.1.1). Local MySQL for the suite: `docker run -d --name tolap-mysql -e MYSQL_ROOT_PASSWORD=root
-e MYSQL_DATABASE=tolap -p 3307:3306 mysql:8.4`, then
`DATABASE_URL=mysql://root:root@127.0.0.1:3307/tolap uv run pytest -q`.

**Released.** `django-tolap` 0.1.1 on PyPI 2026-09-25, tagged `v0.1.1`, fresh install verified
with migration `0002` present. `sqlalchemy-tolap` stays at 0.1.0.

**Waiting on the owner.** Nothing. Next release: create project-scoped PyPI tokens
or set up trusted publishing before uploading.

**How to resume.** `uv sync && make check` (SQLite). PostgreSQL:
`DATABASE_URL=postgres://localhost/postgres HYPOTHESIS_PROFILE=ci uv run pytest -q`
(local Homebrew PostgreSQL 17, binaries at `/opt/homebrew/opt/postgresql@17/bin`).
Regenerate the gap report with `DATABASE_URL=... make gap-report`.

**Backlog (post-v0.1, in rough priority order).**
- Purpose binding, delegation chains, judge: when `tolap-core` 1.1 reaches PyPI. Four merge
  scenario fixtures are skipped until then; the upstream-`main` CI leg reports drift.
- `tolap_resolve` management command.
- Projection of joined-table columns (`values("related__x")`, `select(Encounter.status)` next
  to a Patient root) is refused today; would need per-table object naming in rows.
- ORM write-path validation for Django (`save()`/`delete()`); DRF writes are gated already.
- drf-spectacular schema integration beyond serializer-field hiding.

**Things to remember.**
- Never run scripts against the configured `DATABASE_URL` directly; use Django's test
  database setup (`tests/gap/report.py`) or a throwaway `createdb`.
- The Bash tool wrapper ignores `set -e`; chain with `&&`.
- Upstream fixtures are pinned to commit `e5c92107…` (`tests/fixtures/upstream/SOURCE`).
