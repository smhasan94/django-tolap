# django-tolap

**TOLAP policies managed in Django admin and enforced on your QuerySets.**

[TOLAP](https://github.com/awslabs/tolap) (Tool-Object Level Access Protocol, AWS, Apache-2.0)
decides what an AI agent's tool may *return*: which tables, columns and rows, how fields are
masked, how many results. `django-tolap` brings that to Django:

- **QuerySet enforcement.** One call turns any QuerySet into the rows a signed TOLAP policy
  allows, as dicts, with hidden columns gone and masked fields masked.
- **ORM-native pushdown.** Row filters become `Q` objects, the result limit becomes a slice,
  hidden columns leave the `SELECT`. The database does the filtering; excluded rows never cross
  the wire. Proven equal to post-pass-only with upstream's fixtures and property tests.
- **Policy store in Django admin** (coming in the next epic), a DRF mixin, and a tool
  decorator.

Status: **v0.1 in progress.** Epic 1 (QuerySet enforcement core) is done. See
[`docs/03-epics.md`](docs/03-epics.md).

## Install

Not on PyPI yet. From this repository:

```bash
pip install "django-tolap @ git+https://github.com/smhasan94/django-tolap#subdirectory=packages/django-tolap"
```

This pulls `tolap-core` and `tolap-store` from PyPI. Python 3.11+, Django 5.2/6.0/6.1.

## Quickstart

Add the app and a signing key:

```python
# settings.py
INSTALLED_APPS += ["django_tolap"]
TOLAP = {"SIGNING_KEY": "change-me"}   # any secret; treat it like SECRET_KEY
```

Given a model such as

```python
class Patient(models.Model):
    full_name = models.TextField()
    email = models.TextField()
    ssn = models.TextField()
    region = models.TextField()
    status = models.TextField()

    class Meta:
        db_table = "patients"
```

write a policy, sign it, and enforce it on a QuerySet:

<!-- quickstart:start -->
```python
from django.conf import settings
from tolap_core import build_security_context, deserialize_effective_policy, sign_context

from django_tolap import enforce
from clinic.models import Patient

policy = deserialize_effective_policy({
    "version": "1.0",
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
context = sign_context(
    build_security_context("alice", "clinic", [policy]), settings.TOLAP["SIGNING_KEY"]
)

rows = enforce(Patient.objects.filter(status="active"), context)
print(rows)
```
<!-- quickstart:end -->

The SQL that ran:

```sql
SELECT "patients"."id", "patients"."full_name", "patients"."email", "patients"."region",
       "patients"."status"
FROM "patients"
WHERE "patients"."status" = 'active' AND "patients"."region" IN ('us-east', 'us-west')
LIMIT 500
```

`ssn` was never selected, out-of-region rows never left the database, and `email` came back
as a SHA-256 pseudonym. Then TOLAP's own post-execution pipeline ran over the rows. That pass
is the security boundary and always runs; the pushdown only reduces what the database
produces.

## What upstream already does, and what this adds

The TOLAP Python SDK already rewrites **raw SQL strings** (`tolap_core.sql_rewriter`): it
pushes row filters, the limit and hidden columns into a `SELECT` you hand it as text. Its own
docs list "an ORM that owns its own SQL" as the case where you fall back to post-pass only.
`django-tolap` is that missing piece: it works on the QuerySet, so joins, annotations,
subqueries and Django's parameter handling stay Django's, and the rewrite is a `Q`, not a
regex.

Where a filter has no faithful ORM form on your database (`contains`, `startsWith`,
`matches` everywhere; `like` on SQLite; string ordering on PostgreSQL), it is left to the
post pass and reported in `Preparation.unpushable_filters`. Never approximated.

## How it works

```
enforce(queryset, context)
  1. verify signature, then expiry            (tolap_core)
  2. canQuery, object access for every table  (tolap_core.validate_access)
  3. referenced columns vs hidden/allowed     (refuses; never silently narrows)
  4. push Q filters, .values(visible), [:max] (django_tolap)
  5. execute                                  (Django)
  6. apply_result_pipeline(rows, policy)      (tolap_core, always)
```

Modes mirror upstream's `SqlEnforcementMode`: `enforce(..., mode="postOnly")` skips the
pushdown but not the checks or the post pass, and returns the same rows.

## Compatibility

| | Tested | Notes |
| --- | --- | --- |
| PostgreSQL | CI | `like` pushed; string ordering left to post pass (collation) |
| SQLite | CI | `like` left to post pass (case-insensitive `LIKE`) |
| MySQL | not yet | string equality left to post pass (case-insensitive collations) |

`tolap-core` 1.0.0 from PyPI. Upstream `main` is tested separately.

## Docs

- [`docs/01-overview.md`](docs/01-overview.md): problem, landscape, design, threat model
- [`docs/02-prd.md`](docs/02-prd.md): requirements
- [`docs/decisions.md`](docs/decisions.md): every decision and why

## License

Apache-2.0. Not affiliated with AWS; TOLAP is their project.
