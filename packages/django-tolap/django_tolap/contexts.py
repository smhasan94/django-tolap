"""Issue signed contexts from the store, or accept ones issued elsewhere."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from tolap_core import (
    ReplayGuard,
    SecurityContext,
    build_security_context,
    deserialize_context,
    serialize_context,
    sign_context,
)

from django_tolap.conf import settings

if TYPE_CHECKING:
    from django_tolap.store import DjangoPolicyStore


def issue_context(
    user_id: str,
    tenant_id: str,
    source: str,
    *,
    store: DjangoPolicyStore | None = None,
    ttl: timedelta | int | None = None,
    signing_key: str | None = None,
) -> SecurityContext:
    """Resolve (upstream merge) and sign one context for one source."""
    if store is None:
        # Imported here: models cannot be imported until the app registry is ready.
        from django_tolap.store import DjangoPolicyStore

        store = DjangoPolicyStore()
    policy = store.resolve_policy(user_id, tenant_id, source)
    lifetime = ttl if ttl is not None else settings.CONTEXT_TTL
    if isinstance(lifetime, int):
        lifetime = timedelta(seconds=lifetime)
    context = build_security_context(user_id, tenant_id, [policy], lifetime)
    return sign_context(context, signing_key or settings.SIGNING_KEY)


def serialize(context: SecurityContext) -> str:
    """Base64 JSON for transport (upstream ``serialize_context``)."""
    wire: str = serialize_context(context)
    return wire


def accept_context(
    serialized: str,
    *,
    signing_key: str | None = None,
    replay_guard: ReplayGuard | None = None,
) -> SecurityContext:
    """Deserialize and validate a context issued elsewhere (upstream ``deserialize_context``).

    Raises ``ValueError`` on a bad signature, expiry, or replay, as upstream does.
    """
    return deserialize_context(serialized, signing_key or settings.SIGNING_KEY, replay_guard)
