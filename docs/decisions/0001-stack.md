# 0001. Stack: Foundry, Solidity 0.8.29, Python standard library

- Status: accepted
- Date: 2026-11-17

## Context

Pelita is a reactive contract on Reactive Lasna that refuels other reactive contracts when the network marks
them as in debt, plus a callback contract on Base Sepolia, a small static page and a read-only indexer.
The official library `reactive-lib-omni` targets Solidity `^0.8.29` and ships as a Foundry project.

## Decision

- Contracts: Foundry, Solidity 0.8.29, `evm_version = "cancun"`, optimizer 200 runs.
- `reactive-lib-omni` is a git submodule pinned to tag `v0.1.0`; `forge-std` is a submodule pinned to `v1.16.1`
  (the version that library itself pins). No code from either is copied into `src/`.
- No proxies, no `delegatecall`, no `selfdestruct`.
- Scripts that send transactions: Bash + `cast`, using a named Foundry keystore (`--account`) and a password file, so
  no key ever appears in argv, logs or this repository. Foundry is called as `$HOME/.foundry/bin/forge` / `cast`
  because non-interactive shells and cron do not load it into `PATH`.
- Reads, measurements and the indexer: Python 3.12 standard library only (no pip dependencies). Every HTTP request
  sends the `User-Agent` from `config/chains.json`; the public Base Sepolia RPC and Blockscout API answer 403 to the
  default `Python-urllib` agent.
- Values that may change (chains, billers, fees, refill sizes, caps, alert thresholds, intervals) live in
  `config/chains.json` and `config/pelita.json`, not in code.
- Offline gate: `scripts/gerbang-ujian.sh` (fmt check, build, unit tests without `test/fork/`, Python tests).

## Consequences

- Anyone with Foundry and Python 3 can build, test and re-run the measurements without installing packages.
- Fork tests against Lasna run as a separate task, not in CI.

## Rollback

If `reactive-lib-omni` changes its interface, keep the pinned tag and record the difference in a new ADR.
