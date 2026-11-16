# Build log

One line per working day.

- 2026-11-17 — Repository skeleton: README, license, pinned submodules (`reactive-lib-omni` v0.1.0, `forge-std` v1.16.1), Foundry config, chain and Pelita config, `IBiller` with selector tests, offline test gate, ADR 0001. `PelitaKeeper` (Lasna refuel inside `react()`, destination callback request, daily cap, two-step ownership) with a mock system contract and 46 unit tests, including boundary checks.
- 2026-11-17 (later) — `PelitaTank` (destination refuel through the callback proxy, never reverts, `Skipped` reasons 1–5), demo `Beacon`/`Flicker`/`Lantern`, keeper-to-tank payload test, three keeper invariants (checked against mutants), `docs/SECURITY.md`. Chain facts re-read on-chain (E-001, 44 checks; log range caps corrected to the measured 201/1001 blocks, ADR 0003) and 9 read-only fork tests against Lasna and Base Sepolia. Census of dark contracts (`scripts/census.py`: Lasna logs in capped windows, Blockscout for destinations, E-003) and the read-only indexer (`ops/indexer.py`: block cursors, batched status reads, atomic snapshot, once-a-day alerts; ADR 0004), tested offline on recorded chain replies.
