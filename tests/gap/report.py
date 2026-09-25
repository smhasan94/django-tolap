"""Run the corpus through upstream's string rewriter and through ORM pushdown; render Markdown.

Usage (writes ``docs/gap-report.md``; the PostgreSQL columns need ``DATABASE_URL``)::

    PYTHONPATH=. uv run python -m tests.gap.report > docs/gap-report.md

The upstream rewriter is not at fault for any row here: it was never written for
ORM-rendered SQL, and its own docs say so. The table measures the gap, not a defect.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
django.setup()

from django.db import connection, transaction  # noqa: E402
from django.test.utils import setup_databases, teardown_databases  # noqa: E402
from sqlalchemy import create_engine, insert  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from tolap_core import SqlDialect, prepare_sql_query  # noqa: E402

from django_tolap.pushdown import prepare_queryset  # noqa: E402
from sqlalchemy_tolap.pushdown import prepare_select  # noqa: E402
from tests.gap.corpus import CORPUS, POLICIES  # noqa: E402
from tests.gap.sa_corpus import SA_CORPUS  # noqa: E402
from tests.harness.seed import ENCOUNTERS, PATIENTS, seed  # noqa: E402

DIALECTS = {"postgresql": SqlDialect.postgres, "sqlite": SqlDialect.ansi}


def _executes(sql: str) -> str:
    """Whether the rewriter's output runs on this database as rendered by ``str(query)``."""
    try:
        # A savepoint: on PostgreSQL a failed statement would otherwise abort the
        # surrounding transaction (the test suite runs this inside one).
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(sql)
            cur.fetchall()
    except Exception as exc:  # noqa: BLE001 - the error class is the finding
        return f"no ({type(exc).__name__})"
    return "yes"


def upstream_row(sql: str, policy: Any) -> dict[str, str]:
    prep = prepare_sql_query(sql, policy, dialect=DIALECTS.get(connection.vendor, SqlDialect.ansi))
    if not prep.allowed:
        return {"outcome": f"refused: {prep.denial_reason}", "executes": "-"}
    pushed = "rewritten" if prep.rewritten else "unchanged"
    unpushed = ", ".join(f.field for f in prep.unpushable_filters) or "none"
    return {"outcome": f"{pushed}; unpushed: {unpushed}", "executes": _executes(prep.query)}


def ours_row(qs: Any, policy: Any) -> str:
    prep = prepare_queryset(qs, policy)
    if not prep.allowed:
        return f"refused: {prep.denial_reason}"
    pushed = len(prep.pushed_filters)
    total = pushed + len(prep.unpushable_filters)
    rows = len(list(prep.queryset)) if prep.queryset is not None else 0
    return f"pushed {pushed}/{total} filters, {len(prep.visible_fields)} visible cols, {rows} rows fetched"


def _sa_session() -> Session:
    """An in-memory SQLite session with upstream's seed rows (schema-less tables)."""
    import datetime as dt

    from tests.sqlalchemy import models

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    if models.SCHEMA:
        # The test models are schema-qualified when DATABASE_URL is PostgreSQL; SQLite
        # accepts the same qualified names once a database is attached under that name.
        # ATTACH must run outside a transaction, so it goes on the DBAPI connect event.
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _attach(dbapi_connection: Any, _record: Any) -> None:
            dbapi_connection.execute(f"ATTACH DATABASE ':memory:' AS {models.SCHEMA}")

    models.metadata.create_all(engine)
    session = Session(engine)
    session.execute(
        insert(models.patients),
        [
            {
                "id": i,
                "full_name": n,
                "email": e,
                "ssn": s,
                "date_of_birth": dt.date.fromisoformat(d),
                "region": r,
                "status": st,
            }
            for i, (n, e, s, d, r, st) in enumerate(PATIENTS, start=1)
        ],
    )
    session.execute(
        insert(models.encounters),
        [
            {
                "id": i,
                "patient_id": p,
                "occurred_at": dt.datetime.fromisoformat(o),
                "region": r,
                "status": st,
            }
            for i, (p, o, r, st) in enumerate(ENCOUNTERS, start=1)
        ],
    )
    session.flush()
    return session


def sa_upstream_row(sql: str, policy: Any, session: Session) -> dict[str, str]:
    from sqlalchemy import text

    prep = prepare_sql_query(sql, policy, dialect=SqlDialect.ansi)
    if not prep.allowed:
        return {"outcome": f"refused: {prep.denial_reason}", "executes": "-"}
    pushed = "rewritten" if prep.rewritten else "unchanged"
    unpushed = ", ".join(f.field for f in prep.unpushable_filters) or "none"
    try:
        with session.begin_nested():
            session.execute(text(prep.query)).all()
    except Exception as exc:  # noqa: BLE001 - the error class is the finding
        return {
            "outcome": f"{pushed}; unpushed: {unpushed}",
            "executes": f"no ({type(exc).__name__})",
        }
    return {"outcome": f"{pushed}; unpushed: {unpushed}", "executes": "yes"}


def sa_ours_row(stmt: Any, policy: Any, session: Session) -> str:
    prep = prepare_select(stmt, policy, dialect="sqlite")
    if not prep.allowed:
        return f"refused: {prep.denial_reason}"
    pushed = len(prep.pushed_filters)
    total = pushed + len(prep.unpushable_filters)
    rows = len(session.execute(prep.statement).all()) if prep.statement is not None else 0
    return f"pushed {pushed}/{total} filters, {len(prep.visible_fields)} visible cols, {rows} rows fetched"


def render_sqlalchemy() -> str:
    session = _sa_session()
    dialect = session.get_bind().dialect
    lines = [
        "# SQLAlchemy",
        "",
        "Statements rendered with `str(stmt.compile(dialect, compile_kwargs={'literal_binds': True}))` "
        "(so parameters are inlined, the friendliest form for a string rewriter) and handed to "
        "upstream `prepare_sql_query` with the `ansi` profile; the same statement goes through "
        "`sqlalchemy_tolap.prepare_select` on SQLite.",
        "",
    ]
    for policy_name, policy in POLICIES.items():
        lines += [
            f"## Policy: {policy_name} (SQLAlchemy)",
            "",
            "| Select | Shape | Upstream rewriter on compiled SQL | Rewritten SQL executes? | sqlalchemy-tolap |",
            "| --- | --- | --- | --- | --- |",
        ]
        for name, factory, description in SA_CORPUS:
            stmt = factory()
            sql = str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
            up = sa_upstream_row(sql, policy, session)
            lines.append(
                f"| `{name}` | {description} | {up['outcome']} | {up['executes']} | {sa_ours_row(stmt, policy, session)} |"
            )
        lines.append("")
    return "\n".join(lines)


def render() -> str:
    lines = [
        "# Gap report: upstream string rewriter vs ORM-native pushdown",
        "",
        f"Generated by `tests/gap/report.py` on vendor `{connection.vendor}` with `tolap-core` "
        "1.0.0. Each QuerySet is rendered with `str(qs.query)` and handed to upstream "
        "`prepare_sql_query`; the same QuerySet goes through `django_tolap.prepare_queryset`. "
        "Upstream's rewriter was never designed for ORM-rendered SQL (its docs say to use "
        "`postOnly` when an ORM owns the SQL); this table measures that gap.",
        "",
    ]
    for policy_name, policy in POLICIES.items():
        lines += [
            f"## Policy: {policy_name}",
            "",
            "| QuerySet | Shape | Upstream rewriter on `str(qs.query)` | Rewritten SQL executes? | django-tolap |",
            "| --- | --- | --- | --- | --- |",
        ]
        for name, factory, description in CORPUS:
            qs = factory()
            up = upstream_row(str(qs.query), policy)
            lines.append(
                f"| `{name}` | {description} | {up['outcome']} | {up['executes']} | {ours_row(qs, policy)} |"
            )
        lines.append("")
    refused = sum(
        1
        for p in POLICIES.values()
        for _, f, _ in CORPUS
        if not prepare_sql_query(
            str(f().query), p, dialect=DIALECTS.get(connection.vendor, SqlDialect.ansi)
        ).allowed
    )
    total = len(POLICIES) * len(CORPUS)
    lines += [
        "## Summary",
        "",
        f"- Upstream refused or left unchanged: see table; refused outright: {refused} of {total} (QuerySet, policy) pairs.",
        "- Django renders a default projection as an explicit column list, so any hidden column on the model makes the rewriter refuse the query (`validate_query` sees the column named).",
        '- Injected predicates are unqualified (`"region" = ...`), which is ambiguous once a join is present.',
        "- `str(qs.query)` is not executable SQL: parameters are interpolated without quoting, so string filters and dates fail to run.",
        "",
    ]
    return "\n".join(lines) + "\n" + render_sqlalchemy()


def main() -> None:
    """Render against a throwaway test database (``test_<name>``), never the configured one."""
    old_config = setup_databases(verbosity=0, interactive=False)
    try:
        seed()
        sys.stdout.write(render())
    finally:
        teardown_databases(old_config, verbosity=0)


if __name__ == "__main__":
    main()
