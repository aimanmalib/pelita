# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `PelitaKeeper` (Reactive Lasna): subscribes to the biller's `BlacklistContract` log for each protected contract and
  relights it from its own balance, with `depositTo` on Lasna or a callback to a destination tank. Per-refuel and
  per-day limits, a floor it never spends, and a reason code for every refusal.
- `PelitaTank` (destination chain): pays the callback proxy for a protected contract when the keeper asks.
- Demo contracts `Beacon`, `Flicker` and `Lantern`, so anyone can cause an outage with one transaction and watch it relit.
- Unit, invariant and read-only fork tests; `scripts/deploy.sh`, `deploy-your-own.sh`, `verify.sh` and `funds.sh`,
  tested against local anvil chains with the real chain ids.
- A census of contracts that went dark on Lasna and Base Sepolia, readable without a key (`scripts/census.py`), and an
  indexer that writes the page's snapshot every two minutes.
- The page at https://pelita.sasateguh.com in English and Malay.
- Community files, CI and an offline README link check.
