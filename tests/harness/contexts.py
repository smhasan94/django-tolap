"""Sign fixture policies into contexts the way upstream's own tests do."""

from __future__ import annotations

from datetime import timedelta

from tolap_core import EffectivePolicy, SecurityContext, build_security_context, sign_context

from tests.harness.fixtures import FIXTURE_TENANT, FIXTURE_USER

SIGNING_KEY = "test-signing-key"


def signed(
    policy: EffectivePolicy,
    *,
    key: str = SIGNING_KEY,
    ttl: timedelta = timedelta(hours=1),
) -> SecurityContext:
    return sign_context(build_security_context(FIXTURE_USER, FIXTURE_TENANT, [policy], ttl), key)
