"""Differential assertion for the SQLAlchemy adapter (same property as the Django harness)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session
from tolap_core import EffectivePolicy

from sqlalchemy_tolap.enforce import dialect_name
from sqlalchemy_tolap.pushdown import EnforcementMode, Preparation, finalize, prepare_select


def run(
    stmt: Any, policy: EffectivePolicy, session: Session, mode: EnforcementMode
) -> tuple[Preparation, list[dict[str, Any]]]:
    prep = prepare_select(stmt, policy, dialect=dialect_name(session), mode=mode)
    assert prep.allowed and prep.statement is not None, prep.denial_reason
    rows = [dict(r) for r in session.execute(prep.statement).mappings().all()]
    return prep, finalize(prep, rows, policy, None)


def total_order(stmt: Any) -> bool:
    """Whether the statement's ORDER BY includes a primary-key column, so ties cannot occur."""
    for clause in stmt._order_by_clauses:
        column = getattr(clause, "element", clause)  # unwrap desc()/asc()
        if getattr(column, "primary_key", False):
            return True
    return False


def canonical(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)


def assert_differential(
    stmt: Any, policy: EffectivePolicy, session: Session
) -> list[dict[str, Any]]:
    prep, left = run(stmt, policy, session, EnforcementMode.rewrite_and_post)
    _, right = run(stmt, policy, session, EnforcementMode.post_only)
    if prep.max_results is not None and not total_order(stmt):
        # A limit without a total ORDER BY picks database-chosen rows among ties on either
        # path (MySQL demonstrably differs between the LIMIT and unlimited plans); only the
        # count is comparable.
        assert len(left) == len(right), "limit without total ordering changed the row count"
        return left
    assert canonical(left) == canonical(right), (
        f"pushdown changed the result\n  sql: {prep.statement}\n"
        f"  pushed={[(f.field, f.operator.value) for f in prep.pushed_filters]}\n"
        f"  unpushable={[(f.field, f.operator.value) for f in prep.unpushable_filters]}"
    )
    return left
