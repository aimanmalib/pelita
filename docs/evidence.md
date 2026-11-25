# Evidence index

Each factual sentence in `README.md` and on the live page, with the file or chain read behind it. Numbers are not
copied here. Each one points to the section of [measured.md](measured.md) that holds it, and that file is written by
`scripts/measure/report.py` from the evidence files only.

## How the network behaves

| Claim | Where | Source |
|---|---|---|
| A reactive contract that cannot pay gets a debt; the system contract emits `BlacklistContract` and stops calling it | README intro; page "How it works" | [E-001](evidence/E-001-chain-facts.json) (topics read on chain), [E-002](evidence/E-002-spike.json) (an outage transaction), [ADR 0003](decisions/0003-chain-facts-and-fork-tests.md) |
| `depositTo` needs no permission: anyone can relight any contract | README Usefulness; page dark list | [E-002](evidence/E-002-spike.json) (the Keeper, a separate contract, paid `Flicker`'s debt); fork test `test_Fork_ProxyDepositToCreditsReserves` in [test/fork/BaseSepoliaFork.t.sol](../test/fork/BaseSepoliaFork.t.sol) |
| A reactive transaction's receipt shows no fee; Lasna takes the bill from the contract's balance in the reaction's block | measured.md H5 | `billed_per_tx` in [scripts/measure/series.py](../scripts/measure/series.py); `reaction_billed_wei` per row in [E-005 Lasna](evidence/E-005-series-lasna.json) |

## What Pelita does

| Claim | Where | Source |
|---|---|---|
| The Keeper subscribes to `BlacklistContract` and `WhitelistContract` per protected contract, and has no Cron subscription | README intro, Integration, What already exists | `_subscriptions` in [src/PelitaKeeper.sol](../src/PelitaKeeper.sol) |
| On Lasna it pays the debt plus a refill with `depositTo` in the same reaction, and the contract is relit in that transaction | README Integration; page "Try it" step 3 | `_refuelLocal` in [src/PelitaKeeper.sol](../src/PelitaKeeper.sol); every guarded row of [E-005 Lasna](evidence/E-005-series-lasna.json) has `lit_tx` equal to `reaction_tx` |
| On Base Sepolia the Tank accepts `refuel` only from the callback proxy carrying the Keeper as sender | README Integration | `test_Refuel_OnlyProxy`, `test_Refuel_OnlyKeeperAsSender` in [test/PelitaTank.t.sol](../test/PelitaTank.t.sol) |
| `react()` and `refuel()` do not revert for an ordinary log | README Craft | `testFuzz_React_NeverRevertsForSystemLogs` in [test/PelitaKeeper.t.sol](../test/PelitaKeeper.t.sol), `testFuzz_RefuelNeverRevertsAndKeepsFloor` in [test/PelitaTank.t.sol](../test/PelitaTank.t.sol), [SECURITY.md](SECURITY.md) |
| Daily spend per ward is capped, unregistered addresses are never paid, refuels never break the floor | README Craft | invariants in [test/invariant/KeeperInvariant.t.sol](../test/invariant/KeeperInvariant.t.sol) |

## Measured on chain

| Claim | Where | Source |
|---|---|---|
| Lasna outages of the guarded ward, how many were relit, and how fast | measured.md H1 | [E-005 Lasna](evidence/E-005-series-lasna.json); repeat: `python3 scripts/measure/series.py record --side lasna` |
| Base Sepolia outages relit through a callback, and how fast | measured.md H2 | [E-005 Base Sepolia](evidence/E-005-series-base-sepolia.json); repeat: `python3 scripts/measure/series.py record --side base-sepolia` |
| The control ward without Pelita stays dark, with its debt read at the last block | measured.md H3; page fleet ("control: no Pelita") | `controls` in both E-005 files |
| Beats lost by the guarded Lantern against the control Lantern | measured.md H4 | `demo` in [E-005 Base Sepolia](evidence/E-005-series-base-sepolia.json) |
| Cost of one relight | measured.md H5 | `reaction_billed_wei` and `callback_fee_wei` in both E-005 files |
| How many contracts went dark, how many are still dark | README census table; page dark list | measured.md H8, [E-003](evidence/E-003-census.json); each row names the command that repeats it |
| The page shows the same census as `scripts/census.py` for the same block range | README census section | `h8_equal` in [E-003](evidence/E-003-census.json) |
| The page data is refreshed every two minutes | README census section | [ADR 0004](decisions/0004-census-and-indexer.md) (cron schedule), [ops/indexer.py](../ops/indexer.py) |

## Deployment history

| Claim | Where | Source |
|---|---|---|
| The first Lasna loop: outage, then `Refueled` and `WhitelistContract` in one transaction | README Deployment | [E-002](evidence/E-002-spike.json), [ADR 0002](decisions/0002-spike-lasna-loop.md) |
| One full loop on each path, with every hash and `refTx` | README Deployment | [E-004 first loops](evidence/E-004-first-loops.json) |
| The demo loop: `poke()` on Base Sepolia, `Flicker` on Lasna, `Lit` in `Lantern` | README Deployment | [E-004 demo loop](evidence/E-004-demo-loop.json) |
| The first demo pair asked for too little callback gas and the proxy refused every delivery | README Deployment | [E-004 refused](evidence/E-004-demo-loop-gas-refused.json), [ADR 0008](decisions/0008-callback-gas-floor.md) |
| Pokes are limited by a cooldown and a daily number, both read from the contract | README "Cause an outage yourself"; page "Try it" | [src/demo/Beacon.sol](../src/demo/Beacon.sol); constructor arguments in [deployments/base-sepolia.json](../deployments/base-sepolia.json) |

## The page

| Claim | Where | Source |
|---|---|---|
| The fuel gauge reads straight from the Lasna RPC in your browser; nothing passes through this site | page fuel gauge | [web/js/gauge.js](../web/js/gauge.js) (`rpcBatch` posts to the Lasna RPC named in `config/chains.json`, served beside the page) |
| The page is in English and Malay and is tested on WebKit iPhone 13 | README Craft | [web/lang/](../web/lang/), [scripts/web-smoke.py](../scripts/web-smoke.py) |

## Prior work

| Claim | Where | Source |
|---|---|---|
| Reactivate (2025) targets the previous version of Reactive Network and is tied to its legacy system contract address | README What already exists | Reactivate's public source, read 17 Nov 2026; the Omni system contract address Pelita uses is in [E-001](evidence/E-001-chain-facts.json) |
