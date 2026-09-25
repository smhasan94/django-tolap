"""Pre-execution checks (connector spec section 5), same order and reasons as django-tolap."""

from __future__ import annotations

from typing import Any

from tolap_core import AccessResult, EffectivePolicy, validate_access

from sqlalchemy_tolap.exceptions import Uninspectable
from sqlalchemy_tolap.inspect import Inspection, inspect
from sqlalchemy_tolap.rules import FieldRules, field_visible, is_masked, unknown_fields

UNKNOWN_FIELD = "policy references unknown field: {name}"
FIELD_DENIED = "denied fields: {names}"
MASKED_ANNOTATION = "annotation exposes masked field: {name}"
CANNOT_INSPECT = "query cannot be inspected: {why}"


def field_denied(names: list[str]) -> str:
    return FIELD_DENIED.format(names=", ".join(names))


def precheck_inspection(ins: Inspection, policy: EffectivePolicy) -> AccessResult:
    if not policy.permissions.can_query:
        return AccessResult(allowed=False, reason="query not permitted")
    root_access = validate_access(ins.root.name, policy)
    if not root_access.allowed:
        return root_access
    for name in sorted(n for n in ins.tables if n != ins.root.name):
        access = validate_access(name, policy)
        if not access.allowed:
            return access
    rules = FieldRules.of(policy)
    unknown = unknown_fields(ins.root, rules)
    if unknown:
        return AccessResult(allowed=False, reason=UNKNOWN_FIELD.format(name=unknown[0]))
    denied = sorted(
        f"{r.table}.{r.name}"
        for r in ins.referenced
        if not field_visible(rules, f"{r.table}.{r.name}")
    )
    if denied:
        return AccessResult(allowed=False, reason=field_denied(denied))
    for label, sources in sorted(ins.annotations.items()):
        for ref in sorted(sources):
            if is_masked(rules, f"{ref.table}.{ref.name}"):
                return AccessResult(allowed=False, reason=MASKED_ANNOTATION.format(name=label))
    return AccessResult(allowed=True)


def precheck(stmt: Any, policy: EffectivePolicy) -> AccessResult:
    try:
        ins = inspect(stmt)
    except Uninspectable as exc:
        return AccessResult(allowed=False, reason=CANNOT_INSPECT.format(why=exc.why))
    return precheck_inspection(ins, policy)
