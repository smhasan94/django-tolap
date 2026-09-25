from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from tests.drf_app import PatientViewSet

router = DefaultRouter()
router.register("patients", PatientViewSet, basename="patient")

urlpatterns = [path("admin/", admin.site.urls), path("api/", include(router.urls))]
