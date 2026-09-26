# Example: clinic

A Django project with one model (`patients`), two TOLAP policies (analyst, auditor), one agent
tool (`patients.tools.patients_search`), and a benchmark.

```bash
cd examples/clinic
uv run python manage.py migrate
uv run python manage.py seed_patients --rows 100000      # 1000000 for the README numbers
uv run python manage.py benchmark --user alice --markdown
uv run python manage.py createsuperuser                   # then /admin/django_tolap/
uv run python manage.py runserver
```

`DATABASE_URL=postgres://localhost/clinic` switches to PostgreSQL. Running from this
repository's `uv` environment provides `dj-database-url`; elsewhere `pip install django-tolap
dj-database-url`.

Memory in the benchmark is the process high-water mark, so the modes run from lightest to
heaviest and each delta is what that mode added.

## The same policies over REST

`patients/api.py` mounts the model as a DRF viewset with the `django-tolap` mixins; the
seed creates login users `alice` (analyst) and `bob` (auditor), password = username.

```bash
uv run python manage.py runserver
curl -u alice:alice 'http://127.0.0.1:8000/api/patients/?q=jo'   # us-east only, no ssn, hashed email
curl -u bob:bob     'http://127.0.0.1:8000/api/patients/3/'      # every region, names redacted
curl -u alice:alice -X DELETE http://127.0.0.1:8000/api/patients/3/   # 403: read-only policy
curl -u alice:alice http://127.0.0.1:8000/api/schema/            # alice's schema: no ssn, no writes
```

The schema is served per caller (`SERVE_PUBLIC = False`); `manage.py spectacular` prints
the full one. `manage.py test patients` runs the API smoke test.
