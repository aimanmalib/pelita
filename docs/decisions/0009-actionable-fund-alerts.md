# ADR 0009: Fund alerts say what to do, how much and where

Status: accepted, 24 Nov 2026

## Context

The indexer sends one `tank_low` warning a day (ADR 0004) when the Keeper on Lasna holds less than `keeper.low_mark`
lREACT, or a destination Tank holds fewer than `alerts.base_tank_min_refills` refills. The old text only gave the balance
and "repeat the faucet step". It did not say three things the operator needs to act from a phone:

- whether the Keeper has **already stopped**: `PelitaKeeper` refuses every refill once its balance is under
  `amount + selfFloor` (`src/PelitaKeeper.sol`), so below `keeper.self_floor` nothing is relit any more;
- how much test ETH to send;
- to which address.

## Decision

`Indexer.tank_low_alert` builds the message from configuration only (`config/pelita.json`):

- `status`: `alerts.keeper_state.stopped` when the balance is under `keeper.self_floor`, otherwise `.running`.
- `eth_needed`: for the Keeper `(funds.keeper_fund − balance) / funds.lreact_per_eth`; for a Tank
  `funds.tank_fund − balance`. Rounded **up** to `alerts.eth_decimals` places, never below one step.
- `address`: `alerts.top_up_address`, the deployer that `scripts/funds.sh` and `deploy/deploy.sh` spend from.
  Without that key the `*_plain` texts are used, so a deploy-your-own install keeps working.

`funds.lreact_per_eth` = 100 is measured, not assumed: the faucet swap of 0.009 ETH returned 0.9 lREACT (E-002).
If the faucet rate changes, change that one value.

The alert frequency is unchanged (one per kind per day); only the wording changed.

## Consequences

- With the Keeper at 0.2673751 lREACT the warning reads "Keeper SUDAH berhenti … hantar 0.118 ETH ujian Base Sepolia
  ke 0xdCCA…3394". Covered by `FleetTest.test_tank_low_message_is_actionable`.
- The "Buat" sentence says the deployment run waits for that balance and then tops up the Keeper or Tank itself. That is
  true while the funded deployment step is still pending; once it is done, rewrite the text in `config/pelita.json`.
- Rollback: `git revert` the commit; the old single `tank_low` text is in git history.
