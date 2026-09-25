"""django-tolap under upstream's ``tolap-mcp`` wrapper: the two layers do not conflict.

Upstream's wrapper governs the *tool call* (allowed tools, object and declared fields,
signature, expiry) and runs its own post pass on whatever the tool returns. django-tolap
governs the *query*. Both use the same signed context.

One interaction to know: ``hash`` masking is not idempotent, so a tool that already
returned hashed pseudonyms and is then post-passed again by ``execute_with_enforcement``
gets them hashed twice. The clean composition is upstream ``pre_execute`` for the call plus
django-tolap ``enforce`` for the data; the last test pins the double-hash so the docs stay
honest.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from tolap_mcp import SecureMcpServerOptions, SecureMcpToolWrapper

from django_tolap import ToolContext, tolap_tool
from django_tolap.contexts import issue_context
from django_tolap.store import DjangoPolicyStore
from tests.testapp.models import Patient

pytestmark = pytest.mark.django_db

SOURCE = "db:testapp:patients"
KEY = "test-signing-key"


@pytest.fixture
def context(seeded: None):  # type: ignore[no-untyped-def]
    store = DjangoPolicyStore()
    store.save_definition_json(
        {
            "version": "1.0",
            "name": "analyst",
            "permissions": {"canQuery": True, "readOnly": True},
            "objectRules": {
                "allowedObjects": ["patients"],
                "fieldRules": {
                    "hiddenFields": ["patients.ssn"],
                    "maskedFields": [{"field": "patients.email", "maskType": "hash"}],
                },
                "rowFilters": [{"field": "region", "operator": "equals", "value": "us-east"}],
            },
        }
    )
    store.assign("analyst", user_id="alice", tenant_id="clinic", granted_by="a", reason="r")
    return issue_context("alice", "clinic", SOURCE)


@tolap_tool(source=SOURCE)
def patients_search(q: str, *, tolap: ToolContext) -> list[dict[str, Any]]:
    return tolap.enforce(Patient.objects.filter(full_name__icontains=q).order_by("id"))


def test_upstream_pre_execute_then_django_tolap_enforce(context) -> None:  # type: ignore[no-untyped-def]
    wrapper = SecureMcpToolWrapper(
        SecureMcpServerOptions(signing_key=KEY, allowed_tools=["patients_search"])
    )
    pre = wrapper.pre_execute(
        context, "patients_search", object_name="patients", fields=["patients.full_name"]
    )
    assert pre.allowed
    rows = patients_search("o", context=context)
    assert [r["id"] for r in rows] == [1, 3]
    assert rows[0]["email"] == hashlib.sha256(b"john.smith@example.com").hexdigest()[:16]


def test_upstream_refuses_before_our_code_runs(context) -> None:  # type: ignore[no-untyped-def]
    wrapper = SecureMcpToolWrapper(
        SecureMcpServerOptions(signing_key=KEY, allowed_tools=["other_tool"])
    )
    assert (
        wrapper.pre_execute(context, "patients_search", object_name="patients").reason
        == "tool not in allowed list"
    )
    wrapper = SecureMcpToolWrapper(SecureMcpServerOptions(signing_key=KEY))
    denied = wrapper.pre_execute(
        context, "patients_search", object_name="patients", fields=["patients.ssn"]
    )
    assert not denied.allowed and "ssn" in (denied.reason or "")
    assert (
        wrapper.pre_execute(context, "patients_search", object_name="audit_log").reason
        == "object not in allowed set"
    )


def test_execute_with_enforcement_double_hashes_and_is_otherwise_idempotent(context) -> None:  # type: ignore[no-untyped-def]
    wrapper = SecureMcpToolWrapper(SecureMcpServerOptions(signing_key=KEY))
    ours = patients_search("o", context=context)
    theirs = wrapper.execute_with_enforcement(
        context=context,
        tool_name="patients_search",
        tool_fn=patients_search,
        tool_args={"q": "o", "context": context},
        object_name="patients",
    )
    assert [r["id"] for r in theirs] == [r["id"] for r in ours]
    assert all("ssn" not in r for r in theirs)
    once = ours[0]["email"]
    assert theirs[0]["email"] == hashlib.sha256(once.encode()).hexdigest()[:16]  # hashed twice
