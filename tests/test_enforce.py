from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from django.db.models import Count

import django_tolap
from django_tolap import TolapDenied, enforce
from django_tolap.enforce import validate
from tests.harness.contexts import signed
from tests.harness.fixtures import effective_policy
from tests.testapp.models import Patient

pytestmark = pytest.mark.django_db

ANALYST = {
    "permissions": {"canQuery": True, "readOnly": True},
    "objectRules": {
        "allowedObjects": ["patients"],
        "fieldRules": {
            "hiddenFields": ["patients.ssn", "patients.date_of_birth"],
            "maskedFields": [
                {
                    "field": "patients.email",
                    "maskType": "hash",
                    "parameters": {"algorithm": "sha256"},
                },
                {
                    "field": "patients.full_name",
                    "maskType": "partial",
                    "parameters": {"showFirst": 1, "maskChar": "*"},
                },
            ],
        },
        "rowFilters": [
            {"field": "region", "operator": "in", "values": ["us-east", "us-west"]},
            {"field": "status", "operator": "notEquals", "value": "deleted"},
        ],
    },
    "limits": {"maxResults": 5000},
}


def test_readme_policy_end_to_end(seeded: None) -> None:
    rows = enforce(Patient.objects.order_by("id"), signed(effective_policy(ANALYST)))
    assert [r["id"] for r in rows] == [1, 2, 3]
    row = rows[0]
    assert "ssn" not in row and "date_of_birth" not in row
    assert row["full_name"] == "J" + "*" * 9
    assert row["email"] == hashlib.sha256(b"john.smith@example.com").hexdigest()[:16]
    assert row["region"] == "us-east"


def test_returns_dicts_never_instances(seeded: None) -> None:
    rows = enforce(
        Patient.objects.all(), signed(effective_policy({"permissions": {"canQuery": True}}))
    )
    assert all(type(r) is dict for r in rows) and len(rows) == 6


def test_manager_accepted(seeded: None) -> None:
    assert (
        len(enforce(Patient.objects, signed(effective_policy({"permissions": {"canQuery": True}}))))
        == 6
    )


def test_tampered_signature_denied(seeded: None) -> None:
    ctx = signed(effective_policy(ANALYST))
    ctx.effective_policy.limits.max_results = 1  # type: ignore[union-attr]
    with pytest.raises(TolapDenied) as exc:
        enforce(Patient.objects.all(), ctx)
    assert exc.value.reason == "invalid signature"
    assert str(exc.value) == "Access denied: invalid signature"


def test_wrong_key_denied(seeded: None) -> None:
    with pytest.raises(TolapDenied, match="invalid signature"):
        enforce(Patient.objects.all(), signed(effective_policy(ANALYST), key="other"))


def test_expired_denied_after_signature(seeded: None) -> None:
    ctx = signed(effective_policy(ANALYST), ttl=timedelta(seconds=-1))
    with pytest.raises(TolapDenied) as exc:
        enforce(Patient.objects.all(), ctx)
    assert "expired" in exc.value.reason
    ctx.signature = "tampered"
    with pytest.raises(TolapDenied, match="invalid signature"):
        validate(ctx)


def test_denials_carry_reason_only(seeded: None) -> None:
    ctx = signed(effective_policy(ANALYST))
    with pytest.raises(TolapDenied) as exc:
        enforce(Patient.objects.values("id", "ssn"), ctx)
    assert exc.value.reason == "denied fields: patients.ssn"
    assert "John" not in str(exc.value)


def test_hidden_object_denied(seeded: None) -> None:
    from tests.testapp.models import AuditLog

    with pytest.raises(TolapDenied, match="object not in allowed set"):
        enforce(AuditLog.objects.all(), signed(effective_policy(ANALYST)))


def test_can_query_false_denied(seeded: None) -> None:
    with pytest.raises(TolapDenied, match="query not permitted"):
        enforce(
            Patient.objects.all(), signed(effective_policy({"permissions": {"canQuery": False}}))
        )


def test_unpushable_filter_still_enforced_by_post_pass(seeded: None) -> None:
    p = effective_policy(
        {
            "permissions": {"canQuery": True},
            "objectRules": {
                "rowFilters": [{"field": "full_name", "operator": "startsWith", "value": "J"}]
            },
        }
    )
    rows = enforce(Patient.objects.order_by("id"), signed(p))
    assert [r["id"] for r in rows] == [1, 2]


def test_hash_salt_from_settings_and_override(seeded: None, settings) -> None:  # type: ignore[no-untyped-def]
    p = effective_policy(
        {
            "permissions": {"canQuery": True},
            "objectRules": {
                "fieldRules": {"maskedFields": [{"field": "email", "maskType": "hash"}]}
            },
        }
    )
    plain = enforce(Patient.objects.filter(id=1), signed(p))[0]["email"]
    settings.TOLAP = {**settings.TOLAP, "HASH_SALT": "pepper"}
    salted = enforce(Patient.objects.filter(id=1), signed(p))[0]["email"]
    explicit = enforce(Patient.objects.filter(id=1), signed(p), hash_salt="other")[0]["email"]
    assert len({plain, salted, explicit}) == 3


def test_annotations_survive_post_pass(seeded: None) -> None:
    rows = enforce(
        Patient.objects.annotate(n=Count("encounters")).order_by("id"),
        signed(effective_policy({"permissions": {"canQuery": True}})),
    )
    assert rows[0]["n"] == 1


def test_public_api_has_single_executing_entry_point() -> None:
    """Only ``enforce``, ``enforce_sql`` and ``enforce_raw`` execute anything, each through the
    post pass; nothing else public runs a query."""
    executing = {name for name in django_tolap.__all__ if callable(getattr(django_tolap, name))}
    assert executing == {
        "enforce",
        "enforce_raw",
        "enforce_sql",
        "EnforcementMode",
        "TolapDenied",
        "TolapSchemaMismatch",
        "ToolContext",
        "Uninspectable",
        "accept_context",
        "issue_context",
        "tolap_context",
        "tolap_tool",
    }


def test_post_only_mode_returns_same_rows_without_pushing(seeded: None) -> None:
    ctx = signed(effective_policy(ANALYST))
    pushed = enforce(Patient.objects.order_by("id"), ctx)
    post = enforce(Patient.objects.order_by("id"), ctx, mode="postOnly")
    assert pushed == post
    with pytest.raises(ValueError):
        enforce(Patient.objects.all(), ctx, mode="rewriteOnly")


def test_filter_field_added_for_post_pass_is_stripped_from_output(seeded: None) -> None:
    p = effective_policy(
        {
            "permissions": {"canQuery": True},
            "objectRules": {
                "rowFilters": [{"field": "region", "operator": "equals", "value": "us-east"}]
            },
        }
    )
    rows = enforce(Patient.objects.values("id", "full_name").order_by("id"), signed(p))
    assert [r["id"] for r in rows] == [1, 3]
    assert all(set(r) == {"id", "full_name"} for r in rows)
