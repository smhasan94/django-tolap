"""Seed N patients spread across regions, plus the two example policies and assignments."""

from __future__ import annotations

import datetime as dt
import random
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandParser

from django_tolap.store import DjangoPolicyStore
from patients.models import REGIONS, Patient
from patients.policies import ANALYST, AUDITOR

FIRST = ["John", "Jane", "Mary", "Bob", "Alice", "Carl", "Dana", "Chidi", "Bruno", "Mei"]
LAST = ["Smith", "Doe", "Johnson", "Wilson", "Brown", "Davis", "Petrova", "Okonkwo", "Sato", "Li"]
BATCH = 10_000


class Command(BaseCommand):
    help = "Seed patients (deterministic), the example policies, and assignments for alice/bob."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--rows", type=int, default=100_000)
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args: Any, **options: Any) -> None:
        rng = random.Random(options["seed"])
        Patient.objects.all().delete()
        total = options["rows"]
        for start in range(0, total, BATCH):
            batch = []
            for i in range(start, min(start + BATCH, total)):
                # No explicit ids: bulk_create with ids would leave the PostgreSQL sequence
                # behind, and the next admin insert would collide on the primary key.
                batch.append(
                    Patient(
                        full_name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                        email=f"patient{i + 1}@example.com",
                        ssn=f"{rng.randint(100, 999)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}",
                        date_of_birth=dt.date(1940, 1, 1)
                        + dt.timedelta(days=rng.randint(0, 30_000)),
                        region=rng.choice(REGIONS),
                        status="deleted" if rng.random() < 0.05 else "active",
                        score=None if rng.random() < 0.1 else rng.randint(0, 100),
                    )
                )
            Patient.objects.bulk_create(batch)
            self.stdout.write(f"  {min(start + BATCH, total):,}/{total:,}")
        for username in ("alice", "bob"):
            # Login users for the REST API (password = username; example only).
            user, _ = get_user_model().objects.get_or_create(username=username)
            user.set_password(username)
            user.save()
        store = DjangoPolicyStore()
        for body in (ANALYST, AUDITOR):
            store.save_definition_json(body)
        store.assign(
            ANALYST["name"],
            user_id="alice",
            tenant_id="clinic",
            granted_by="seed",
            reason="example",
        )
        store.assign(
            AUDITOR["name"], user_id="bob", tenant_id="clinic", granted_by="seed", reason="example"
        )
        self.stdout.write(
            self.style.SUCCESS(f"Seeded {total:,} patients; alice=analyst, bob=auditor.")
        )
