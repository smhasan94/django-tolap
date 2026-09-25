"""drf-spectacular schema generation for ``TolapViewSetMixin`` views.

A public schema (no caller) documents the whole serializer and every method. A schema
served to an authenticated caller (``SERVE_PUBLIC = False``) is that caller's view of the
API: hidden fields are absent, masked fields are annotated, write methods the policy refuses
are absent, and an object the policy denies has no operations at all.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from drf_spectacular.generators import SchemaGenerator
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from tests.test_drf import grant

pytestmark = pytest.mark.django_db

LIST = "/api/patients/"
DETAIL = "/api/patients/{id}/"


@pytest.fixture
def alice(seeded: None):  # type: ignore[no-untyped-def]
    return get_user_model().objects.create_user(username="alice", password="x")


def schema_for(user=None) -> dict:  # type: ignore[no-untyped-def, type-arg]
    if user is None:
        return SchemaGenerator().get_schema(request=None, public=True)
    request = APIRequestFactory().get("/api/schema/")
    force_authenticate(request, user=user)
    return SchemaGenerator().get_schema(request=Request(request), public=False)


def patient_properties(schema: dict) -> dict:  # type: ignore[type-arg]
    return schema["components"]["schemas"]["Patient"]["properties"]


def test_public_schema_documents_every_field_and_method(seeded: None) -> None:
    schema = schema_for()
    assert set(schema["paths"][LIST]) == {"get", "post"}
    assert set(schema["paths"][DETAIL]) == {"get", "put", "patch", "delete"}
    assert "ssn" in patient_properties(schema)
    assert "x-tolap-mask" not in patient_properties(schema)["email"]


def test_operations_name_the_tolap_source(seeded: None) -> None:
    operation = schema_for()["paths"][LIST]["get"]
    assert operation["x-tolap-source"] == "db:testapp:patients"
    assert "db:testapp:patients" in operation["description"]


def test_caller_schema_hides_fields_annotates_masks_drops_writes(alice) -> None:  # type: ignore[no-untyped-def]
    grant(alice)
    schema = schema_for(alice)
    assert set(schema["paths"][LIST]) == {"get"}
    assert set(schema["paths"][DETAIL]) == {"get"}
    properties = patient_properties(schema)
    assert "ssn" not in properties
    assert properties["email"]["x-tolap-mask"] == "hash"
    assert "x-tolap-mask" not in properties["full_name"]


def test_caller_schema_keeps_permitted_writes(alice) -> None:  # type: ignore[no-untyped-def]
    grant(alice, permissions={"readOnly": False, "canInsert": True, "canUpdate": True})
    schema = schema_for(alice)
    assert set(schema["paths"][LIST]) == {"get", "post"}
    # Row filters make the target row unverifiable at schema time; that is not a refusal.
    assert set(schema["paths"][DETAIL]) == {"get", "put", "patch"}


def test_caller_without_policy_sees_no_patient_operations(alice) -> None:  # type: ignore[no-untyped-def]
    schema = schema_for(alice)
    assert LIST not in schema["paths"] and DETAIL not in schema["paths"]
    assert "Patient" not in schema["components"].get("schemas", {})


def test_schema_view_serves_the_caller_view(alice, settings) -> None:  # type: ignore[no-untyped-def]
    grant(alice)
    settings.SPECTACULAR_SETTINGS = {"SERVE_PUBLIC": False}
    client = APIClient()
    client.force_authenticate(alice)
    response = client.get("/api/schema/?format=json")
    assert response.status_code == 200
    schema = response.json()
    assert set(schema["paths"][LIST]) == {"get"}
    assert "ssn" not in patient_properties(schema)


def test_viewset_mixin_uses_tolap_auto_schema() -> None:
    from django_tolap.spectacular import TolapAutoSchema
    from tests.drf_app import PatientViewSet

    assert isinstance(
        PatientViewSet.__dict__.get("schema") or PatientViewSet().schema, TolapAutoSchema
    )


def test_viewset_mixin_without_drf_spectacular_leaves_schema_alone(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import importlib
    import sys

    import django_tolap.drf as drf

    monkeypatch.setitem(sys.modules, "django_tolap.spectacular", None)  # import raises
    try:
        assert "schema" not in importlib.reload(drf).TolapViewSetMixin.__dict__
    finally:
        monkeypatch.undo()
        importlib.reload(drf)
    assert "schema" in drf.TolapViewSetMixin.__dict__


def test_auto_schema_on_a_view_without_tolap_source_changes_nothing(rf) -> None:  # type: ignore[no-untyped-def]
    from rest_framework import serializers, viewsets

    from django_tolap.spectacular import TolapAutoSchema

    class Plain(serializers.Serializer):  # type: ignore[type-arg]
        name = serializers.CharField()

    class PlainViewSet(viewsets.ViewSet):
        serializer_class = Plain

    view = PlainViewSet()
    view.request = Request(rf.get("/"))
    view.action = "list"
    schema = TolapAutoSchema()
    schema.view = view
    schema.method = "GET"
    assert schema._tolap_policy() is None
    assert schema.get_extensions() == {}
    assert "TOLAP" not in schema.get_description()
    assert schema._tolap_mask(Plain().fields["name"]) is None


def test_mask_annotation_ignores_fields_that_are_not_model_columns(alice, rf) -> None:  # type: ignore[no-untyped-def]
    from rest_framework import serializers

    from django_tolap.spectacular import TolapAutoSchema
    from tests.drf_app import PatientViewSet

    grant(alice)
    view = PatientViewSet()
    request = rf.get("/api/patients/")
    force_authenticate(request, user=alice)
    view.request = Request(request)
    schema = TolapAutoSchema()
    schema.view = view
    assert schema._tolap_mask(serializers.CharField()) is None  # no field_name: not a column
