"""Identity resolvers: which groups and roles a user id holds (upstream ``IdentityResolver``)."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.utils.module_loading import import_string
from tolap_store import IdentityResolver

from django_tolap.conf import settings


class DjangoGroupsIdentityResolver:
    """Groups are the names of the user's Django ``Group``s; roles are empty.

    ``user_id`` is the user's primary key as a string, or the username. An id that
    matches no user resolves to no groups: unknown is not an error, it is "no memberships".
    """

    def get_groups(self, user_id: str) -> list[str]:
        user_model = get_user_model()
        lookup = {"pk": user_id} if user_id.isdigit() else {user_model.USERNAME_FIELD: user_id}
        user = user_model._default_manager.filter(**lookup).first()
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
