from django.db import models

REGIONS = ["us-east", "us-west", "us-central", "eu-west", "eu-central", "ap-south"]


class Patient(models.Model):
    full_name = models.CharField(max_length=80)
    email = models.CharField(max_length=120)
    ssn = models.CharField(max_length=11)
    date_of_birth = models.DateField()
    region = models.CharField(max_length=16, db_index=True)
    status = models.CharField(max_length=16)
    score = models.IntegerField(null=True)

    class Meta:
        db_table = "patients"
