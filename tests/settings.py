"""Test settings. DATABASE_URL selects the vendor; defaults to in-memory SQLite."""

import os

import dj_database_url

SECRET_KEY = "test-secret-key"
DEBUG = False
USE_TZ = True

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django_tolap",
    "tests.testapp",
]

DATABASES = {
    "default": dj_database_url.config(default="sqlite://:memory:"),
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TOLAP = {
    "SIGNING_KEY": os.environ.get("TOLAP_SIGNING_KEY", "test-signing-key"),
}
