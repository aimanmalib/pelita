# Build log

One line per working day.

- 2026-11-17 — Repository skeleton: README, license, pinned submodules (`reactive-lib-omni` v0.1.0, `forge-std` v1.16.1), Foundry config, chain and Pelita config, `IBiller` with selector tests, offline test gate, ADR 0001. `PelitaKeeper` (Lasna refuel inside `react()`, destination callback request, daily cap, two-step ownership) with a mock system contract and 46 unit tests, including boundary checks.
- 2026-11-17 (later) — `PelitaTank` (destination refuel through the callback proxy, never reverts, `Skipped` reasons 1–5), demo `Beacon`/`Flicker`/`Lantern`, keeper-to-tank payload test, three keeper invariants (checked against mutants), `docs/SECURITY.md`.
