# sqlalchemy-tolap

**TOLAP policies enforced on SQLAlchemy `Select` statements with ORM-native pushdown.**

[TOLAP](https://github.com/awslabs/tolap) (Tool-Object Level Access Protocol, AWS,
Apache-2.0) decides what an AI agent's tool may *return*: which tables, columns and rows,
how fields are masked, how many results. `sqlalchemy-tolap` enforces a signed TOLAP
context on a SQLAlchemy 2.x `Select` before it runs, and applies TOLAP's own
post-execution pass afterwards.

- **Pre-execution checks.** Signature and expiry, `canQuery`, object access for every table
  in the statement, referenced columns against hidden and allowed sets. Refuses rather than
  narrows.
- **Pushdown.** Row filters become `WHERE` clauses, the result limit a `LIMIT`, hidden
  columns leave the projection. Only where the dialect's semantics match TOLAP's; anything
  else is left to the post pass and reported, never approximated.
- **Differential proof.** Pushdown plus post pass returns the same rows as post pass alone,
  on SQLite and PostgreSQL, against upstream's fixtures and a Hypothesis property.

## Install

```bash
pip install sqlalchemy-tolap
```

Python 3.11+, SQLAlchemy 2.0 or 2.1. Pulls `tolap-core` from PyPI.

## Usage

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

Entity selects (`select(Patient)`) are the default projection; named columns and labels are
explicit references. `text()`, `literal_column()`, derived tables in `FROM` and set
operations are refused. `enforce(..., mode="postOnly")` skips the pushdown but not the
checks or the post pass.

Design notes, the vendor rules and the gap measurement against upstream's string rewriter
are in the [repository README](https://github.com/smhasan94/django-tolap#readme).

## License

Apache-2.0. Not affiliated with AWS; TOLAP is their project.
