from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView
from patients.api import PatientViewSet
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register("patients", PatientViewSet, basename="patient")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/", include(router.urls)),
]
