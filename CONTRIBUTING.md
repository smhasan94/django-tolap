# Contributing

Thanks for looking. This repository holds two packages, `django-tolap` and
`sqlalchemy-tolap`, in a `uv` workspace. Both are adapters for
[TOLAP](https://github.com/awslabs/tolap); neither vendors or forks it.

## Setup

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/smhasan94/django-tolap
cd django-tolap
uv sync
make check          # ruff, mypy --strict, migration check, pytest on SQLite
```

`make check` is what CI runs on every Python and Django version in the matrix. It takes
under a minute on SQLite.

### PostgreSQL

Pushdown rules differ per database, so the differential tests also run on PostgreSQL in
CI. Locally, point `DATABASE_URL` at a server you can create test databases on:

```bash
DATABASE_URL=postgres://localhost/postgres HYPOTHESIS_PROFILE=ci uv run pytest -q
```

Django creates and drops a `test_*` database; nothing touches the named database itself.

### MySQL

The suite also runs on MySQL 8.4 in CI. Locally, a throwaway container is enough:

```bash
docker run -d --name tolap-mysql -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=tolap \
  -p 3307:3306 mysql:8.4
DATABASE_URL=mysql://root:root@127.0.0.1:3307/tolap uv run pytest -q
```

The driver is `mysqlclient`, which compiles against libmysqlclient. Debian/Ubuntu:
`apt-get install default-libmysqlclient-dev pkg-config`. macOS: `brew install mysql-client`
and, if `uv sync` fails to link (a universal2 Python or a mismatched Xcode), build with the
Command Line Tools toolchain:

```bash
CLT=/Library/Developer/CommandLineTools
CC=$CLT/usr/bin/clang LDSHARED="$CLT/usr/bin/clang -bundle -undefined dynamic_lookup" \
SDKROOT=$CLT/SDKs/MacOSX.sdk ARCHFLAGS="-arch arm64" \
PKG_CONFIG_PATH=/opt/homebrew/opt/mysql-client/lib/pkgconfig uv sync
```

The SQLAlchemy fixtures create and drop a second database, `test_tolap_sa`, on the same
server.

### Other targets

| Target | What it does |
| --- | --- |
| `make fmt` | `ruff format` and autofix |
| `make gap-report` | Regenerates `docs/gap-report.md` (needs `DATABASE_URL`; CI diffs it) |
| `make demo` | Seeds `examples/clinic` on SQLite and runs the benchmark |
| `scripts/quickstart_check.sh` | Installs the package into a fresh project and runs the README quickstart |

## What a change needs

1. **Tests.** Every behaviour change comes with a test. Pushdown changes need a
   differential test: pushdown plus post pass must return the same rows as post pass alone.
   The fixtures in `tests/fixtures/upstream/` are upstream's and are pinned to the commit in
   `SOURCE`; do not edit them, add local fixtures next to them.
2. **Fail closed.** Anything the adapter cannot translate faithfully is left to TOLAP's
   post-execution pass and reported in `Preparation.unpushable_filters`. Never emit a looser
   SQL filter, never narrow a projection silently, never skip the post pass.
3. **Green `make check`.** Lint, types and tests pass before a commit. `make test` measures
   line and branch coverage of both packages and fails under 90% (`[tool.coverage.report]`
   in `pyproject.toml`); every CI leg clears that on its own, so vendor-specific code needs a
   test on its vendor, not a skip.
4. **A decision record** in `docs/decisions.md` when a change picks between semantically
   different options (a new vendor rule, a new refusal, a changed default). Date, question,
   options, decision, rationale.
5. **`CHANGELOG.md`** entry under the unreleased heading for anything user-visible.

## Adding a database vendor rule

Vendor rules live in `VENDORS` (`django_tolap`) and `DIALECTS` (`sqlalchemy_tolap`). A rule
says which TOLAP operators are pushed for which field kinds on that database. Add a rule
only with a CI leg that runs the differential tests on that database; an untested rule is
listed as such in the README compatibility table.

## Commits

Short imperative summary line, optional body explaining why. One logical change per commit.

## Releasing

Releases run from `.github/workflows/release.yml` through PyPI trusted publishing; no token
is stored anywhere. Each package releases on its own:

1. On `main`, bump `version` in `packages/<package>/pyproject.toml`, date the matching
   `## <version>` heading in `CHANGELOG.md`, run `uv lock`, merge through a pull request.
2. Tag that commit `<package>-v<version>` and push the tag:

   ```bash
   git tag -a django-tolap-v0.2.0 -m "django-tolap 0.2.0"
   git push origin django-tolap-v0.2.0
   ```

The workflow refuses a tag whose version differs from the pyproject, runs lint, types and
tests, builds only that package, checks it with twine, publishes it, and creates the GitHub
release with the wheel, the sdist and the `CHANGELOG.md` section for that version as notes.

## Reporting bugs and proposing features

Use the issue templates. For anything about the protocol itself (policy schema, resolution,
masking semantics) open the issue with [upstream](https://github.com/awslabs/tolap/issues)
instead; this project follows their spec.

## License

By contributing you agree that your contributions are licensed under Apache-2.0, the
license of this repository.
