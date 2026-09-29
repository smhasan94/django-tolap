# Draft: GitHub issue for awslabs/tolap

*Not posted. The repository owner posts this by hand.*

**Title:** ORM adapters for Django and SQLAlchemy (`django-tolap`, `sqlalchemy-tolap`) — link or host?

---

Hi TOLAP team,

Thanks for open-sourcing TOLAP. I have been building data-layer adapters for it and would like
to ask whether you would mention them alongside the integration examples in your README, or
host them under `awslabs`.

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
- **`sqlalchemy-tolap`** (same repo, `packages/sqlalchemy-tolap`) — the same checks,
  pushdown rules and post pass for SQLAlchemy 2.x `Select` statements, sharing the test
  harness and the differential proof below. Entity selects are the default projection;
  `text()`, `literal_column()`, derived tables and set operations are refused.

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

Would you mention the adapters alongside the integration examples, or prefer to host them (I would
transfer or contribute them under Apache-2.0 either way)? Happy to align naming, structure or
test conventions with whatever you prefer.

---

## Maintainer reply (2026-09-29)

phspies answered on #31 the day TOLAP 1.2.0 was tagged. Summary, each point verified
against the tag and the linked issues:

- Adapters listed in the README under "Community integrations" (#35, #41). Hosting under
  `awslabs` undecided; they will follow up on #31.
- Point 1 (double hash): `EnforcedResult.for_context(data, context)` (#33, #40).
  `execute_with_enforcement` skips the result pipeline for it; honoured only under
  signature enforcement with a marker naming the context's exact signature. Skips masking
  and the size ceiling; row filters, hidden/allowed projection, `maxResults` and tag rules
  still run. A claim, not proof: only after `apply_result_pipeline` ran.
- Bare-name fallback (our 0.2.0 comment): filed #32, fixed #37. `allowedFields` had the same
  cross-object hole: #36, #38. SQL pre-check now resolves every reference (#39),
  `validate_query_references` exported, unresolvable constructs refused.
- Point 2 (release channel): #34, still open. PyPI still 1.0.0.
- Asked us to check three behaviour changes on our upstream-main leg: dropped rows on
  ambiguous or conflicting lookups, `*.name` allowing only bare `name`, stricter raw SQL.

## Reply draft (owner posts; do not post from the tool)

Thanks for the fast turnaround, and for the README listing.

**Behaviour changes.** Our upstream-`main` CI leg ran against main at `6a4cc0d` (1.2.0
plus the README and examples commits): UPSTREAM_MAIN_RESULT. The adapters already key
every column `object.field` and resolve each filter to exactly one column before the post
pass, so the new qualified lookup is the path they were written for.

**`EnforcedResult`.** This is exactly the shape I hoped for. Plan on our side, once 1.2.0
is installable from PyPI: `@tolap_tool` and the DRF mixins return
`EnforcedResult.for_context` only after `apply_result_pipeline` has run (never on pushdown
alone), the double-hash test flips to asserting a single hash, and the "use `pre_execute`
for the call" note in our README goes away. Until #34 resolves we stay pinned to
`tolap-core>=1.0,<2`, which today means 1.0.0, so the adapters keep the old composition.

**Fixtures.** We will refresh our verbatim copy of `fixtures/` to the 1.2.0 commit and run
`already-enforced-results.json`, `row-filter-qualified-lookup.json`,
`allowed-fields-qualified.json` and `sql-multi-table.json` through both adapters in the same
differential harness, and report anything that disagrees.

**Hosting.** No preference; whichever is less work for you. If it stays community-hosted, I
will keep the README's install snippet and the version table pointing at the upstream
release each adapter is tested against.
