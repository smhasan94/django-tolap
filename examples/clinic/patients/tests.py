"""Smoke test for the REST path: run with ``manage.py test patients``."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase


class ApiSmokeTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        call_command("seed_patients", rows=200, verbosity=0)

    def test_analyst_sees_us_east_without_ssn(self) -> None:
        self.client.force_login(get_user_model().objects.get(username="alice"))
        rows = self.client.get("/api/patients/").json()
        self.assertTrue(rows)
        self.assertTrue(all(r["region"] == "us-east" and "ssn" not in r for r in rows))
        self.assertEqual(self.client.delete(f"/api/patients/{rows[0]['id']}/").status_code, 403)

    def test_auditor_sees_every_region_redacted(self) -> None:
        self.client.force_login(get_user_model().objects.get(username="bob"))
        rows = self.client.get("/api/patients/").json()
        self.assertGreater(len({r["region"] for r in rows}), 1)
        self.assertTrue(all(r["full_name"] == "[REDACTED]" for r in rows))

    def test_schema_is_the_callers_view(self) -> None:
        self.client.force_login(get_user_model().objects.get(username="alice"))
        schema = self.client.get("/api/schema/?format=json").json()
        properties = schema["components"]["schemas"]["Patient"]["properties"]
        self.assertNotIn("ssn", properties)
        self.assertEqual(properties["email"]["x-tolap-mask"], "hash")
        self.assertEqual(set(schema["paths"]["/api/patients/"]), {"get"})

    def test_anonymous_is_refused(self) -> None:
        self.assertIn(self.client.get("/api/patients/").status_code, (401, 403))
