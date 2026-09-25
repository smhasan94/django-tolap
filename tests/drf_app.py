from __future__ import annotations

from rest_framework import serializers, viewsets
from rest_framework.pagination import PageNumberPagination

from django_tolap.drf import TolapSerializerMixin, TolapViewSetMixin
from tests.testapp.models import Patient


class PatientSerializer(TolapSerializerMixin, serializers.ModelSerializer):  # type: ignore[type-arg]
    class Meta:
        model = Patient
        fields = ["id", "full_name", "email", "ssn", "date_of_birth", "region", "status", "score"]


class OnePerPage(PageNumberPagination):
    page_size = 1


class PatientViewSet(TolapViewSetMixin, viewsets.ModelViewSet):  # type: ignore[type-arg]
    queryset = Patient.objects.order_by("id")
    serializer_class = PatientSerializer
    tolap_source = "db:testapp:patients"

    @property
    def paginator(self):  # type: ignore[no-untyped-def]
        if self.request.query_params.get("paginate"):
            if not hasattr(self, "_paginator"):
                self._paginator = OnePerPage()
            return self._paginator
        return None
