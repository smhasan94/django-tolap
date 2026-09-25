# django-tolap (working name)

Django and SQLAlchemy data-layer adapters for AWS TOLAP (Tool-Object Level Access
Protocol, github.com/awslabs/tolap, Apache-2.0). TOLAP enforces object-level access
control on what an AI agent's tool returns: visible tables/columns/rows, field masking,
result limits. Upstream ships Python packages `tolap-core`, `tolap-store`, `tolap-mcp`.

## What we build

1. QuerySet enforcement (Django): compile TOLAP row filters to `Q`, restrict selected
   columns, refuse denied models before any query, apply result limit via slicing.
   Pushdown is an optimization; TOLAP's post-execution pass always runs afterward.
2. Differential correctness: pushdown + post-pass == post-pass alone. Upstream shared
   fixtures plus Hypothesis property tests. Untranslatable filters fall back to
   post-pass only, never to a looser SQL filter.
3. Django-model policy store implementing TOLAP's `PolicyStore` protocol, registered in
   Django admin, with migrations.
4. DRF serializer/viewset mixin applying TOLAP masking to endpoints used as agent tools.
5. Tool helper decorator/context manager: resolve context, verify signature, enforce.
   Works alongside TOLAP's framework integrations, does not replace them.
6. SQLAlchemy adapter (after Django): same pushdown for `Select`, same differential tests.
7. Example app + benchmark at ~1M rows: SQL emitted with/without pushdown, rows
   fetched, memory, latency. README headline.
8. Upstream proposal drafted to `docs/upstream-issue.md`, then halt for the owner to post.

## Constraints

- Never fork or vendor TOLAP. Depend on published packages. If something needed is not
  public, halt.
- Fail closed everywhere the TOLAP spec says to.
- License Apache-2.0 unless a reason to recommend otherwise is found.
- Top priority: time-to-first-value. Small, excellent, installable v0.1 usable within
  five minutes of reading the README, no infrastructure for the core use case. Fewer
  features done well over breadth.

## Standing rules (every phase)

1. **Halt on questions and gaps.** STOP and ask before continuing whenever anything is
   ambiguous, missing, or contradictory, or when something learned changes the plan
   (upstream already does part of this, an API differs from assumptions, requirements
   conflict). Every halt gives: the question and why it matters; the recommended
   approach with reasoning; one to three alternatives with trade-offs. Wait for the
   answer. Record each answer in `docs/decisions.md` (date, question, options,
   decision, rationale), then commit and push.
2. **Git.** Work on `main` only. No branches, no PRs. Commit early and often in small
   logical commits (one story or less). Push to `origin main` after every commit.
   Messages: short imperative summary line plus optional body. Never include a
   `Co-Authored-By` trailer, a "Generated with Claude Code" line, a session link, or
   any other AI attribution. `.git/hooks/commit-msg` strips these as a safety net.
3. **Verify before relying.** Check every external library, spec, API, or file format
   against current docs or source before building on it. If reality differs in a way
   that matters, halt (rule 1).
4. **Tests gate commits.** Write tests alongside code. Run test suite, linter, and type
   checker before each commit. Never commit red.
5. **Don't publish.** Never publish packages, create releases or tags, post to external
   sites, or change repository settings. Prepare everything, then halt and hand over.
6. **Track progress in the repo.** Keep every epic and story status current in
   `docs/03-epics.md` (todo / in progress / done / reviewed) so work resumes cleanly
   after a context reset.

## Decisions expected from the owner (halt when each comes up)

- Package naming (check PyPI/GitHub collisions; `tolap-django` could look official).
- Repo layout: monorepo with separate Django and SQLAlchemy packages, or separate repos.
- Supported versions of Python, Django, SQLAlchemy.
- Schema mismatches: policy references columns/models absent from the Django schema.
- Store timing: Django-model store in v0.1 or v0.2.

## Phase sequence (strictly in order; a phase starts only after the previous one is committed and pushed)

- **Phase 0: Setup.** Confirm git repo on `main` with pushable `origin`. Install the
  `commit-msg` hook. Write this file. First commit and push. Confirm the commit message
  has no attribution.
- **Phase 1: Overview → `docs/01-overview.md`.** Research the landscape first. Cover
  the problem (who, what goes wrong, worked example), existing solutions and where they
  fall short (with links), how the project works (architecture, components, data flow,
  design decisions and rejected alternatives, trust boundaries, threat model), how
  developers use it (install, five-minute quickstart, integration examples,
  configuration), non-goals, success signals. Halt if research shows something already
  solves this well.
- **Phase 2: PRD → `docs/02-prd.md`.** Goals/non-goals, personas, numbered FRs with
  acceptance criteria, NFRs (performance, security, compatibility, dependency budget),
  public API surface, v0.1 scope vs later, open questions. Halt on any open question
  that blocks v0.1.
- **Phase 3: Epics → `docs/03-epics.md`.** Group FRs into epics; stories of about a
  day each with acceptance criteria, FR IDs, dependencies. Order by dependency and
  time-to-first-value; first epic ends installable and demoable.
- **Phase 4: Planning → `docs/plans/epic-NN-<slug>.md`.** Use the `plan` skill per
  epic, in order, before code: files, interfaces, test strategy, sequencing, risks.
- **Phase 5: Implementation.** Epic by epic, story by story, per the plans. Re-read and
  update each plan before starting its epic. Commit and push after each story. Keep the
  README quickstart working at every step.
- **Phase 6: Review.** After each epic, run code-review in low mode on that epic's
  changes. Fix issues, rerun tests, commit, push. Mark the epic "reviewed" in
  `docs/03-epics.md`, then return to Phase 5 for the next epic.

## Current status

See `docs/status.md` for where the build stands, what waits on the owner, and the backlog.

## Repo conventions

- Python tooling: `uv`, `pytest`, `ruff`, `mypy`.
- Docs live in `docs/`. Decisions in `docs/decisions.md`. Plans in `docs/plans/`.
