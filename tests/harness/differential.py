"""The property that makes pushdown safe: it never changes what the post pass returns.

``post(execute(pushdown(qs, policy))) == post(execute(qs))``, compared as sorted lists of
dicts. The right-hand side executes the caller's QuerySet as-is (as ``.values()`` over the
same projection the caller asked for) and lets upstream's pipeline do everything.
"""

from __future__ import annotations

import json
from typing import Any

from django.db.models import Manager, QuerySet
from tolap_core import EffectivePolicy, apply_result_pipeline

from django_tolap.inspect import inspect
from django_tolap.pushdown import Preparation, prepare_queryset


def post_only(
    queryset: QuerySet[Any] | Manager[Any], policy: EffectivePolicy
) -> list[dict[str, Any]]:
    """Rows the post pass alone returns for the caller's QuerySet, no pushdown at all."""
    qs = queryset.all() if isinstance(queryset, Manager) else queryset
    ins = inspect(qs)
    names = ins.projected if ins.projected is not None else ()
    rows = [dict(r) for r in qs.values(*names)]
    result: list[dict[str, Any]] = apply_result_pipeline(rows, policy)
    return result


def pushed(
    queryset: QuerySet[Any] | Manager[Any], policy: EffectivePolicy
) -> tuple[Preparation, list[dict[str, Any]]]:
    prep = prepare_queryset(queryset, policy)
    assert prep.allowed and prep.queryset is not None, prep.denial_reason
    rows = [dict(r) for r in prep.queryset]
    result: list[dict[str, Any]] = apply_result_pipeline(rows, policy)
    return prep, result


def _key(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, default=str)


def canonical(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(_key(r) for r in rows)


def assert_differential(
    queryset: QuerySet[Any] | Manager[Any], policy: EffectivePolicy
) -> list[dict[str, Any]]:
    """Assert both paths agree; return the pushed-path rows for further assertions."""
    prep, left = pushed(queryset, policy)
    right = post_only(queryset, policy)
    assert canonical(left) == canonical(right), (
        f"pushdown changed the result\n  sql: {prep.queryset.query}\n"
        f"  pushed={[(f.field, f.operator.value) for f in prep.pushed_filters]}\n"
        f"  unpushable={[(f.field, f.operator.value) for f in prep.unpushable_filters]}"
    )
    return left
