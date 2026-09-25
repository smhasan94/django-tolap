"""Seed rows identical to upstream ``schema.sql`` so integration scenarios' expected ids hold."""

from __future__ import annotations

import datetime as dt
import re

from django.core.management.color import no_style
from django.db import connection

from tests.harness.fixtures import UPSTREAM
from tests.testapp.models import AuditLog, BillingInternal, Diagnosis, Encounter, Patient

PATIENTS = [
    ("John Smith", "john.smith@example.com", "111-22-3333", "1980-03-12", "us-east", "active"),
    ("Jane Doe", "jane.doe@example.com", "222-33-4444", "1975-09-01", "us-west", "active"),
    ("Mary Johnson", "mary.j@example.com", "333-44-5555", "1990-12-30", "us-east", "active"),
    ("Bob Wilson", "bob.wilson@example.com", "444-55-6666", "1965-07-22", "us-central", "active"),
    ("Alice Brown", "alice.brown@example.com", "555-66-7777", "1988-02-14", "eu-west", "active"),
    ("Carl Davis", "carl.davis@example.com", "666-77-8888", "1972-11-05", "us-west", "deleted"),
]
ENCOUNTERS = [
    (1, "2026-01-15T09:00+00:00", "us-east", "active"),
    (2, "2026-02-10T14:30+00:00", "us-west", "active"),
    (3, "2026-03-05T11:15+00:00", "us-east", "active"),
    (4, "2026-04-20T16:45+00:00", "us-central", "active"),
    (5, "2026-05-01T08:00+00:00", "eu-west", "active"),
    (6, "2026-05-12T10:00+00:00", "us-west", "deleted"),
]
DIAGNOSES = [
    (1, "E11.9", "us-east", "active"),
    (2, "I10", "us-west", "active"),
    (3, "J45.9", "us-east", "active"),
    (4, "M54.5", "us-central", "active"),
    (5, "K21.9", "eu-west", "active"),
]
BILLING = [(1, 12500, "us-east"), (2, 89000, "us-west")]
AUDIT = [
    ("admin@hospital", "GRANT_POLICY", "2026-05-01T12:00+00:00"),
    ("admin@hospital", "REVOKE_POLICY", "2026-05-15T12:00+00:00"),
]


def seed() -> None:
    """Insert upstream's rows with explicit ids 1..n so ``idsEqual`` expectations match."""
    Patient.objects.bulk_create(
        [
            Patient(
                id=i,
                full_name=n,
                email=e,
                ssn=s,
                date_of_birth=dt.date.fromisoformat(d),
                region=r,
                status=st,
            )
            for i, (n, e, s, d, r, st) in enumerate(PATIENTS, start=1)
        ]
    )
    Encounter.objects.bulk_create(
        [
            Encounter(
                id=i, patient_id=p, occurred_at=dt.datetime.fromisoformat(o), region=r, status=st
            )
            for i, (p, o, r, st) in enumerate(ENCOUNTERS, start=1)
        ]
    )
    Diagnosis.objects.bulk_create(
        [
            Diagnosis(id=i, encounter_id=e, icd10=c, region=r, status=st)
            for i, (e, c, r, st) in enumerate(DIAGNOSES, start=1)
        ]
    )
    BillingInternal.objects.bulk_create(
        [
            BillingInternal(id=i, patient_id=p, amount_cents=a, region=r)
            for i, (p, a, r) in enumerate(BILLING, start=1)
        ]
    )
    AuditLog.objects.bulk_create(
        [
            AuditLog(id=i, actor=a, action=ac, occurred_at=dt.datetime.fromisoformat(o))
            for i, (a, ac, o) in enumerate(AUDIT, start=1)
        ]
    )
    # Explicit ids leave PostgreSQL sequences behind; realign them so later inserts work.
    statements = connection.ops.sequence_reset_sql(
        no_style(), [Patient, Encounter, Diagnosis, BillingInternal, AuditLog]
    )
    if statements:
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)


def upstream_row_counts() -> dict[str, int]:
    """Count VALUES tuples per table in upstream ``schema.sql`` (guards the hardcoded seed)."""
    sql = (UPSTREAM / "schema" / "schema.sql").read_text()
    counts: dict[str, int] = {}
    for match in re.finditer(r"INSERT INTO (\w+) \([^)]*\) VALUES\s*(.*?);", sql, re.S):
        counts[match.group(1)] = len(re.findall(r"\(\s*(?:\d+|')", match.group(2)))
    return counts
