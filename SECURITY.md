# Security policy

Pelita is a buildathon entry that runs on testnets only: Reactive Lasna (chain 5318007) and Base Sepolia (chain
84532). The contracts are not audited. Do not deploy them with real money.

## Reporting a vulnerability

Please don't open a public issue. Use
[private vulnerability reporting](https://github.com/aimanmalib/pelita/security/advisories/new); it reaches only the
maintainer. Include the contract, the chain, and a transaction hash or a failing test if you have one. I aim to reply
within seven days.

## What is in scope

- `src/`: the Keeper and Tank contracts and the demo contracts.
- `scripts/` and `ops/`: deployment, verification, the census and the indexer. A path that could print, log or commit a
  private key or keystore password is a vulnerability.
- The page under `web/`: it has no wallet connection, cookies or third-party scripts, and a change that adds one is a bug.

## How the contracts limit spending

Who may call what, the per-refuel and per-day limits, the floor each contract keeps, and why `react()` and `refuel()`
never revert are written down in [docs/SECURITY.md](docs/SECURITY.md).
