"""Test models mirroring upstream ``sdk/python/tests/integration/schema.sql``.

``db_table`` names match upstream so fixture policies (``allowedObjects: ["patients"]``,
``hiddenFields: ["patients.ssn"]``) apply unchanged. ``region`` and ``score`` are nullable on
``Patient`` so null-handling tests can insert rows upstream's seed does not contain.
"""

from django.db import models


class Patient(models.Model):
    full_name = models.TextField()
    email = models.TextField()
    ssn = models.TextField()
    date_of_birth = models.DateField()
    region = models.TextField(null=True)
    status = models.TextField()
    score = models.IntegerField(null=True)

    class Meta:
        db_table = "patients"


class Encounter(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="encounters")
    occurred_at = models.DateTimeField()
    region = models.TextField()
    status = models.TextField()

    class Meta:
        db_table = "encounters"


class Diagnosis(models.Model):
    encounter = models.ForeignKey(Encounter, on_delete=models.CASCADE, related_name="diagnoses")
    icd10 = models.TextField()
    region = models.TextField()
    status = models.TextField()

    class Meta:
        db_table = "diagnoses"


class BillingInternal(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, null=True)
    amount_cents = models.IntegerField()
    region = models.TextField()

    class Meta:
        db_table = "billing_internal"


class AuditLog(models.Model):
    actor = models.TextField()
    action = models.TextField()
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "audit_log"
