"""The property that makes pushdown safe: it never changes what the post pass returns.

``post(execute(pushdown(qs, policy))) == post(execute(qs))``, compared as sorted lists of
dicts. The right-hand side executes the caller's QuerySet as-is (as ``.values()`` over the
same projection the caller asked for) and lets upstream's pipeline do everything.
"""

from __future__ import annotations

import json
from typing import Any

from django.db.models import Manager, QuerySet
from tolap_core import EffectivePolicy

from django_tolap.pushdown import EnforcementMode, Preparation, finalize, prepare_queryset


def run(
    queryset: QuerySet[Any] | Manager[Any], policy: EffectivePolicy, mode: EnforcementMode
) -> tuple[Preparation, list[dict[str, Any]]]:
    prep = prepare_queryset(queryset, policy, mode=mode)
    assert prep.allowed and prep.queryset is not None, prep.denial_reason
    rows = [dict(r) for r in prep.queryset]
    return prep, finalize(prep, rows, policy, None)


def post_only(
    queryset: QuerySet[Any] | Manager[Any], policy: EffectivePolicy
) -> list[dict[str, Any]]:
    """Rows the post pass alone returns: no filter or limit pushed, same projection."""
    return run(queryset, policy, EnforcementMode.post_only)[1]


def pushed(
    queryset: QuerySet[Any] | Manager[Any], policy: EffectivePolicy
) -> tuple[Preparation, list[dict[str, Any]]]:
    return run(queryset, policy, EnforcementMode.rewrite_and_post)


def _key(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, default=str)


def canonical(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(_key(r) for r in rows)


def assert_differential(
    queryset: QuerySet[Any] | Manager[Any], policy: EffectivePolicy
) -> list[dict[str, Any]]:
    """Assert both modes agree; return the pushed-path rows for further assertions."""
    prep, left = pushed(queryset, policy)
    right = post_only(queryset, policy)
    qs = queryset.all() if isinstance(queryset, Manager) else queryset
    if prep.max_results is not None and not qs.query.order_by and not qs.ordered:
        # A limit without ORDER BY picks database-chosen rows on either path; only the
        # count is comparable.
        assert len(left) == len(right), "limit without ordering changed the row count"
        return left
    assert canonical(left) == canonical(right), (
        f"pushdown changed the result\n  sql: {prep.queryset.query}\n"
        f"  pushed={[(f.field, f.operator.value) for f in prep.pushed_filters]}\n"
        f"  unpushable={[(f.field, f.operator.value) for f in prep.unpushable_filters]}"
    )
    return left
