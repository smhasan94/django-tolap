"""``enforce()``: verify, pre-check, push down, execute, post-pass. The post pass always runs."""

from __future__ import annotations

from typing import Any

from tolap_core import SecurityContext, validate_context, validate_expiry

from sqlalchemy_tolap.exceptions import TolapDenied
from sqlalchemy_tolap.pushdown import EnforcementMode, Preparation, finalize, prepare_select


def validate(context: SecurityContext, signing_key: str) -> None:
    if not validate_context(context, signing_key):
        raise TolapDenied("invalid signature")
    expiry_reason = validate_expiry(context)
    if expiry_reason is not None:
        raise TolapDenied(expiry_reason)


def dialect_name(executor: Any) -> str:
    """The dialect of a Session, Connection or Engine."""
    if hasattr(executor, "get_bind"):
        return str(executor.get_bind().dialect.name)
    if hasattr(executor, "dialect"):
        return str(executor.dialect.name)
    if hasattr(executor, "engine"):
        return str(executor.engine.dialect.name)
    raise TypeError("executor must be a Session, Connection or Engine")


def enforce(
    stmt: Any,
    context: SecurityContext,
    executor: Any,
    *,
    signing_key: str,
    hash_salt: str | bytes | None = None,
    mode: EnforcementMode | str = EnforcementMode.rewrite_and_post,
) -> list[dict[str, Any]]:
    """Rows of ``stmt`` the signed ``context``'s policy allows, as dicts.

    ``executor`` is a Session or Connection (anything with ``execute``); the dialect it is
    bound to decides which filters can be pushed. Raises :class:`TolapDenied` on refusal.
    """
    validate(context, signing_key)
    policy = context.effective_policy
    prep: Preparation = prepare_select(stmt, policy, dialect=dialect_name(executor), mode=mode)
    if not prep.allowed or prep.statement is None:
        raise TolapDenied(prep.denial_reason or "access denied")
    rows = [dict(row) for row in executor.execute(prep.statement).mappings().all()]
    return finalize(prep, rows, policy, hash_salt)
