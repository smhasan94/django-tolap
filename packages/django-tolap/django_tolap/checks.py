"""Django system checks for the ``TOLAP`` settings."""

from __future__ import annotations

from typing import Any

from django.core.checks import CheckMessage, Error, Tags, register
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from django_tolap.conf import settings

E001 = "django_tolap.E001"
E002 = "django_tolap.E002"
E003 = "django_tolap.E003"
E004 = "django_tolap.E004"
E005 = "django_tolap.E005"


@register(Tags.security)
def check_tolap_settings(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    messages: list[CheckMessage] = []

    try:
        _ = settings.SIGNING_KEY
    except ImproperlyConfigured as exc:
        messages.append(Error(str(exc), hint="Set TOLAP = {'SIGNING_KEY': ...}", id=E001))

    resolver = settings.IDENTITY_RESOLVER
    if resolver is not None:
        try:
            import_string(resolver)
        except (ImportError, AttributeError, ValueError) as exc:
            messages.append(
                Error(
                    f"TOLAP['IDENTITY_RESOLVER'] {resolver!r} cannot be imported: {exc}",
                    id=E002,
                )
            )

    identity = settings.IDENTITY
    if identity is not None:
        try:
            import_string(identity)
        except (ImportError, AttributeError, ValueError) as exc:
            messages.append(
                Error(f"TOLAP['IDENTITY'] {identity!r} cannot be imported: {exc}", id=E004)
            )

    tenant_resolver = settings.TENANT_RESOLVER
    if tenant_resolver is not None:
        try:
            import_string(tenant_resolver)
        except (ImportError, AttributeError, ValueError) as exc:
            messages.append(
                Error(
                    f"TOLAP['TENANT_RESOLVER'] {tenant_resolver!r} cannot be imported: {exc}",
                    id=E005,
                )
            )

    object_name = settings.OBJECT_NAME
    if object_name != "db_table":
        try:
            target = import_string(object_name) if isinstance(object_name, str) else object_name
        except (ImportError, AttributeError, ValueError) as exc:
            messages.append(Error(f"TOLAP['OBJECT_NAME'] cannot be imported: {exc}", id=E003))
        else:
            if not callable(target):
                messages.append(
                    Error(
                        "TOLAP['OBJECT_NAME'] must be 'db_table' or a callable (model) -> str",
                        id=E003,
                    )
                )

    return messages
