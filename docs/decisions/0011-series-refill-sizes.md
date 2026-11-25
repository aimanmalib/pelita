# ADR 0011: Refill sizes for the Base Sepolia series

Status: accepted, 25 Nov 2026

## Context

The H2 series (PRD 2.1) needs at least 15 outages of the guarded Lantern on Base Sepolia, each relit through a
Keeper reaction on Lasna and a Tank callback. Read from the chains on 25 Nov 2026 before this change:

- The guarded Lantern refill was 0.0002 ETH. Each beat's light callback takes about 6.3e11 wei from its proxy
  reserves (75 owner beats took 4.73e13 wei), so one refill lasts about 300 beats and 15 outages would need some
  4,500 beats.
- Every beat also drains the guarded Flicker on Lasna. With a refill of 0.05 `lREACT` it went dark about every five
  beats, and its ward had already used 30 of its 40 refills in the current window (`used` 30), so the series would
  stop at the Flicker's daily cap long before the Lantern reached 15 outages.

## Decision

1. `wards.base-sepolia.refill`: 0.0002 → 0.000005 ETH. One refill now lasts about eight beats.
2. `wards.lasna.refill`: 0.05 → 0.25 `lREACT`. The guarded Flicker goes dark about every 25 beats, so a 200-beat run
   stays well inside its daily cap of 40.
3. `scripts/deploy.sh` applied both (ADR 0010: release + protect while lit), and topped the Keeper back up to
   12 `lREACT` by plain transfer after swapping 0.025 Base Sepolia ETH on the faucet contract.

## Consequences

- What one beat costs does not change: the fee is per light or per reaction, not per refill. Only the size of each
  deposit changes, so how often a ward goes dark changes.
- H1 rows recorded before this change used a 0.05 `lREACT` refill; later Lasna outages use 0.25. The series file pairs
  each outage with its reaction by `refTx` either way, and latency does not depend on the amount.
- The ward bound per day is now `40 × (maxOwed + refill)`: 14 `lREACT` on Lasna (above the Keeper's 12, so the Keeper's
  own `selfFloor` is what stops it) and 0.04 ETH on Base Sepolia (the Tank holds 0.02 and its `maxPerRefuel` is 0.002).
  The public Beacon still allows only 40 beats a day, about two Flicker outages.
- Rollback: set both refills back (0.05 and 0.0002) and run `scripts/deploy.sh` while both wards are lit.
