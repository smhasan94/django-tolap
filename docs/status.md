# Status (saved 2026-09-25)

**Where we are.** All six epics implemented and reviewed (`docs/03-epics.md`). v0.1.0 is
prepared, not published: versions bumped, `CHANGELOG.md` written, wheels build with
`uv build --all-packages` and pass `twine check` with LICENSE and NOTICE inside. Publish
polish done 2026-09-25: badges, `CONTRIBUTING.md`, `SECURITY.md`, issue and PR templates,
PyPI-facing package READMEs. No tag, no release, nothing posted upstream.

**Waiting on the owner.**
1. Post `docs/upstream-issue.md` to github.com/awslabs/tolap/issues.
2. Publish `django-tolap` and `sqlalchemy-tolap` 0.1.0 to PyPI (and tag) when ready:
   rebuild with `uv build --all-packages` into a clean `dist/`, run
   `uv run --with twine twine check dist/*`, then upload. Afterwards drop the "Not on PyPI
   yet" paragraph in `README.md` and date the `0.1.0 — unreleased` heading in `CHANGELOG.md`.
3. Enable private vulnerability reporting on the GitHub repository (Settings → Security);
   `SECURITY.md` and the issue-template contact link point there. Make the repo public
   before publishing, since the README badges and install URLs assume it.

**How to resume.** `uv sync && make check` (SQLite). PostgreSQL:
`DATABASE_URL=postgres://localhost/postgres HYPOTHESIS_PROFILE=ci uv run pytest -q`
(local Homebrew PostgreSQL 17, binaries at `/opt/homebrew/opt/postgresql@17/bin`).
Regenerate the gap report with `DATABASE_URL=... make gap-report`.

**Backlog (post-v0.1, in rough priority order).**
- Purpose binding, delegation chains, judge: when `tolap-core` 1.1 reaches PyPI. Four merge
  scenario fixtures are skipped until then; the upstream-`main` CI leg reports drift.
- MySQL CI leg (rules exist in `VENDORS["mysql"]`/`DIALECTS["mysql"]`, untested).
- Thin wrappers for `Manager.raw()` / cursor paths over upstream's string rewriter
  (decision 2026-09-25 item 5).
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
