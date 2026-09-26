"""The same policies over a REST endpoint an agent (or anyone) can call.

``TolapViewSetMixin`` resolves the caller's policy once per request, returns enforced
rows from ``list`` and ``retrieve``, and refuses writes the policy does not permit.
``TolapSerializerMixin`` keeps the OpenAPI schema honest: hidden fields are absent from it.
With drf-spectacular installed, ``/api/schema/`` served to an authenticated caller is that
caller's view of the API (masked fields carry ``x-tolap-mask``, refused methods are gone).
"""

from __future__ import annotations

from rest_framework import serializers, viewsets
from rest_framework.request import Request

from django_tolap.drf import TolapSerializerMixin, TolapViewSetMixin
from patients.models import Patient
from patients.tools import SOURCE


class PatientSerializer(TolapSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = "__all__"


class PatientViewSet(TolapViewSetMixin, viewsets.ModelViewSet):
    """``GET /api/patients/?q=jo`` and ``GET /api/patients/<id>/`` under the caller's policy."""

    queryset = Patient.objects.order_by("id")
    serializer_class = PatientSerializer
    tolap_source = SOURCE

    def get_tolap_identity(self, request: Request) -> tuple[str | None, str | None]:
        # The seed assigns policies by username in tenant "clinic"; the default identity is
        # the user's primary key in tenant "default". Override to match your assignments.
        user = request.user
        if not user.is_authenticated:
            return None, None
        return user.get_username(), "clinic"

    def get_queryset(self):  # type: ignore[no-untyped-def]
        qs = super().get_queryset()
        q = self.request.query_params.get("q") if self.request else None
        return qs.filter(full_name__icontains=q) if q else qs
