# 0003. Chain facts re-read on-chain; log range caps; fork tests run on a real fork

- Status: accepted
- Date: 2026-11-17
- Number 0002 is kept for the delivery spike (S1/S2), which needs test funds.

## Context

Every address, topic, selector, fee parameter and RPC limit in `config/chains.json` was copied from a measurement
made before the event code existed. Each one is re-read from the chains by `scripts/spike/readonly.sh`, which writes
`docs/evidence/E-001-chain-facts.json` (44 checks: topics and selectors recomputed with `cast`, chain ids, biller code,
fee getters `_gasPriceCoeffPer1000` / `_extraGas` / `_maxChargeGas`, gas price, faucet code, `eth_getLogs` range caps,
the live `trigger` selector and log order of the newest blacklisting, Lasna RPC CORS, and the receipts of two earlier
observed blacklisting → reaction pairs).

## Findings that changed config

- `eth_getLogs` range caps are inclusive block counts one higher than first noted. Measured by bisection with an
  `address` filter: Base Sepolia accepts 201 blocks (`toBlock - fromBlock = 200`) and refuses 202 with HTTP 413;
  Unichain Sepolia accepts 1001 and refuses 1002 with HTTP 400. Lasna accepts 30000 and refuses 30001.
  `get_logs_max_blocks` now holds the measured inclusive count (201, 1001, 30000), and E-001 checks both sides of
  each cap on every run, so a provider change shows up as a failed check instead of a silent gap in the indexer.

## Findings that confirmed config

- All four topics, the five named selectors and the `trigger` selector (`0xcebbda8d`, read from the input of the
  newest blacklisting transaction) match.
- Blacklisting transactions emit `PaymentFailure` then `BlacklistContract` on the system contract.
- Fee parameters on the Lasna system contract and the three destination proxies match the config.
- The Lasna RPC reflects the page origin in `access-control-allow-origin`, so the page can read it directly.
- Both earlier pairs: the reaction receipt carries `refTx` = the blacklisting transaction, `rnkTxType` `r`,
  status 1, one block later. This is read-only evidence for S1; the spike itself still runs (it also answers S2).

## Fork tests

The plan allowed `eth_call` + `stateOverride` if the RPC could not serve a fork. It can: `forge test --fork-url`
works against both the Lasna and Base Sepolia public RPCs, so `test/fork/` uses a real fork with `vm.deal` and
`vm.prank`. `scripts/spike/fork-tests.sh` picks a contract that is dark at run time (newest `BlacklistContract`
target with `debt > 0`), so no third-party address is pinned in test code. These tests are not part of CI or the
offline gate because they depend on live state.

## Rollback

Set `get_logs_max_blocks` back to 200 / 1000 (one block of margin) if a provider tightens the cap; E-001 will
report which side of the cap moved.
