"""Map Django models to TOLAP object names and source connection ids."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.db.models import Model
from django.utils.module_loading import import_string

from django_tolap.conf import settings


def _object_name_callable() -> Callable[[type[Model]], str] | None:
    configured = settings.OBJECT_NAME
    if configured == "db_table":
        return None
    target: Any = import_string(configured) if isinstance(configured, str) else configured
    if not callable(target):
        raise TypeError("TOLAP['OBJECT_NAME'] must be 'db_table' or a callable")
    return target  # type: ignore[no-any-return]


def object_name(model: type[Model]) -> str:
    """The TOLAP object name a policy uses for this model (default: ``db_table``)."""
    fn = _object_name_callable()
    if fn is None:
        return str(model._meta.db_table)
    return fn(model)


def source_id(model: type[Model]) -> str:
    """``db:<SOURCE_PREFIX or app_label>:<object name>`` (connector spec section 1)."""
    prefix = settings.SOURCE_PREFIX or model._meta.app_label
    return f"db:{prefix}:{object_name(model)}"
