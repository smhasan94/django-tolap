import itertools

import pytest
from tolap_core.enforcement import _field_name_matches, _pattern_matches

from sqlalchemy_tolap.matching import field_matches, object_matches
from tests.test_matching import KEYS, RULES


@pytest.mark.parametrize(("rule", "key"), list(itertools.product(RULES, KEYS)))
def test_parity(rule: str, key: str) -> None:
    assert field_matches(rule, key) == _field_name_matches(rule, key)
    assert object_matches(rule, key) == _pattern_matches(rule, key)
