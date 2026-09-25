"""Load upstream TOLAP fixtures verbatim (see ``tests/fixtures/upstream/SOURCE``).

Fixture policies are bare (``version``, ``permissions``, ``objectRules``, ``limits``). The
effective-policy schema requires an envelope, so :func:`effective_policy` adds one in exactly
one place and deserializes through upstream's own deserializer. Nothing else touches the
fixture content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tolap_core import EffectivePolicy, deserialize_effective_policy

UPSTREAM = Path(__file__).resolve().parent.parent / "fixtures" / "upstream"

FIXTURE_USER = "fixture-user"
FIXTURE_TENANT = "fixture-tenant"
FIXTURE_SOURCE = "db:testapp:patients"


def envelope(bare: dict[str, Any], *, source: str = FIXTURE_SOURCE) -> dict[str, Any]:
    """Wrap a bare fixture policy in the effective-policy envelope, camelCase as on the wire."""
    now = datetime.now(UTC)
    wrapped: dict[str, Any] = {
        "version": bare.get("version", "1.0"),
        "userId": FIXTURE_USER,
        "tenantId": FIXTURE_TENANT,
        "sourceConnectionId": source,
        "resolvedAt": now.isoformat().replace("+00:00", "Z"),
        "expiresAt": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "sourceProfiles": ["fixture"],
        "permissions": bare["permissions"],
        "integrity": {"algorithm": "hmac-sha256", "signature": ""},
    }
    for key in ("objectRules", "limits", "purposeProfile"):
        if key in bare:
            wrapped[key] = bare[key]
    return wrapped


def effective_policy(bare: dict[str, Any], *, source: str = FIXTURE_SOURCE) -> EffectivePolicy:
    return deserialize_effective_policy(envelope(bare, source=source))


def _load(relative: str) -> dict[str, Any]:
    with (UPSTREAM / relative).open() as fh:
        data: dict[str, Any] = json.load(fh)
    return data


@dataclass(frozen=True)
class OperatorCase:
    name: str
    policy: EffectivePolicy
    bare_policy: dict[str, Any]
    records: list[dict[str, Any]]
    expected_ids: list[str]
    notes: str


def operator_corpus() -> list[OperatorCase]:
    """``fixtures/enforcement/apply-row-filters-all-operators.json``: one case per operator."""
    data = _load("enforcement/apply-row-filters-all-operators.json")
    records: list[dict[str, Any]] = data["records"]
    return [
        OperatorCase(
            name=case["name"],
            policy=effective_policy(case["policy"]),
            bare_policy=case["policy"],
            records=records,
            expected_ids=list(case["expected"]),
            notes=case.get("notes", ""),
        )
        for case in data["cases"]
    ]


@dataclass(frozen=True)
class Scenario:
    name: str
    policy: EffectivePolicy
    bare_policy: dict[str, Any]
    table: str
    columns: list[str]
    expected: dict[str, Any]


def _scenario_policy(data: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    """Per-scenario ``policy``, or ``basePolicy`` shallow-merged with ``policyOverride``.

    Mirrors upstream ``sdk/python/tests/integration/_scenarios.py::merge_policy``: top-level
    keys only, nested objects replaced wholesale.
    """
    if "policy" in scenario:
        policy: dict[str, Any] = scenario["policy"]
        return policy
    merged = dict(data["basePolicy"])
    merged.update(scenario.get("policyOverride") or {})
    return merged


def integration_scenarios(file_name: str) -> list[Scenario]:
    """A ``fixtures/integration-scenarios/*.json`` file as :class:`Scenario` objects."""
    data = _load(f"integration-scenarios/{file_name}")
    scenarios: list[Scenario] = []
    for s in data["scenarios"]:
        if "query" not in s:
            continue
        bare = _scenario_policy(data, s)
        scenarios.append(
            Scenario(
                name=s["name"],
                policy=effective_policy(bare),
                bare_policy=bare,
                table=s["query"]["table"],
                columns=list(s["query"]["columns"]),
                expected=s["expected"],
            )
        )
    return scenarios


INTEGRATION_FILES = (
    "postgres-row-filters.json",
    "postgres-field-rules.json",
    "postgres-healthcare-analyst.json",
    "permissions-and-limits.json",
)


def all_scenarios() -> list[tuple[str, Scenario]]:
    return [(f, s) for f in INTEGRATION_FILES for s in integration_scenarios(f)]
