"""The corpus loads and both paths run; the committed report must be regenerable."""

from __future__ import annotations

import pytest
from django.db import connection

from django_tolap.pushdown import prepare_queryset
from tests.gap.corpus import CORPUS, POLICIES, REFUSED
from tests.gap.sa_corpus import SA_REFUSED

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
    assert "# Documented limits" in text
    corpus_rows = (len(CORPUS) + len(SA_CORPUS)) * len(POLICIES)
    assert text.count("| `") == corpus_rows + len(REFUSED) + len(SA_REFUSED)
    # Row starts only: the corpus tables' header lines end in these cells too.
    assert text.count("\n| django-tolap | ") == len(REFUSED)
    assert text.count("\n| sqlalchemy-tolap | ") == len(SA_REFUSED)


@pytest.mark.parametrize("entry", REFUSED, ids=lambda e: e[0])
def test_documented_limit_is_refused(seeded: None, entry) -> None:  # type: ignore[no-untyped-def]
    _, factory, _ = entry
    for policy in POLICIES.values():
        prep = prepare_queryset(factory(), policy)
        assert not prep.allowed and prep.denial_reason


@pytest.mark.parametrize("entry", SA_REFUSED, ids=lambda e: e[0])
def test_sqlalchemy_documented_limit_is_refused(entry) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy_tolap.pushdown import prepare_select

    _, factory, _ = entry
    for policy in POLICIES.values():
        prep = prepare_select(factory(), policy, dialect="sqlite")
        assert not prep.allowed and prep.denial_reason
