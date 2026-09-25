"""The agent tool. Everything about policy is outside this function."""

from __future__ import annotations

from typing import Any

from django_tolap import ToolContext, tolap_tool
from patients.models import Patient

SOURCE = "db:clinic:patients"


@tolap_tool(source=SOURCE)
def patients_search(q: str = "", *, tolap: ToolContext) -> list[dict[str, Any]]:
    qs = Patient.objects.order_by("id")
    if q:
        qs = qs.filter(full_name__icontains=q)
    return tolap.enforce(qs)
