"""``enforce()``: the one public entry point that executes a QuerySet under a policy.

Order (never reordered, never partially applied):

1. signature (``validate_context``), then expiry (``validate_expiry``) -- upstream order:
   a tampered context reports a signature failure rather than revealing its expiry
2. pre-execution checks and pushdown (:func:`~django_tolap.pushdown.prepare_queryset`)
3. execute
4. ``apply_result_pipeline`` -- the security boundary, upstream's own function, always

Pushdown reduces what the database produces. It is not what makes the result safe.
"""

from __future__ import annotations

from typing import Any

from tolap_core import SecurityContext, validate_context, validate_expiry

from django_tolap.conf import settings
from django_tolap.exceptions import TolapDenied
from django_tolap.pushdown import EnforcementMode, Preparation, finalize, prepare_queryset


def validate(context: SecurityContext, *, signing_key: str | None = None) -> None:
    """Refuse a context whose signature or expiry fails, signature first."""
    key = signing_key if signing_key is not None else settings.SIGNING_KEY
    if not validate_context(context, key):
        raise TolapDenied("invalid signature")
    expiry_reason = validate_expiry(context)
    if expiry_reason is not None:
        raise TolapDenied(expiry_reason)


def enforce(
    queryset: Any,
    context: SecurityContext,
    *,
    hash_salt: str | bytes | None = None,
    signing_key: str | None = None,
    mode: EnforcementMode | str = EnforcementMode.rewrite_and_post,
) -> list[dict[str, Any]]:
    """Return the rows of ``queryset`` the signed ``context``'s policy allows, as dicts.

    ``mode`` mirrors upstream's ``SqlEnforcementMode``: ``rewrite_and_post`` (default) pushes
    filters, limit and projection into the QuerySet; ``post_only`` leaves filters and limit to
    the post pass. Both return the same rows.

    Raises :class:`TolapDenied` with the reason when the context, the object, a referenced
    field, or the QuerySet's shape is refused. Never returns model instances: the post pass
    only accepts records, and a deferred attribute on an instance would be a way around it.
    """
    validate(context, signing_key=signing_key)
    policy = context.effective_policy
    prep: Preparation = prepare_queryset(queryset, policy, mode=mode)
    if not prep.allowed or prep.queryset is None:
        raise TolapDenied(prep.denial_reason or "access denied")
    rows = [dict(row) for row in prep.queryset]
    salt = hash_salt if hash_salt is not None else settings.HASH_SALT
    return finalize(prep, rows, policy, salt)
