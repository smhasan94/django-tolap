"""Field and object name matching with upstream's semantics (connector spec section 3).

Mirrors ``tolap_core.enforcement._pattern_matches`` and ``_field_name_matches``, which are
private upstream. They are reproduced here (not imported) so a refactor upstream cannot
silently change our pre-execution decisions; ``tests/test_matching.py`` asserts parity
against the upstream functions on a corpus so drift is caught instead.

Rules: ``*`` and ``?`` are the only metacharacters, brackets are literal, matching is
case-insensitive and platform-independent, and a field reference may be bare (``ssn``) or
qualified (``patients.ssn``) on either side.
"""

from __future__ import annotations

from fnmatch import fnmatchcase


def _literal_brackets(pattern: str) -> str:
    return pattern.replace("[", "[[]")


def object_matches(pattern: str, name: str) -> bool:
    """Case-insensitive glob over the whole name, brackets literal."""
    return fnmatchcase(name.lower(), _literal_brackets(pattern).lower())


def _forms(name: str) -> set[str]:
    lowered = name.lower()
    forms = {lowered}
    if "." in lowered:
        forms.add(lowered.split(".", 1)[1])
        forms.add(lowered.rsplit(".", 1)[1])
    return forms


def field_matches(rule: str, key: str) -> bool:
    """Whether a policy field reference refers to a record key, either side qualified."""
    return any(
        fnmatchcase(key_form, _literal_brackets(rule_form))
        for rule_form in _forms(rule)
        for key_form in _forms(key)
    )


def is_pattern(name: str) -> bool:
    return "*" in name or "?" in name
