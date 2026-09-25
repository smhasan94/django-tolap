from __future__ import annotations

import pytest

from tests.harness.seed import seed


@pytest.fixture
def seeded(db: None) -> None:
    """Upstream's six patients, encounters, diagnoses, billing and audit rows."""
    seed()
