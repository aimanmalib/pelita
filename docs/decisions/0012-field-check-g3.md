# ADR 0012: Field check at G3, other entries use the same debt event

Status: accepted, 27 Nov 2026

## Context

PRD 4.14 repeats a GitHub search and one read of the event's project list at G2 and G3. At G2 (22 Nov 2026) no active
contract on Lasna was subscribed to the debt events, and no repository described a tool that refuels reactive contracts.

At G3 (27 Nov 2026) the same searches found two repositories, created during this buildathon, that describe the same
approach as Pelita: a reactive contract on Lasna listens for `BlacklistContract`, pays a protected contract's debt plus a
top-up within a budget, and uses a callback for contracts on a destination chain. Both list transaction hashes on
Lasna and Base Sepolia. The one read of the event's project list was answered with a human-verification page, as at G2,
and was not retried.

## Decision

1. No pivot (PRD 4.14). Pelita's design, measurements and limits stay as they are.
2. Public text says plainly that other entries in this buildathon also listen for the debt event and pay the debt, and
   that Pelita's numbers are for Pelita only. It names no other participant or project (PRD 0.6, red line 3) and makes
   no claim to be the only or the earliest tool of its kind.
3. The comparison table in the README stays against designs that poll on a timer, which is a design choice we can
   state from our own code. We do not describe other entries' internals.

## Consequences

- The README "What already exists" section and the form text carry one sentence each about it.
- The names and links found are kept in the private field notes, not in the repository.
