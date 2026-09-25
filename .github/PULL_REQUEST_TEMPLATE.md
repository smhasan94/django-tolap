## What

<!-- One or two sentences. Link the issue if there is one. -->

## Why

<!-- The behaviour before, and why this is the right change. -->

## Checks

- [ ] `make check` passes locally
- [ ] Tests cover the change; pushdown changes include a differential test
- [ ] Nothing falls back to a looser SQL filter or skips the post pass
- [ ] `CHANGELOG.md` updated if user-visible
- [ ] `docs/decisions.md` entry if this picks between semantically different options
