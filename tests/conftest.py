from __future__ import annotations

import os

import pytest
from hypothesis import settings as hypothesis_settings

from tests.harness.seed import seed

hypothesis_settings.register_profile("ci", max_examples=500)
hypothesis_settings.register_profile("dev", max_examples=50)
hypothesis_settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture
def seeded(db: None) -> None:
    """Upstream's six patients, encounters, diagnoses, billing and audit rows."""
    seed()
