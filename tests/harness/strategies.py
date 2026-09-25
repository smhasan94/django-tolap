"""Hypothesis strategies for policies and rows over ``tests.testapp.models.Patient``."""

from __future__ import annotations

import datetime as dt
from typing import Any

from hypothesis import strategies as st
from tolap_core import EffectivePolicy

from tests.harness.fixtures import effective_policy

REGIONS = ["us-east", "us-west", "eu-west", "US-EAST", "Us-East", "", "a", "b_c", "%"]
NAMES = ["alice smith", "ALICE JONES", "bob stone", "Bob_Stone", "m", "", "a%b", "al"]
STATUSES = ["active", "deleted", "Active", ""]
STRING_FIELDS = ("region", "full_name", "status")
INT_FIELDS = ("score",)

strings = st.sampled_from(REGIONS + NAMES + STATUSES) | st.text(max_size=6)
ints = st.integers(min_value=-5, max_value=100)
string_or_none = st.none() | strings
int_or_none = st.none() | ints
# Deliberately mismatched values exercise the decline paths.
any_value = (
    st.none()
    | strings
    | ints
    | st.booleans()
    | st.floats(allow_nan=False, allow_infinity=False, width=16)
)


def _value_for(field: str) -> st.SearchStrategy[Any]:
    typed = string_or_none if field in STRING_FIELDS else int_or_none
    return st.one_of(typed, typed, typed, any_value)


@st.composite
def row_filters(draw: st.DrawFn) -> dict[str, Any]:
    field = draw(st.sampled_from(STRING_FIELDS + INT_FIELDS))
    operator = draw(
        st.sampled_from(
            [
                "equals",
                "notEquals",
                "in",
                "notIn",
                "greaterThan",
                "greaterThanOrEqual",
                "lessThan",
                "lessThanOrEqual",
                "contains",
                "startsWith",
                "like",
                "notLike",
                "matches",
                "isNull",
                "isNotNull",
                "between",
            ]
        )
    )
    rf: dict[str, Any] = {
        "field": draw(st.sampled_from([field, f"patients.{field}", field.upper()])),
        "operator": operator,
    }
    if operator in ("in", "notIn"):
        rf["values"] = draw(st.lists(_value_for(field), max_size=4))
    elif operator == "between":
        rf["values"] = draw(st.lists(_value_for(field), min_size=0, max_size=3))
    elif operator in ("isNull", "isNotNull"):
        pass
    elif operator == "matches":
        rf["value"] = draw(st.sampled_from(["us-.*", "a.*", "(", "^b|m$"]))
    elif operator in ("like", "notLike"):
        rf["value"] = draw(st.sampled_from(["alice%", "%\\_%", "b_b%", "%", "ALICE%", "a\\%b", ""]))
    else:
        rf["value"] = draw(_value_for(field))
    return rf


FIELDS = ("id", "full_name", "email", "ssn", "date_of_birth", "region", "status", "score")


@st.composite
def policies(draw: st.DrawFn) -> EffectivePolicy:
    hidden = draw(
        st.lists(st.sampled_from(FIELDS + ("patients.ssn", "s*", "*name")), max_size=2, unique=True)
    )
    allowed = draw(
        st.none()
        | st.lists(st.sampled_from(FIELDS + ("patients.*", "id")), max_size=5, unique=True)
    )
    masked = draw(
        st.lists(
            st.builds(
                lambda f, m: {"field": f, "maskType": m},
                st.sampled_from(("email", "full_name", "region")),
                st.sampled_from(("hash", "partial", "redact", "full", "null")),
            ),
            max_size=2,
        )
    )
    filters = draw(st.lists(row_filters(), max_size=3))
    max_results = draw(st.none() | st.integers(min_value=0, max_value=7))
    bare: dict[str, Any] = {
        "permissions": {"canQuery": True},
        "objectRules": {
            "fieldRules": {
                "hiddenFields": hidden,
                **({"allowedFields": allowed} if allowed is not None else {}),
                "maskedFields": masked,
            },
            "rowFilters": filters,
        },
    }
    if max_results is not None:
        bare["limits"] = {"maxResults": max_results}
    return effective_policy(bare)


@st.composite
def patient_rows(draw: st.DrawFn) -> list[dict[str, Any]]:
    n = draw(st.integers(min_value=0, max_value=8))
    rows = []
    for i in range(n):
        rows.append(
            {
                "id": i + 1,
                "full_name": draw(st.none() | st.sampled_from(NAMES)) or "",
                "email": f"{i}@example.com",
                "ssn": f"000-00-{i:04d}",
                "date_of_birth": dt.date(1990, 1, 1) + dt.timedelta(days=i),
                "region": draw(st.none() | st.sampled_from(REGIONS)),
                "status": draw(st.sampled_from(STATUSES)),
                "score": draw(st.none() | ints),
            }
        )
    return rows
