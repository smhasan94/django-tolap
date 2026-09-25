# django-tolap

**TOLAP policies managed in Django admin and enforced on your QuerySets.**

[TOLAP](https://github.com/awslabs/tolap) (Tool-Object Level Access Protocol, AWS,
Apache-2.0) decides what an AI agent's tool may *return*: which tables, columns and rows,
how fields are masked, how many results. `django-tolap` brings that to Django:

- **QuerySet enforcement.** `enforce(queryset, context)` returns the rows a signed TOLAP
  policy allows, as dicts, with hidden columns gone and masked fields masked.
- **ORM-native pushdown.** Row filters become `Q` objects, the result limit becomes a
  slice, hidden columns leave the `SELECT`. Excluded rows never cross the wire. Proven equal
  to post-pass-only with upstream's fixtures and property tests; TOLAP's own post-execution
  pass always runs afterwards.
- **Policy store in Django admin.** Definitions and assignments are models with migrations,
  validation through upstream's deserializer, schema-drift warnings, a resolve preview and
  an audit log.
- **A tool decorator and DRF mixins** that resolve, sign, verify and enforce per call.

## Install

```bash
pip install django-tolap            # add [drf] for the REST Framework mixins
```

Python 3.11+, Django 5.2 to 6.1. Pulls `tolap-core` and `tolap-store` from PyPI.

## Quickstart

```python
# settings.py
INSTALLED_APPS += ["django_tolap"]
TOLAP = {"SIGNING_KEY": "change-me"}   # any secret; treat it like SECRET_KEY
```

```bash
python manage.py migrate django_tolap
```

```python
from django_tolap import enforce, issue_context
from django_tolap.store import DjangoPolicyStore

store = DjangoPolicyStore()
store.save_definition_json({
    "version": "1.0",
    "name": "analyst",
    "permissions": {"canQuery": True, "readOnly": True},
    "objectRules": {
        "allowedObjects": ["patients"],
        "fieldRules": {
            "hiddenFields": ["patients.ssn"],
            "maskedFields": [{"field": "patients.email", "maskType": "hash"}],
        },
        "rowFilters": [{"field": "region", "operator": "in", "values": ["us-east", "us-west"]}],
    },
    "limits": {"maxResults": 500},
})
store.assign("analyst", user_id="alice", tenant_id="clinic", granted_by="admin", reason="demo")

context = issue_context("alice", "clinic", "db:clinic:patients")
rows = enforce(Patient.objects.filter(status="active"), context)
```

The SQL that ran selects only the visible columns, filters `region` in the database and
stops at 500 rows. `email` comes back as a SHA-256 pseudonym. Then TOLAP's post-execution
pipeline runs over the rows; that pass is the security boundary and always runs.

Full documentation, the benchmark on 1,000,000 rows, the agent-tool decorator and the
Django REST Framework integration are in the
[repository README](https://github.com/smhasan94/django-tolap#readme).

## License

Apache-2.0. Not affiliated with AWS; TOLAP is their project.
