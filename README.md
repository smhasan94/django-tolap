# django-tolap

[![CI](https://github.com/smhasan94/django-tolap/actions/workflows/ci.yml/badge.svg)](https://github.com/smhasan94/django-tolap/actions/workflows/ci.yml)
[![PyPI: django-tolap](https://img.shields.io/pypi/v/django-tolap?label=django-tolap)](https://pypi.org/project/django-tolap/)
[![PyPI: sqlalchemy-tolap](https://img.shields.io/pypi/v/sqlalchemy-tolap?label=sqlalchemy-tolap)](https://pypi.org/project/sqlalchemy-tolap/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://github.com/smhasan94/django-tolap/blob/main/packages/django-tolap/pyproject.toml)
[![Django 5.2 to 6.1](https://img.shields.io/badge/django-5.2%20%7C%206.0%20%7C%206.1-0C4B33)](https://github.com/smhasan94/django-tolap/blob/main/.github/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

**TOLAP policies managed in Django admin and enforced on your QuerySets.**

[TOLAP](https://github.com/awslabs/tolap) (Tool-Object Level Access Protocol, AWS, Apache-2.0)
decides what an AI agent's tool may *return*: which tables, columns and rows, how fields are
masked, how many results. `django-tolap` brings that to Django:

- **QuerySet enforcement.** One call turns any QuerySet into the rows a signed TOLAP policy
  allows, as dicts, with hidden columns gone and masked fields masked.
- **ORM-native pushdown.** Row filters become `Q` objects, the result limit becomes a slice,
  hidden columns leave the `SELECT`. The database does the filtering; excluded rows never cross
  the wire. Proven equal to post-pass-only with upstream's fixtures and property tests.
- **Policy store in Django admin.** Definitions and assignments are models; the admin
  validates bodies with upstream's own deserializer, warns about fields your models lack,
  previews what a user resolves to, and keeps an audit log. Resolution and merging are
  upstream's `resolve()`, not a reimplementation.
- **A tool decorator and DRF mixins** that resolve, sign, verify and enforce per call, and
  compose with upstream's own `tolap-mcp` wrapper.

## Why pushdown

Same tool, same policy, same 1,000,000-row `patients` table on PostgreSQL 17 (Apple M-series
laptop, `examples/clinic`, `manage.py benchmark`). Both modes return identical rows; the post
pass runs in both. The only difference is what the database is asked to produce.

Analyst policy (`region = us-east`, `status <> deleted`, `maxResults 500`, SSN hidden, email
hashed, name partially masked):

| Mode (postgresql, 1,000,000 rows) | Rows fetched | Rows returned | Median wall time | Peak RSS delta |
| --- | ---: | ---: | ---: | ---: |
| `rewriteAndPost` | 500 | 500 | 18 ms | 1 MB |
| `postOnly` | 1,000,000 | 500 | 6,323 ms | 1,207 MB |

Auditor policy (all regions, `status <> deleted`, `maxResults 1000`, everything identifying
redacted):

| Mode (postgresql, 1,000,000 rows) | Rows fetched | Rows returned | Median wall time | Peak RSS delta |
| --- | ---: | ---: | ---: | ---: |
| `rewriteAndPost` | 1,000 | 1,000 | 41 ms | 3 MB |
| `postOnly` | 1,000,000 | 1,000 | 39,179 ms | 2,192 MB |

Analyst policy with the tool's own filter `full_name__icontains="smith"` on top:

| Mode (postgresql, 1,000,000 rows) | Rows fetched | Rows returned | Median wall time | Peak RSS delta |
| --- | ---: | ---: | ---: | ---: |
| `rewriteAndPost` | 500 | 500 | 41 ms | 1 MB |
| `postOnly` | 99,747 | 500 | 667 ms | 115 MB |

The SQL the analyst query sent with pushdown:

```sql
SELECT "patients"."id", "patients"."full_name", "patients"."email", "patients"."region",
       "patients"."status", "patients"."score"
FROM "patients"
WHERE ("patients"."region" = 'us-east' AND NOT ("patients"."status" = 'deleted'))
ORDER BY 1 ASC LIMIT 500
```

Without it: `SELECT ... FROM "patients" ORDER BY 1 ASC`, a million rows into Python, then
TOLAP keeps 500. `ssn` is not in either statement.

Status: **v0.1 feature-complete, unreleased.** All six epics done (enforcement, store and
admin, tool and DRF, differential hardening, example and benchmark, SQLAlchemy adapter). See
[`docs/03-epics.md`](docs/03-epics.md).

## Install

Not on PyPI yet. From this repository:

```bash
pip install "django-tolap @ git+https://github.com/smhasan94/django-tolap#subdirectory=packages/django-tolap"
```

This pulls `tolap-core` and `tolap-store` from PyPI. Python 3.11+, Django 5.2/6.0/6.1.

## Quickstart

Add the app, a signing key, and migrate:

```python
# settings.py
INSTALLED_APPS += ["django_tolap"]
TOLAP = {"SIGNING_KEY": "change-me"}   # any secret; treat it like SECRET_KEY
```

```bash
python manage.py migrate django_tolap
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

author a policy and assign it. In Django admin (`/admin/django_tolap/`) paste the JSON
below into a new policy definition and add an assignment for user `alice`, or do the same
from a shell:

<!-- quickstart:start -->
```python
from django_tolap import enforce, issue_context
from django_tolap.store import DjangoPolicyStore
from clinic.models import Patient

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

# In the tool: resolve (merge, most-restrictive-wins), sign, enforce.
context = issue_context("alice", "clinic", "db:clinic:patients")
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

Every definition, assignment and resolution lands in the audit log (also in admin). The
"Resolve preview" button on the definitions list shows what a user resolves to. Groups map
to Django groups by default (`TOLAP["IDENTITY_RESOLVER"]` to change that).

## In an agent tool

```python
from django_tolap import tolap_tool, ToolContext

@tolap_tool(source="db:clinic:patients")
def patients_search(q: str, *, tolap: ToolContext) -> list[dict]:
    return tolap.enforce(Patient.objects.filter(full_name__icontains=q))

patients_search("smith", user_id="alice", tenant_id="clinic")
```

Identity comes from the call's `user_id`/`tenant_id`, from an `identity=` callable that
derives them from the tool's own arguments, or from `TOLAP["IDENTITY"]`. A signed
`context=` issued elsewhere (for example by upstream's policy server) is verified and used
as-is. This composes with upstream's `tolap-mcp` wrapper: let it run `pre_execute` for the
tool call and `django-tolap` enforce the query; see `tests/test_tool_mcp_interop.py`.

## In Django REST Framework

```python
from django_tolap.drf import TolapSerializerMixin, TolapViewSetMixin

class PatientSerializer(TolapSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = "__all__"

class PatientViewSet(TolapViewSetMixin, viewsets.ModelViewSet):
    queryset = Patient.objects.all()
    serializer_class = PatientSerializer
    tolap_source = "db:clinic:patients"
```

`list` and `retrieve` return enforced rows (a filtered-out row is a 404). `POST`, `PUT`,
`PATCH` and `DELETE` go through upstream `validate_write`: refused on a `readOnly` policy,
when the policy lacks the write permission, when the payload names a hidden or read-only
field, or when the target row is not visible under the row filters. The tenant is
`"default"` unless `TOLAP["TENANT_RESOLVER"]` names a callable taking the request.
Install with `pip install "django-tolap[drf]"`.

## SQLAlchemy

The same adapter for SQLAlchemy 2.x `Select` statements, without Django:

```python
from sqlalchemy import select
from sqlalchemy_tolap import enforce

rows = enforce(
    select(Patient).where(Patient.full_name.ilike(f"%{q}%")),
    context,            # a signed TOLAP SecurityContext from wherever you resolve policies
    session,            # Session or Connection; its dialect decides what can be pushed
    signing_key=KEY,
)
```

Same pre-checks, same pushdown rules (negations render `(col <> x OR col IS NULL)`
explicitly, since SQLAlchemy does not add the null arm Django does), same mandatory post
pass, same differential proof on SQLite and PostgreSQL against the same fixtures and
property tests. Entity selects (`select(Patient)`) are the default projection; named columns
and labels are explicit references. `text()`, `literal_column()`, derived tables in `FROM`
and set operations are refused. Install with `pip install sqlalchemy-tolap` once released;
from this repository:

```bash
pip install "sqlalchemy-tolap @ git+https://github.com/smhasan94/django-tolap#subdirectory=packages/sqlalchemy-tolap"
```

## What upstream already does, and what this adds

The TOLAP Python SDK already rewrites **raw SQL strings** (`tolap_core.sql_rewriter`): it
pushes row filters, the limit and hidden columns into a `SELECT` you hand it as text. Its own
docs list "an ORM that owns its own SQL" as the case where you fall back to post-pass only.
`django-tolap` is that missing piece: it works on the QuerySet, so joins, annotations,
subqueries and Django's parameter handling stay Django's, and the rewrite is a `Q`, not a
regex.

Measured on 48 (QuerySet, policy) pairs from a corpus of realistic QuerySets
([`docs/gap-report.md`](docs/gap-report.md), regenerated in CI):

| Handing `str(qs.query)` to upstream's rewriter | Count |
| --- | ---: |
| Refused (Django names every column, so a hidden column anywhere on the model refuses the query) | 18 |
| Rewritten | 30 |
| Rewritten SQL executes as-is (`str(query)` interpolates parameters unquoted) | 16 |
| django-tolap prepares the same QuerySet | 46 |

None of that is a defect in upstream, which was never built for ORM-rendered SQL. It is the
gap. The report has a second table for SQLAlchemy statements compiled with literal binds
(the friendliest form for a string rewriter): entity selects are refused for the same reason,
and only column-list selects rewrite cleanly.

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
- [`CONTRIBUTING.md`](CONTRIBUTING.md): development setup and how changes are checked
- [`SECURITY.md`](SECURITY.md): reporting a vulnerability
- [`CHANGELOG.md`](CHANGELOG.md)

## License

Apache-2.0. Not affiliated with AWS; TOLAP is their project.
