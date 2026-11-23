# 0002. Spike S1/S2 on Lasna: the debt event reaches a subscriber, and `depositTo` inside `react()` relights at once

- Status: accepted
- Date: 2026-11-23

## Context

PRD 4.4 asks two questions before the real deployment:

- **S1**: does the system contract's `BlacklistContract(address)` log reach a reactive contract that subscribed to it?
- **S2**: can that contract call `depositTo(target)` from inside `react()`, so that the system emits
  `WhitelistContract(target)` in the same transaction and `debt(target)` reads 0?

If S1 failed the fallback was F1 (a Cron subscription, PRD 7 R1); if S2 failed, F2 once, then the Base Sepolia path
would become the main one (PRD 7 R2, red team D2). The first test ETH arrived on 2026-11-23: 0.01 ETH on Base Sepolia,
against the 0.3 ETH asked for.

## Decisions

- **The spike runs on the real contracts, not a throwaway `SpikeKeeper`.** At 100 gwei on Lasna a Keeper deployment
  alone costs about 0.2 `lREACT`, and the first swap gave 0.9 `lREACT`. Paying for a spike contract and then for the
  real Keeper would have spent most of it. `scripts/spike/lasna_spike.py` drives the same idempotent `Deployer` as
  `scripts/deploy.sh` (ADR 0005) and writes the same `deployments/<chain>.json`, so P2b resumes from these contracts:
  Keeper (config constructor arguments), `setChain(Lasna)`, Beacon and the guarded Lantern on Base Sepolia, the
  guarded Flicker on Lasna created with 0.005 `lREACT` only (so it runs dry on its first reaction), `protect` of that
  Flicker, and a plain transfer to the Keeper (0.5 `lREACT`, RT-5). The control pair, the Tank, source verification and
  the full funding are left to P2b.
- **Swap 0.009 ETH, not 0.01.** The whole balance was 0.01 ETH; swapping all of it would have left nothing for the
  swap's own gas or the Beacon and Lantern on Base Sepolia. The faucet answered 1 ETH : 100 `lREACT` (0.009 ETH gave
  0.9 `lREACT`), as measured on 16 Nov, so PRD 7 R4 (faucet changed or empty) did not apply.
- **Result read from the chain, not typed.** `scripts/spike/spike_evidence.py --beat <tx>` follows the receipts' `refTx`
  links from the Beacon beat to the Flicker reaction to the Keeper reaction, decodes the logs and writes
  `docs/evidence/E-002-spike.json`. It exits 0 only when both S1 and S2 hold.
- **S1 holds.** The Flicker reaction to the beat carries `BlacklistContract(flicker)`; the next Lasna block holds the
  Keeper reaction whose `refTx` is that Flicker reaction.
- **S2 holds.** The Keeper reaction carries `WentDark`, `WhitelistContract(flicker)` from the system contract and
  `Refueled(amount = owed + refill)` in one transaction, and `debt(flicker)` reads 0 afterwards. F1 and F2 are not
  needed. **The Lasna path stays the main path**; the Base Sepolia series stays at the PRD size (15 outages).
- **`LowTank` on the first refuel is expected.** The Keeper holds less than `lowMark` (3 `lREACT`) until P2b tops it
  up to `funds.keeper_fund`.

## Notes

- The guarded Lantern on Base Sepolia has the same address as the guarded Flicker on Lasna. Both were created by the
  same deployer at the same nonce on two chains, so CREATE gives one address. Every file keys contracts by chain, so
  nothing mixes them, but readers of `deployments/*.json` should not take it for a mistake.
- Hashes, blocks, block times and amounts are in `docs/evidence/E-002-spike.json`; the public numbers will come from
  `docs/measured.md` once the series run (P3a, P3b), not from this file.

## Rollback

`release` the Flicker on the Keeper and `withdraw` the Keeper balance; nothing else depends on these contracts until
P2b. Deleting `deployments/*.json` would make `deploy.sh` create fresh contracts at full cost, so keep them.
