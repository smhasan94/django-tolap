"""Field-rule helpers shared by the pre-check and the projection (mirrors django_tolap.precheck)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Table
from tolap_core import EffectivePolicy, PolicyDefinition

from sqlalchemy_tolap.matching import field_matches, is_pattern


@dataclass(frozen=True)
class FieldRules:
    hidden: tuple[str, ...]
    allowed: tuple[str, ...] | None
    masked: tuple[str, ...]
    filtered: tuple[str, ...]

    @classmethod
    def of(cls, policy: EffectivePolicy | PolicyDefinition) -> FieldRules:
        rules = policy.object_rules
        fr = rules.field_rules if rules else None
        return cls(
            hidden=tuple(fr.hidden_fields or ()) if fr else (),
            allowed=tuple(fr.allowed_fields) if fr and fr.allowed_fields is not None else None,
            masked=tuple(m.field for m in (fr.masked_fields or ())) if fr else (),
            filtered=tuple(f.field for f in (rules.row_filters or ())) if rules else (),
        )


def is_hidden(rules: FieldRules, key: str) -> bool:
    return any(field_matches(rule, key) for rule in rules.hidden)


def is_allowed(rules: FieldRules, key: str) -> bool:
    return rules.allowed is None or any(field_matches(rule, key) for rule in rules.allowed)


def is_masked(rules: FieldRules, key: str) -> bool:
    return any(field_matches(rule, key) for rule in rules.masked)


def field_visible(rules: FieldRules, key: str) -> bool:
    return not is_hidden(rules, key) and is_allowed(rules, key)


def unknown_fields(table: Table, rules: FieldRules) -> list[str]:
    """Policy field names that must exist on ``table`` but do not (bare or table-qualified)."""
    obj = table.name.lower()
    columns = {c.name.lower() for c in table.columns}
    unknown: list[str] = []
    for name in (*rules.filtered, *rules.hidden, *(rules.allowed or ()), *rules.masked):
        if is_pattern(name):
            continue
        qualifier, _, leaf = name.rpartition(".")
        if qualifier and qualifier.lower() != obj:
            continue
        if leaf.lower() not in columns:
            unknown.append(name)
    return unknown
