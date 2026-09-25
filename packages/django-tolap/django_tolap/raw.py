"""``enforce_sql`` / ``enforce_raw``: the raw SQL paths (cursor and ``Manager.raw()``).

Upstream's ``prepare_sql_query`` rewrites the SQL text. This module decides *what* it may
push: the same vendor rules as the QuerySet path (:func:`~django_tolap.pushdown.compile_filter`),
applied by handing upstream a reduced policy. The post pass runs with the full policy and is,
as everywhere, the security boundary.

Only single-table ``SELECT`` statements are rewritten. Upstream injects unqualified column
names, which bind to the wrong table across a join, so joins, comma ``FROM`` lists, subqueries
and set operations get the pre-execution checks and the post pass but no pushdown.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from django.db import connections
from django.db.models import Model
from django.db.models.query import RawQuerySet
from tolap_core import (
    EffectivePolicy,
    RowFilter,
    SecurityContext,
    SqlDialect,
    apply_result_pipeline,
)
from tolap_core.sql_rewriter import extract_table_name, prepare_sql_query

from django_tolap.conf import settings
from django_tolap.enforce import validate
from django_tolap.exceptions import TolapDenied
from django_tolap.objects import object_name
from django_tolap.pushdown import EnforcementMode, compile_filter, resolve_field

DIALECTS: dict[str, SqlDialect] = {
    "postgresql": SqlDialect.postgres,
    "mysql": SqlDialect.mysql,
    "sqlite": SqlDialect.ansi,
}

_SELECT = re.compile(r"^\s*select\b", re.IGNORECASE)
_MULTI_TABLE = re.compile(
    r"\bjoin\b|\bunion\b|\bintersect\b|\bexcept\b|\(\s*select\b|\bfrom\s+[\w.\"`]+\s*,",
    re.IGNORECASE,
)
_PLACEHOLDER = re.compile(r"%s|%\(\w+\)s")


@dataclass
class RawPreparation:
    """Mirrors :class:`~django_tolap.pushdown.Preparation` for a SQL string.

    ``sql`` and ``params`` are what to execute when ``allowed``. **The post-execution
    pipeline still MUST run on the rows they return.**
    """

    allowed: bool
    sql: str | None
    params: Any = None
    denial_reason: str | None = None
    rewritten: bool = False
    pushed_filters: list[RowFilter] = dataclass_field(default_factory=list)
    unpushable_filters: list[RowFilter] = dataclass_field(default_factory=list)
    max_results: int | None = None
    mode: EnforcementMode = EnforcementMode.rewrite_and_post

    @property
    def fully_pushed_down(self) -> bool:
        return self.allowed and not self.unpushable_filters

    @classmethod
    def denied(cls, reason: str) -> RawPreparation:
        return cls(allowed=False, sql=None, denial_reason=reason)


def _as_column(rf: RowFilter, model: type[Model]) -> RowFilter:
    """``rf`` with its field spelled as the model's database column.

    Our rules resolve fields case-insensitively; upstream quotes the name verbatim, and
    PostgreSQL would then look for ``"REGION"``.
    """
    field = resolve_field(rf, model)
    return dataclasses.replace(rf, field=field.column) if field is not None else rf


def _reduced(
    policy: EffectivePolicy, pushable: list[RowFilter], push_limit: bool, model: type[Model]
) -> EffectivePolicy:
    """A copy of ``policy`` carrying only ``pushable`` row filters and, if asked, the limit."""
    rules = policy.object_rules
    if rules is not None:
        rules = dataclasses.replace(rules, row_filters=[_as_column(rf, model) for rf in pushable])
    return dataclasses.replace(
        policy, object_rules=rules, limits=policy.limits if push_limit else None
    )


def _key(rf: RowFilter) -> tuple[Any, ...]:
    values = tuple(rf.values) if rf.values is not None else None
    return (rf.field, rf.operator, rf.value, values)


def _normalise(table: str | None) -> str:
    return (table or "").strip('"`[]').split(".")[-1].lower()


def escape_outside_placeholders(sql: str) -> str:
    """Double every ``%`` that is not part of a ``%s`` / ``%(name)s`` placeholder."""
    out: list[str] = []
    last = 0
    for match in _PLACEHOLDER.finditer(sql):
        out.append(sql[last : match.start()].replace("%", "%%"))
        out.append(match.group(0))
        last = match.end()
    out.append(sql[last:].replace("%", "%%"))
    return "".join(out)


def prepare_sql(
    sql: str,
    params: Any,
    policy: EffectivePolicy,
    *,
    model: type[Model],
    vendor: str,
    mode: EnforcementMode | str = EnforcementMode.rewrite_and_post,
) -> RawPreparation:
    """Pre-execution checks and faithful pushdown for a SQL string against ``model``."""
    mode = EnforcementMode(mode)
    if not _SELECT.match(sql or ""):
        return RawPreparation.denied("only SELECT statements are enforced")
    name = object_name(model)
    read = _normalise(extract_table_name(sql))
    if read != name.lower():
        return RawPreparation.denied(
            f"statement reads {read or 'an unknown table'!r}, not {name!r}"
        )

    rules = policy.object_rules
    filters = list(rules.row_filters or []) if rules is not None else []
    pushable = [rf for rf in filters if compile_filter(rf, model, vendor) is not None]
    dialect = DIALECTS.get(vendor)
    push = (
        mode is EnforcementMode.rewrite_and_post
        and dialect is not None
        and not _MULTI_TABLE.search(sql)
    )
    if not push:
        pushable = []
    push_limit = push and len(pushable) == len(filters)

    upstream = prepare_sql_query(
        sql,
        _reduced(policy, pushable, push_limit, model),
        object_name=name,
        dialect=dialect or SqlDialect.ansi,
    )
    if not upstream.allowed:
        return RawPreparation.denied(upstream.denial_reason or "access denied")
    if upstream.unpushable_filters and push_limit:
        # Upstream declined something our rules accepted; the limit must not run ahead of an
        # unpushed filter (decision 2026-09-25), so rewrite again without it.
        declined = {_key(rf) for rf in upstream.unpushable_filters}
        pushable = [rf for rf in pushable if _key(_as_column(rf, model)) not in declined]
        push_limit = False
        upstream = prepare_sql_query(
            sql, _reduced(policy, pushable, False, model), object_name=name, dialect=dialect
        )
    query = upstream.query
    if len(_PLACEHOLDER.findall(query)) != len(_PLACEHOLDER.findall(sql)):
        # A pushed literal looked like a placeholder; do not risk a mis-bound parameter.
        pushable, push_limit = [], False
        query = prepare_sql_query(
            sql,
            _reduced(policy, [], False, model),
            object_name=name,
            dialect=dialect or SqlDialect.ansi,
        ).query
    if params is not None and query != sql:
        query = escape_outside_placeholders(query)

    declined = {_key(rf) for rf in upstream.unpushable_filters}
    pushed = [rf for rf in pushable if _key(_as_column(rf, model)) not in declined]
    unpushable = [rf for rf in filters if rf not in pushed]
    limit = policy.limits.max_results if policy.limits else None
    return RawPreparation(
        allowed=True,
        sql=query,
        params=params,
        rewritten=query != sql,
        pushed_filters=pushed,
        unpushable_filters=unpushable,
        max_results=limit if push_limit else None,
        mode=mode,
    )


def enforce_sql(
    sql: str,
    params: Any = None,
    context: SecurityContext | None = None,
    *,
    model: type[Model],
    using: str | None = None,
    hash_salt: str | bytes | None = None,
    signing_key: str | None = None,
    mode: EnforcementMode | str = EnforcementMode.rewrite_and_post,
) -> list[dict[str, Any]]:
    """Execute ``sql`` under the signed ``context``'s policy; rows as dicts.

    ``model`` names the table the statement reads (its ``db_table`` is the TOLAP object) and
    supplies the column types the pushdown rules need. Same order as :func:`enforce`:
    signature, expiry, checks and pushdown, execute, ``apply_result_pipeline``.
    """
    if context is None:
        raise TypeError("enforce_sql() missing required argument: 'context'")
    validate(context, signing_key=signing_key)
    policy = context.effective_policy
    connection = connections[using or "default"]
    prep = prepare_sql(sql, params, policy, model=model, vendor=connection.vendor, mode=mode)
    if not prep.allowed or prep.sql is None:
        raise TolapDenied(prep.denial_reason or "access denied")
    with connection.cursor() as cursor:
        if prep.params is None:
            cursor.execute(prep.sql)
        else:
            cursor.execute(prep.sql, prep.params)
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, values, strict=True)) for values in cursor.fetchall()]
    salt = hash_salt if hash_salt is not None else settings.HASH_SALT
    result: list[dict[str, Any]] = apply_result_pipeline(rows, policy, salt)
    return result


def enforce_raw(
    queryset: RawQuerySet[Any],
    context: SecurityContext,
    *,
    hash_salt: str | bytes | None = None,
    signing_key: str | None = None,
    mode: EnforcementMode | str = EnforcementMode.rewrite_and_post,
) -> list[dict[str, Any]]:
    """:func:`enforce_sql` for a ``Manager.raw()`` QuerySet. Never instantiates models."""
    model = queryset.model
    if model is None:
        raise TolapDenied("raw QuerySet has no model")
    return enforce_sql(
        str(queryset.raw_query),
        queryset.params,
        context,
        model=model,
        using=queryset.db,
        hash_salt=hash_salt,
        signing_key=signing_key,
        mode=mode,
    )
