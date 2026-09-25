#!/usr/bin/env sh
# Prove the README quickstart works in a fresh project: install from this checkout,
# start a project and app, add the model, run the snippet between the README markers.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

uv venv -q .venv
. .venv/bin/activate
uv pip install -q "$ROOT/packages/django-tolap"

django-admin startproject demo .
python manage.py startapp clinic
cat > clinic/models.py <<'PY'
from django.db import models


class Patient(models.Model):
    full_name = models.TextField()
    email = models.TextField()
    ssn = models.TextField()
    region = models.TextField()
    status = models.TextField()

    class Meta:
        db_table = "patients"
PY
cat >> demo/settings.py <<'PY'
INSTALLED_APPS += ["django_tolap", "clinic"]
TOLAP = {"SIGNING_KEY": "change-me"}
PY
python manage.py makemigrations clinic -v 0
python manage.py migrate -v 0
python manage.py shell -c "
from clinic.models import Patient
Patient.objects.create(full_name='John Smith', email='john@example.com', ssn='111-22-3333', region='us-east', status='active')
Patient.objects.create(full_name='Dana Petrova', email='dana@example.com', ssn='444-55-6666', region='eu-west', status='active')
"

awk '/<!-- quickstart:start -->/{flag=1;next}/<!-- quickstart:end -->/{flag=0}flag' "$ROOT/README.md" \
  | sed '/^```/d' > snippet.py
python manage.py shell -c "exec(open('snippet.py').read())" | tee out.txt
grep -q "'full_name': 'John Smith'" out.txt
! grep -q "ssn" out.txt
! grep -q "eu-west" out.txt
! grep -q "john@example.com" out.txt
echo "quickstart OK"
