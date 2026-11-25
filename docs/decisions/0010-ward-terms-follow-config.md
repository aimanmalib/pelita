# ADR 0010: Ward terms follow config; demo daily cap 40

Status: accepted, 25 Nov 2026

## Context

`PelitaKeeper.protect` fixes a ward's `refill`, `maxOwed` and `dailyCap`; there is no setter. Until now
`deploy.sh` only asked whether a ward was active, so a changed value in `config/pelita.json` never reached the chain.

The guarded demo Flicker on Lasna was protected with `dailyCap` 20 (`wards.demo.daily_cap`). Read from the Keeper on
25 Nov: `used` 3 in a window that opened at block time 1795617765. The H1 series (PRD 2.1) needs at least 30 outages,
and each outage costs about five Beacon beats, so the series would hit the cap and need a second day before G3.

## Decision

1. `Deployer.ensure_ward` reads the ward tuple. Same terms as config: nothing is sent. Different terms: it sends
   `release` and then `protect` with the config terms. Changing a value in `config/pelita.json` and running
   `scripts/deploy.sh` is now the way to change a ward.
2. A ward that is **dark** at that moment is left as it is, with a log line. A fresh ward starts lit; it would never
   see the blacklist that already happened, and the contract would stay dark. Run again once it is lit.
3. `wards.demo.daily_cap` goes from 20 to 40 for the demo wards (guarded Flicker and guarded Lantern).

## Consequences

- Re-protecting starts a new window with `used` 0. The owner can already do this by hand; the script only does it
  when config changed, and the `Released` and `Protected` events show it on chain.
- The public Beacon allows 40 beats per 24 h (`demo.beacon_max_beats_per_window`), about eight Flicker outages, so a
  cap of 40 never binds for public pokes. The bound on what one ward can take in a day is now
  `40 × (maxOwed + refill)` = 6 `lREACT` on Lasna; the Keeper is funded to 12 `lREACT` and keeps `selfFloor` for itself.
- Rollback: set `daily_cap` back to 20 and run `scripts/deploy.sh` while the ward is lit.
