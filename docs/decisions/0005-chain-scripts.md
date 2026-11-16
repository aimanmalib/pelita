# 0005. Chain scripts: Foundry sends every transaction, Python drives the order

- Status: accepted
- Date: 2026-11-17

## Context

PRD 4.5 lists `funds.sh`, `deploy.sh`, `deploy-your-own.sh` and `verify.sh`. `deploy.sh` must be idempotent, follow the
organiser's order (reactive contract first, then the callback contract with its address, then the wiring, then funding),
write `deployments/<chain>.json` and verify sources (Sourcify on Lasna, Blockscout on Base Sepolia). The key must never
appear in argv, logs or the repository (PRD 4.10).

## Decisions

- **Foundry sends, Python orders.** Every transaction is a `forge create` or `cast send` with a Foundry keystore
  (`--account pelita --password-file ~/.config/pelita/keystore.pass`, or `--keystore <file>`). The Bash entry points
  call a small standard-library Python driver (`scripts/lib/deployer.py`, `funds.py`) because reading and writing
  JSON and comparing on-chain state is fragile in Bash. `verify.sh` stays plain Bash so a reader can copy each `cast`
  line it prints.
- **Idempotent by reading the chain, not a step list.** Each step reads first: contract code at the recorded address,
  `chains(id).set`, `ward(id, target).active`, `Flicker.lantern()`, balances. A second run sends no transaction (tested
  on two anvil chains with the real chain ids). If a contract that another one points at is redeployed, the dependent
  contract is redeployed too; a changed number in config is reported and left to the setters.
- **Chain id guard.** Before any transaction the driver compares each RPC's `eth_chainId` with `config/chains.json`
  and stops on a mismatch, so a wrong RPC cannot send to another network.
- **Funding by plain transfer (RT-5).** Keeper and Tank are topped up to `funds.keeper_fund` / `funds.tank_fund`.
  Demo Flicker and Lantern are funded once, through the constructor, and never topped up: they are meant to go dark.
- **One Beacon for both demo pairs.** The guarded and control Flicker listen to the same Beacon, so both receive the
  same beats and the lost-beat comparison (H4) is like for like.
- **Verification never blocks a deploy.** A failed verification is recorded as `"verified": false` and retried on the
  next run.
- **deploy-your-own.sh** deploys Keeper and Tank only into `deployments/own/`, with the user's keystore name; Foundry
  asks for the password.

## Rollback

The scripts only add contracts. Funds come back with `withdraw(to, amount)` on Keeper and Tank (owner only).
Deleting a `deployments/<chain>.json` makes the next run deploy fresh contracts.
