"""Upstream's shared fixtures, run through pushdown + post pass and post pass alone."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from django.apps import apps

from django_tolap import TolapDenied, enforce
from tests.harness.contexts import signed
from tests.harness.differential import assert_differential
from tests.harness.fixtures import all_scenarios, operator_corpus
from tests.testapp.models import CorpusRecord

pytestmark = pytest.mark.django_db

# A relational row always has every projected column, so the corpus's "missing" record
# (a field absent from the record) has no row form: absence only arises when a projection
# omits the field, which prepare_queryset prevents by always projecting filtered fields.
UNREPRESENTABLE = {"missing"}


@pytest.fixture
def corpus_rows() -> None:
    for record in operator_corpus()[0].records:
        if record["id"] in UNREPRESENTABLE:
            continue
        CorpusRecord.objects.create(
            id=record["id"],
            score=record.get("score"),
            region=record.get("region"),
            name=record.get("name"),
        )


@pytest.mark.parametrize("case", operator_corpus(), ids=lambda c: c.name)
def test_operator_corpus(corpus_rows: None, case: Any) -> None:
    rows = assert_differential(CorpusRecord.objects.order_by("id"), case.policy)
    expected = [i for i in case.expected_ids if i not in UNREPRESENTABLE]
    assert sorted(r["id"] for r in rows) == sorted(expected), case.notes


def _model_for(table: str):  # type: ignore[no-untyped-def]
    for model in apps.get_models():
        if model._meta.db_table == table:
            return model
    raise LookupError(table)


def _original(model, pk: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return dict(model.objects.filter(pk=pk).values()[0])


def _assert_mask(kind: str, original: Any, masked: Any) -> None:
    text = str(original)
    if kind == "sha256-16":
        assert masked == hashlib.sha256(text.encode()).hexdigest()[:16]
    elif kind == "redacted":
        assert masked == "[REDACTED]"
    elif kind == "is-null":
        assert masked is None
    elif kind == "full-stars":
        assert masked == "*" * len(text)
    elif kind.startswith("partial-"):
        parts = kind.split("-")
        first = int(parts[parts.index("first") + 1]) if "first" in parts else 0
        last = int(parts[parts.index("last") + 1]) if "last" in parts else 0
        char = "#" if parts[-1] == "hash" else "*"
        assert masked == text[:first] + char * (len(text) - first - last) + (
            text[len(text) - last :] if last else ""
        )
    else:  # pragma: no cover
        raise AssertionError(f"unknown mask expectation {kind}")


@pytest.mark.parametrize(
    ("file_name", "scenario"), all_scenarios(), ids=lambda x: x if isinstance(x, str) else x.name
)
def test_integration_scenario(seeded: None, file_name: str, scenario: Any) -> None:
    model = _model_for(scenario.table)
    qs = model.objects.values(*scenario.columns).order_by("id")
    expected = scenario.expected
    if not expected["pass"]:
        with pytest.raises(TolapDenied) as exc:
            enforce(qs, signed(scenario.policy))
        assert expected["errorContains"] in str(exc.value)
        return

    rows = assert_differential(qs, scenario.policy)
    assert rows == enforce(qs, signed(scenario.policy))
    if "rowCount" in expected:
        assert len(rows) == expected["rowCount"]
    if "idsEqual" in expected:
        assert sorted(r["id"] for r in rows) == sorted(expected["idsEqual"])
    if "idsIn" in expected:
        assert {r["id"] for r in rows} <= set(expected["idsIn"])
    if "regions" in expected:
        assert sorted(r["region"] for r in rows) == sorted(expected["regions"])
    if "hiddenField" in expected:
        assert all(expected["hiddenField"] not in r for r in rows)
    if "maskedField" in expected:
        field, kind = expected["maskedField"]["field"], expected["maskedField"]["mask"]
        assert rows
        for row in rows:
            _assert_mask(kind, _original(model, row["id"])[field], row[field])
    if "everyRowField" in expected:
        for rule in expected["everyRowField"]:
            assert all(r[rule["field"]] == rule["equals"] for r in rows)
