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

`DATABASE_URL=postgres://localhost/clinic` switches to PostgreSQL.
