# Draft: GitHub issue for awslabs/tolap

*Not posted. The repository owner posts this by hand.*

**Title:** ORM adapters for Django and SQLAlchemy (`django-tolap`, `sqlalchemy-tolap`) — link or host?

---

Hi TOLAP team,

Thanks for open-sourcing TOLAP. I have been building data-layer adapters for it and would like
to ask whether you would link to them from the integrations list, or host them under
`awslabs`.

## What they are

- **`django-tolap`** ([repo](https://github.com/smhasan94/django-tolap)) — TOLAP policies
  managed in Django admin and enforced on QuerySets. Depends on the published `tolap-core`
  and `tolap-store` 1.0.0; nothing is vendored or reimplemented. Specifically:
  - `enforce(queryset, context)`: verifies the signed context, runs the pre-execution checks
    (`canQuery`, `validate_access` for every table the query touches, referenced columns
    against hidden/allowed sets, refusal rather than narrowing), pushes row filters into `Q`
    objects, the projection into `.values()` and `maxResults` into a slice, executes, then
    runs `apply_result_pipeline`. Two modes mirroring `SqlEnforcementMode`
    (`rewriteAndPost`, `postOnly`); no rewrite-only mode.
  - `DjangoPolicyStore`: your `PolicyStore` protocol on Django models, resolution delegated
    to `tolap_core.resolve`, admin registration with validation through
    `deserialize_policy_definition`, schema-drift warnings, resolve preview, audit log.
  - A `@tolap_tool` decorator and Django REST Framework mixins (`validate_write` gates
    writes; the target row is fetched under the policy first).
- **`sqlalchemy-tolap`** — the same for SQLAlchemy `Select`, sharing the test harness. In
  progress.

## Why an ORM adapter rather than the string rewriter

Your Python rewriter works on SQL text and your docs already say to use `postOnly` when an
ORM owns the SQL. I measured what happens when Django-rendered SQL is handed to it anyway
([gap report](https://github.com/smhasan94/django-tolap/blob/main/docs/gap-report.md)):

- Django renders a default projection as an explicit column list, so any hidden column on
  the model makes `validate_query` refuse the query (18 of 48 QuerySet/policy pairs refused
  outright in the corpus).
- Injected predicates are unqualified (`"region" = ...`), ambiguous once a join is present.
- `str(qs.query)` interpolates parameters unquoted, so most rewritten statements do not
  execute.

With the adapter the same 48 pairs all prepare. At 1,000,000 rows on PostgreSQL 17, an
analyst policy (`region = us-east`, `status <> deleted`, `maxResults 500`) fetches 500 rows
in 18 ms with pushdown versus 1,000,000 rows in 6.3 s and about 1.2 GB peak memory without
(your threat model's D2). Rows returned are identical in both modes.

## How faithfulness is proven

- Every case in `fixtures/enforcement/apply-row-filters-all-operators.json` and the four
  `fixtures/integration-scenarios/postgres-*.json` / `permissions-and-limits.json` files runs
  through both modes on SQLite and PostgreSQL and must agree with each other and with the
  fixture's expectations. Fixtures are copied verbatim from a pinned commit.
- A Hypothesis property (generated policies over all sixteen operators including null and
  type-mismatched values, hidden/allowed/masked sets, limits; generated rows with nulls;
  joins, annotations, subqueries, slices) asserts `rewriteAndPost == postOnly` on both
  databases, 500 examples per CI run.
- Translation rules are per database vendor and stricter than the string rewriter where a
  faithful form does not exist: string equality is not pushed on MySQL (case-insensitive
  collations), string ordering is not pushed on PostgreSQL (locale collation), `like` only
  where `LIKE` is case-sensitive, and a policy value whose Python type the driver would not
  return for that column is never pushed.
- Store conformance: `fixtures/merge-scenarios` and `fixtures/assignments` resolved through
  `DjangoPolicyStore` and `InMemoryPolicyStore` produce byte-identical `serialize()` output.

## Two things you may want to know

1. `hash` masking is not idempotent, so a tool that already returned hashed pseudonyms and is
   then post-passed again by `execute_with_enforcement` gets them hashed twice. The adapter's
   docs recommend `pre_execute` for the call plus the adapter's enforcement for the data. If
   the wrapper ever grows a way to declare "this result is already enforced", I would use it.
2. PyPI has 1.0.0 (2026-08-11) while the repository is at 1.1.0 and its README says the SDKs
   are not on any registry. The adapter pins `tolap-core>=1.0,<2` and runs a CI leg against
   `main` to catch drift. A note on the intended release channel would help downstream
   packages.

## The ask

Would you link the adapters from the integrations list, or prefer to host them (I would
transfer or contribute them under Apache-2.0 either way)? Happy to align naming, structure or
test conventions with whatever you prefer.
