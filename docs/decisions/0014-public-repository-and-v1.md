# ADR 0014: Public repository, CI back on, release v1.0.0

Status: accepted, 27 Nov 2026

## Context

The buildathon asks for a public, open-source repository at submission. The repository was private while it was built.
Before it could open, the patent policy check for this project had to pass; it did (`status dilepaskan`, not blocked).

The `ci` workflow had been disabled by hand on GitHub while the repository was private, so pushes after 23 Nov had no
CI run. Nothing in the repository recorded why. Actions minutes are free for public repositories.

## Decision

1. The repository is public, with private vulnerability reporting on (the route `SECURITY.md` names), a description,
   the live page as homepage, and six topics.
2. The `ci` workflow is enabled again and run on `main`; the README badge reads its latest result.
3. `v1.0.0` is tagged on the commit that holds this record, and the GitHub release is built from a clean clone of that
   tag (`git archive`), so it holds only tracked files.
4. `docs/AI_USAGE.md` states what the AI wrote and what it did not, next to the README's AI disclosure.

## Rollback

Make the repository private again from the GitHub settings (the release and tag stay). Disable the workflow with
`gh workflow disable ci.yml`. A later fix after submission is not possible: the repository is frozen until results.
