"""Schema-drift warnings for the admin: fields a policy names that a targeted model lacks."""

from __future__ import annotations

from typing import Any

from django.apps import apps
from tolap_core import PolicyDefinition as UpstreamDefinition

from django_tolap.matching import is_pattern
from django_tolap.objects import object_name
from django_tolap.precheck import FieldRules, unknown_fields


def targeted_objects(definition: UpstreamDefinition) -> set[str]:
    """Object names the policy addresses literally: allowed objects and field qualifiers."""
    rules = definition.object_rules
    if rules is None:
        return set()
    names = {o.lower() for o in (rules.allowed_objects or ()) if not is_pattern(o)}
    fr = rules.field_rules
    fields: list[str] = list(f.field for f in (rules.row_filters or ()))
    if fr:
        fields += list(fr.hidden_fields or ()) + list(fr.allowed_fields or ())
        fields += [m.field for m in (fr.masked_fields or ())]
    for name in fields:
        qualifier, _, _ = name.rpartition(".")
        if qualifier and not is_pattern(qualifier):
            names.add(qualifier.lower())
    return names


def drift_warnings(definition: UpstreamDefinition) -> list[str]:
    """One warning per (model, unknown field), for every installed model the policy targets."""
    targets = targeted_objects(definition)
    if not targets:
        return []
    rules = FieldRules.of(definition)  # same object_rules shape as EffectivePolicy
    warnings: list[str] = []
    for model in apps.get_models():
        obj = object_name(model)
        if obj.lower() not in targets:
            continue
        for name in unknown_fields(model, rules):
            warnings.append(f"{obj}: field {name!r} does not exist on {model._meta.label}")
    return warnings


def drift_warnings_for_body(body: dict[str, Any]) -> list[str]:
    from tolap_core import deserialize_policy_definition

    try:
        return drift_warnings(deserialize_policy_definition(body))
    except (KeyError, ValueError, TypeError, AttributeError):
        return []
