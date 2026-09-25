"""Pre-execution checks (connector spec section 5, read path), fail closed.

Order, and the reason string each produces:

1. ``canQuery`` false                         -> ``query not permitted`` (upstream)
2. root object denied                          -> upstream ``validate_access`` reason
3. any joined/subquery object denied           -> upstream ``validate_access`` reason
4. policy names a field the root model lacks   -> ``policy references unknown field: <name>``
5. query references a hidden/non-allowed field -> ``query references fields you do not have
                                                   permission to access`` (upstream text)
6. an annotation is computed from a masked     -> ``annotation exposes masked field: <name>``
   field

Every denial is a refusal, never a narrowing: a hidden column in ``WHERE`` or ``ORDER BY``
decides which rows return even when it is not projected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db.models import Model, QuerySet
from tolap_core import AccessResult, EffectivePolicy, validate_access

from django_tolap.exceptions import Uninspectable
from django_tolap.inspect import FieldRef, Inspection, inspect
from django_tolap.matching import field_matches, is_pattern
from django_tolap.objects import object_name

UNKNOWN_FIELD = "policy references unknown field: {name}"
FIELD_DENIED = "query references fields you do not have permission to access"
MASKED_ANNOTATION = "annotation exposes masked field: {name}"
CANNOT_INSPECT = "query cannot be inspected: {why}"


@dataclass(frozen=True)
class FieldRules:
    hidden: tuple[str, ...]
    allowed: tuple[str, ...] | None
    masked: tuple[str, ...]
    filtered: tuple[str, ...]

    @classmethod
    def of(cls, policy: EffectivePolicy) -> FieldRules:
        rules = policy.object_rules
        fr = rules.field_rules if rules else None
        return cls(
            hidden=tuple(fr.hidden_fields or ()) if fr else (),
            allowed=tuple(fr.allowed_fields) if fr and fr.allowed_fields is not None else None,
            masked=tuple(m.field for m in (fr.masked_fields or ())) if fr else (),
            filtered=tuple(f.field for f in (rules.row_filters or ())) if rules else (),
        )


def qualified(ref: FieldRef) -> str:
    return f"{object_name(ref.model)}.{ref.name}"


def is_hidden(rules: FieldRules, key: str) -> bool:
    return any(field_matches(rule, key) for rule in rules.hidden)


def is_allowed(rules: FieldRules, key: str) -> bool:
    if rules.allowed is None:
        return True
    return any(field_matches(rule, key) for rule in rules.allowed)


def is_masked(rules: FieldRules, key: str) -> bool:
    return any(field_matches(rule, key) for rule in rules.masked)


def field_visible(rules: FieldRules, key: str) -> bool:
    """Not hidden and (if an allow-list exists) allowed. ``[]`` allow-list denies all."""
    return not is_hidden(rules, key) and is_allowed(rules, key)


def unknown_fields(model: type[Model], rules: FieldRules) -> list[str]:
    """Policy field names that must exist on ``model`` but do not (decision 2026-09-25).

    Bare names and names qualified with this model's object name must resolve to a concrete
    field. Names qualified with another object are that object's concern. Patterns are
    exempt: a glob matching nothing hides nothing.
    """
    obj = object_name(model).lower()
    concrete = {f.name.lower() for f in model._meta.concrete_fields}
    unknown: list[str] = []
    for name in (*rules.filtered, *rules.hidden, *(rules.allowed or ()), *rules.masked):
        if is_pattern(name):
            continue
        qualifier, _, leaf = name.rpartition(".")
        if qualifier and qualifier.lower() != obj:
            continue
        if leaf.lower() not in concrete:
            unknown.append(name)
    return unknown


def precheck_inspection(ins: Inspection, policy: EffectivePolicy) -> AccessResult:
    if not policy.permissions.can_query:
        return AccessResult(allowed=False, reason="query not permitted")

    root_access = validate_access(object_name(ins.root), policy)
    if not root_access.allowed:
        return root_access
    for model in sorted(ins.models - {ins.root}, key=lambda m: m._meta.label_lower):
        access = validate_access(object_name(model), policy)
        if not access.allowed:
            return access

    rules = FieldRules.of(policy)
    unknown = unknown_fields(ins.root, rules)
    if unknown:
        return AccessResult(allowed=False, reason=UNKNOWN_FIELD.format(name=unknown[0]))

    for ref in sorted(ins.referenced):
        if not field_visible(rules, qualified(ref)):
            return AccessResult(allowed=False, reason=FIELD_DENIED)

    for name, sources in sorted(ins.annotations.items()):
        for ref in sorted(sources):
            if is_masked(rules, qualified(ref)):
                return AccessResult(allowed=False, reason=MASKED_ANNOTATION.format(name=name))

    return AccessResult(allowed=True)


def precheck(queryset: QuerySet[Any], policy: EffectivePolicy) -> AccessResult:
    """Run every pre-execution check; the first failing check names the reason."""
    try:
        ins = inspect(queryset)
    except Uninspectable as exc:
        return AccessResult(allowed=False, reason=CANNOT_INSPECT.format(why=exc.why))
    return precheck_inspection(ins, policy)
