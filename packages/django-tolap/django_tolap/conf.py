"""Access to the ``TOLAP`` settings dict with defaults.

Every key is read lazily so ``override_settings`` works in tests. ``SIGNING_KEY`` has no
default: a missing key raises ``ImproperlyConfigured`` rather than signing with an empty
string.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured

DEFAULTS: dict[str, Any] = {
    "HASH_SALT": None,
    "IDENTITY_RESOLVER": None,
    "IDENTITY": None,
    "TENANT_RESOLVER": None,
    "OBJECT_NAME": "db_table",
    "CONTEXT_TTL": 3600,
    "SOURCE_PREFIX": None,
}


class TolapSettings:
    """Attribute access over ``settings.TOLAP`` with :data:`DEFAULTS` applied."""

    @property
    def _user(self) -> dict[str, Any]:
        value = getattr(django_settings, "TOLAP", None) or {}
        if not isinstance(value, dict):
            raise ImproperlyConfigured("settings.TOLAP must be a dict")
        return value

    @property
    def SIGNING_KEY(self) -> str:
        key = self._user.get("SIGNING_KEY")
        if not isinstance(key, str) or not key:
            raise ImproperlyConfigured("settings.TOLAP['SIGNING_KEY'] is required")
        return key

    def __getattr__(self, name: str) -> Any:
        if name in DEFAULTS:
            return self._user.get(name, DEFAULTS[name])
        raise AttributeError(name)


settings = TolapSettings()
