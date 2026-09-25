"""The corpus loads and both paths run; the committed report must be regenerable."""

from __future__ import annotations

import pytest
from django.db import connection

from django_tolap.pushdown import prepare_queryset
from tests.gap.corpus import CORPUS, POLICIES

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("entry", CORPUS, ids=lambda e: e[0])
def test_corpus_entry_prepares_or_refuses_cleanly(seeded: None, entry) -> None:  # type: ignore[no-untyped-def]
    name, factory, _ = entry
    for policy in POLICIES.values():
        prep = prepare_queryset(factory(), policy)
        if prep.allowed:
            assert prep.queryset is not None
            list(prep.queryset)
        else:
            assert prep.denial_reason


def test_report_renders(seeded: None) -> None:
    from tests.gap import report
    from tests.gap.sa_corpus import SA_CORPUS

    text = report.render()
    assert "## Policy: hide-ssn-filter-region" in text and connection.vendor in text
    assert "## Policy: hide-ssn-filter-region (SQLAlchemy)" in text
    assert text.count("| `") == (len(CORPUS) + len(SA_CORPUS)) * len(POLICIES)
