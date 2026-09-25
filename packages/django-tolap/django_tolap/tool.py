"""The tool-author surface: one decorator, one context manager, one small object.

Identity (``user_id``, ``tenant_id``) is the integrator's to establish (upstream trust
boundary TB1). It reaches the decorator, in order of precedence, as explicit keyword
arguments on the call, from an ``identity`` callable given to the decorator, or from the
``TOLAP["IDENTITY"]`` setting (a dotted path to such a callable). A caller may instead pass
a signed ``context=`` produced elsewhere, which is verified and used as-is. With none of
these the call is denied.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, NoReturn

from django.utils.module_loading import import_string
from tolap_core import EffectivePolicy, SecurityContext

from django_tolap.conf import settings
from django_tolap.contexts import issue_context
from django_tolap.enforce import enforce, validate
from django_tolap.exceptions import TolapDenied
from django_tolap.pushdown import EnforcementMode

Identity = Callable[..., tuple[str, str]]

IDENTITY_MISSING = "identity not established"


@dataclass(frozen=True)
class ToolContext:
    """What a tool body gets: the verified context and the enforcement call."""

    context: SecurityContext
    source: str

    @property
    def policy(self) -> EffectivePolicy:
        return self.context.effective_policy

    def enforce(
        self, queryset: Any, *, mode: EnforcementMode | str = EnforcementMode.rewrite_and_post
    ) -> list[dict[str, Any]]:
        return enforce(queryset, self.context, mode=mode)

    def deny(self, reason: str) -> NoReturn:
        raise TolapDenied(reason)


@contextmanager
def tolap_context(
    user_id: str | None,
    tenant_id: str | None,
    source: str,
    *,
    context: SecurityContext | None = None,
    store: Any = None,
) -> Iterator[ToolContext]:
    """Resolve and sign (or verify a supplied context), then yield a :class:`ToolContext`."""
    if context is None:
        if not user_id or not tenant_id:
            raise TolapDenied(IDENTITY_MISSING)
        context = issue_context(user_id, tenant_id, source, store=store)
    validate(context)
    yield ToolContext(context=context, source=source)


def _settings_identity() -> Identity | None:
    path = settings.IDENTITY
    if path is None:
        return None
    target: Any = import_string(path)
    return target  # type: ignore[no-any-return]


def _establish(kwargs: dict[str, Any], identity: Identity | None) -> tuple[str | None, str | None]:
    user_id = kwargs.pop("user_id", None)
    tenant_id = kwargs.pop("tenant_id", None)
    if user_id and tenant_id:
        return str(user_id), str(tenant_id)
    resolver = identity or _settings_identity()
    if resolver is None:
        return None, None
    resolved = resolver(**kwargs)
    return (str(resolved[0]), str(resolved[1])) if resolved else (None, None)


def tolap_tool(
    source: str,
    *,
    identity: Identity | None = None,
    param: str = "tolap",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a tool function so it receives a :class:`ToolContext` as ``param``.

    ``source`` is the TOLAP source connection id the tool reads (``db:<ns>:<name>``); one
    context governs one source. ``identity(**kwargs) -> (user_id, tenant_id)`` derives the
    caller from the tool's own arguments when they are not passed explicitly.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            supplied: SecurityContext | None = kwargs.pop("context", None)
            user_id, tenant_id = (None, None) if supplied else _establish(kwargs, identity)
            with tolap_context(user_id, tenant_id, source, context=supplied) as tool:
                return fn(*args, **{**kwargs, param: tool})

        return wrapper

    return decorator
