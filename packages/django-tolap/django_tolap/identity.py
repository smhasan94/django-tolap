"""Identity resolvers: which groups and roles a user id holds (upstream ``IdentityResolver``)."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.utils.module_loading import import_string
from tolap_store import IdentityResolver

from django_tolap.conf import settings


class DjangoGroupsIdentityResolver:
    """Groups are the names of the user's Django ``Group``s; roles are empty.

    ``user_id`` is matched against exactly one field, ``lookup``: the primary key by default
    (what :mod:`django_tolap.tool` and the DRF mixin send), or ``"username"`` for the
    ``USERNAME_FIELD``. Never both: an all-digit username must not resolve to another
    user's primary key. An id that matches no user resolves to no groups.
    """

    def __init__(self, lookup: str = "pk") -> None:
        if lookup not in ("pk", "username"):
            raise ValueError("lookup must be 'pk' or 'username'")
        self.lookup = lookup

    def get_groups(self, user_id: str) -> list[str]:
        user_model = get_user_model()
        if self.lookup == "pk":
            if not user_id.isdigit():
                return []
            user = user_model._default_manager.filter(pk=int(user_id)).first()
        else:
            user = user_model._default_manager.filter(
                **{user_model.USERNAME_FIELD: user_id}
            ).first()
        if user is None:
            return []
        return [str(name) for name in user.groups.values_list("name", flat=True)]

    def get_roles(self, user_id: str) -> list[str]:
        return []


def load_identity_resolver() -> IdentityResolver:
    path = settings.IDENTITY_RESOLVER
    if path is None:
        return DjangoGroupsIdentityResolver()
    target: Any = import_string(path)
    resolver: IdentityResolver = target() if isinstance(target, type) else target
    return resolver
