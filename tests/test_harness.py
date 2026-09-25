"""The fixture loader and seed must reflect upstream verbatim."""

from __future__ import annotations

import json

import jsonschema
import pytest

from tests.harness.fixtures import (
    INTEGRATION_FILES,
    UPSTREAM,
    all_scenarios,
    envelope,
    integration_scenarios,
    operator_corpus,
)
from tests.harness.seed import PATIENTS, upstream_row_counts
from tests.testapp.models import Patient


def test_source_record_names_commit() -> None:
    text = (UPSTREAM / "SOURCE").read_text()
    assert "commit " in text and "awslabs/tolap" in text


def test_operator_corpus_covers_every_schema_operator() -> None:
    schema = json.loads((UPSTREAM / "schema" / "policy-definition.schema.json").read_text())
    operators = set(schema["$defs"]["filterRule"]["properties"]["operator"]["enum"])
    used = {c.bare_policy["objectRules"]["rowFilters"][0]["operator"] for c in operator_corpus()}
    assert operators <= used


def test_operator_corpus_records_include_null_and_missing() -> None:
    corpus = operator_corpus()
    ids = {r["id"] for r in corpus[0].records}
    assert {"nullish", "missing"} <= ids


@pytest.mark.parametrize("file_name", INTEGRATION_FILES)
def test_integration_scenarios_load(file_name: str) -> None:
    scenarios = integration_scenarios(file_name)
    assert scenarios
    for s in scenarios:
        assert s.table and s.columns and "pass" in s.expected


def test_envelope_validates_against_effective_policy_schema() -> None:
    schema = json.loads((UPSTREAM / "schema" / "effective-policy.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    for _, scenario in all_scenarios():
        validator.validate(envelope(scenario.bare_policy))
    for case in operator_corpus():
        validator.validate(envelope(case.bare_policy))


def test_seed_matches_upstream_row_counts(seeded: None) -> None:
    counts = upstream_row_counts()
    assert counts["patients"] == len(PATIENTS) == Patient.objects.count()
    assert Patient.objects.get(id=6).status == "deleted"
    assert counts["encounters"] == 6 and counts["diagnoses"] == 5
