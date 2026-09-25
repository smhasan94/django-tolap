from __future__ import annotations

import hashlib

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from django_tolap.store import DjangoPolicyStore
from tests.drf_app import PatientSerializer, PatientViewSet
from tests.testapp.models import Patient

pytestmark = pytest.mark.django_db


def policy(**extra):  # type: ignore[no-untyped-def]
    return {
        "version": "1.0",
        "name": "analyst",
        "permissions": {"canQuery": True, "readOnly": True, **extra.pop("permissions", {})},
        "objectRules": {
            "allowedObjects": ["patients"],
            "fieldRules": {
                "hiddenFields": ["patients.ssn"],
                "maskedFields": [{"field": "patients.email", "maskType": "hash"}],
            },
            "rowFilters": [{"field": "region", "operator": "equals", "value": "us-east"}],
        },
        **extra,
    }


@pytest.fixture
def alice(seeded: None):  # type: ignore[no-untyped-def]
    return get_user_model().objects.create_user(username="alice", password="x")


@pytest.fixture
def client(alice) -> APIClient:  # type: ignore[no-untyped-def]
    api = APIClient()
    api.force_authenticate(alice)
    return api


def grant(user, **extra) -> DjangoPolicyStore:  # type: ignore[no-untyped-def]
    store = DjangoPolicyStore()
    store.save_definition_json(policy(**extra))
    store.assign("analyst", user_id=str(user.pk), tenant_id="default", granted_by="a", reason="r")
    return store


def test_list_is_enforced(client: APIClient, alice) -> None:  # type: ignore[no-untyped-def]
    grant(alice)
    response = client.get("/api/patients/")
    assert response.status_code == 200
    rows = response.json()
    assert [r["id"] for r in rows] == [1, 3]
    assert "ssn" not in rows[0]
    assert rows[0]["email"] == hashlib.sha256(b"john.smith@example.com").hexdigest()[:16]


def test_list_paginates_enforced_rows(client: APIClient, alice) -> None:  # type: ignore[no-untyped-def]
    grant(alice)
    response = client.get("/api/patients/?paginate=1")
    body = response.json()
    assert body["count"] == 2 and [r["id"] for r in body["results"]] == [1]


def test_retrieve_visible_and_invisible(client: APIClient, alice) -> None:  # type: ignore[no-untyped-def]
    grant(alice)
    assert client.get("/api/patients/1/").status_code == 200
    assert client.get("/api/patients/1/").json()["region"] == "us-east"
    assert client.get("/api/patients/5/").status_code == 404  # eu-west: filtered out
    assert client.get("/api/patients/999/").status_code == 404


def test_unauthenticated_denied(seeded: None) -> None:
    response = APIClient().get("/api/patients/")
    assert response.status_code in (401, 403)


def test_user_without_policy_denied(client: APIClient) -> None:
    response = client.get("/api/patients/")
    assert response.status_code == 403 and "query not permitted" in response.json()["detail"]


def test_writes_refused_on_read_only_policy(client: APIClient, alice) -> None:  # type: ignore[no-untyped-def]
    grant(alice)
    body = {
        "full_name": "New",
        "email": "n@x",
        "ssn": "1",
        "date_of_birth": "2000-01-01",
        "region": "us-east",
        "status": "active",
    }
    assert client.post("/api/patients/", body, format="json").status_code == 403
    assert client.patch("/api/patients/1/", {"status": "x"}, format="json").status_code == 403
    assert client.delete("/api/patients/1/").status_code == 403
    assert Patient.objects.count() == 6


def test_insert_allowed_when_policy_permits(client: APIClient, alice) -> None:  # type: ignore[no-untyped-def]
    grant(alice, permissions={"readOnly": False, "canInsert": True})
    body = {
        "full_name": "New",
        "email": "n@x",
        "date_of_birth": "2000-01-01",
        "region": "us-east",
        "status": "active",
    }
    response = client.post("/api/patients/", body, format="json")
    assert response.status_code == 201, response.content
    assert Patient.objects.count() == 7
    # Writing a hidden field is refused as a whole.
    response = client.post("/api/patients/", {**body, "ssn": "1"}, format="json")
    assert response.status_code == 403 and Patient.objects.count() == 7
    # Form-encoded bodies (QueryDict) are validated as scalars, not single-item lists.
    response = client.post("/api/patients/", body)
    assert response.status_code == 201, response.content
    response = client.post("/api/patients/", {**body, "ssn": "1"})
    assert response.status_code == 403 and Patient.objects.count() == 8


def test_update_and_delete_gated_by_row_visibility(client: APIClient, alice) -> None:  # type: ignore[no-untyped-def]
    grant(alice, permissions={"readOnly": False, "canUpdate": True, "canDelete": True})
    assert (
        client.patch("/api/patients/1/", {"status": "reviewed"}, format="json").status_code == 200
    )
    response = client.patch("/api/patients/5/", {"status": "reviewed"}, format="json")
    assert response.status_code == 403 and "target row not permitted" in response.json()["detail"]
    assert client.delete("/api/patients/5/").status_code == 403
    assert client.delete("/api/patients/1/").status_code == 204
    assert Patient.objects.filter(id=5).exists() and not Patient.objects.filter(id=1).exists()


def test_serializer_drops_hidden_fields_for_view(client: APIClient, alice, rf) -> None:  # type: ignore[no-untyped-def]
    grant(alice)
    from rest_framework.request import Request

    view = PatientViewSet()
    view.request = Request(rf.get("/api/patients/"))
    view.request.user = alice
    view.format_kwarg = None
    assert "ssn" not in PatientSerializer(context={"view": view}).fields
    assert "ssn" in PatientSerializer().fields  # no view, no policy: unchanged


def test_tenant_resolver_setting(client: APIClient, alice, settings) -> None:  # type: ignore[no-untyped-def]
    store = DjangoPolicyStore()
    store.save_definition_json(policy())
    store.assign("analyst", user_id=str(alice.pk), tenant_id="acme", granted_by="a", reason="r")
    assert client.get("/api/patients/").status_code == 403
    settings.TOLAP = {**settings.TOLAP, "TENANT_RESOLVER": "tests.test_drf.tenant_from_header"}
    assert client.get("/api/patients/", HTTP_X_TENANT="acme").status_code == 200


def tenant_from_header(request) -> str:  # type: ignore[no-untyped-def]
    return str(request.headers.get("X-Tenant", "default"))
