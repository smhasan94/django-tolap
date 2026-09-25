# Security

`django-tolap` and `sqlalchemy-tolap` sit on an access-control boundary: they decide which
rows and columns an AI agent's tool receives. A bug that returns data a policy hides is a
vulnerability, even when TOLAP's own post-execution pass would normally catch it.

## Reporting

Please do not open a public issue for a suspected vulnerability. Use GitHub's private
vulnerability reporting on this repository ("Security" tab, "Report a vulnerability").
Include the policy, the QuerySet or `Select`, the database vendor and version, and what
came back.

Expect an acknowledgement within a week. Fixes ship as a patch release with a changelog
entry crediting the reporter unless they ask otherwise.

## Scope

In scope:

- Pushdown that returns rows or columns the post pass alone would not (a differential
  failure).
- Pre-execution checks that can be bypassed: signature or expiry verification, object
  access, referenced-column checks, write gating in the DRF mixins.
- Policy store behaviour that lets an assignment resolve to more than the most restrictive
  merge.

Out of scope here, report upstream instead:

- The TOLAP policy schema, resolution and masking semantics
  (`tolap-core`, `tolap-store`, `tolap-mcp`): https://github.com/awslabs/tolap/security.

## Supported versions

Only the latest 0.x release receives fixes.
