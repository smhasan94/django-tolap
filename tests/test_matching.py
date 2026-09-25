"""Parity with upstream's private matchers, on a corpus that covers every spec rule."""

from __future__ import annotations

import itertools

import pytest
from tolap_core.enforcement import _field_name_matches, _pattern_matches

from django_tolap.matching import field_matches, is_pattern, object_matches

RULES = [
    "ssn",
    "patients.ssn",
    "PATIENTS.SSN",
    "patients.*",
    "*",
    "*.ssn",
    "s?n",
    "log[abc]",
    "report?",
    "encounters.status",
    "date_of_birth",
]
KEYS = [
    "ssn",
    "patients.ssn",
    "Patients.SSN",
    "encounters.ssn",
    "status",
    "encounters.status",
    "loga",
    "log[abc]",
    "reports",
    "report",
    "date_of_birth",
    "nested.patients.ssn",
]


@pytest.mark.parametrize(("rule", "key"), list(itertools.product(RULES, KEYS)))
def test_field_matches_parity(rule: str, key: str) -> None:
    assert field_matches(rule, key) == _field_name_matches(rule, key)


@pytest.mark.parametrize(("pattern", "name"), list(itertools.product(RULES, KEYS)))
def test_object_matches_parity(pattern: str, name: str) -> None:
    assert object_matches(pattern, name) == _pattern_matches(pattern, name)


def test_is_pattern() -> None:
    assert is_pattern("patients.*") and is_pattern("s?n") and not is_pattern("log[abc]")
