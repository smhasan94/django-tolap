"""A plain SQL ``LIKE`` lookup for TOLAP ``like`` filters.

Django's ``contains``/``startswith`` escape the user's text; TOLAP ``like`` patterns already
use SQL wildcards (``%``, ``_``, ``\\`` escapes) so they are passed through verbatim.
Registered under ``tolap_like`` and only ever compiled on vendors whose ``LIKE`` is
case-sensitive (see :mod:`django_tolap.pushdown`).
"""

from __future__ import annotations

from typing import Any

from django.db.models import Field, Lookup


class TolapLike(Lookup):
    lookup_name = "tolap_like"

    def as_sql(self, compiler: Any, connection: Any) -> tuple[str, tuple[Any, ...]]:
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f"{lhs} LIKE {rhs} ESCAPE '\\'", (*lhs_params, *rhs_params)


def register() -> None:
    Field.register_lookup(TolapLike)
