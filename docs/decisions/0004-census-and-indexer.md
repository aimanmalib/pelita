# 0004. Census and indexer: one summary function, block cursors, Blockscout lag

- Status: accepted
- Date: 2026-11-17

## Context

PRD 4.5 and 4.6 ask for a key-less census of contracts that went dark (`scripts/census.py`) and a read-only indexer
(`ops/indexer.py`, cron every 2 minutes) whose page numbers must equal the census over the same block range (H8).

## Decisions

- **One summary function.** `census.summarize()` pairs `BlacklistContract` (dark) and `WhitelistContract` (lit) per
  address in chain order. `census.census_result()` wraps it with the block range, and both the script and the indexer
  call it. The indexer keeps the raw events it has seen plus a block cursor, so an incremental run and a single census
  over the same range give the same JSON (tested in `tests/test_indexer.py`).
- **Reproducible.** Ages are measured against the timestamp of the last block read, never the script's clock.
- **Lasna** is read with `eth_getLogs` on the system contract in windows of `get_logs_max_blocks`. Logs carry
  `blockTimestamp: 0x0`, so each distinct block's time is read once. Lasna prunes old blocks ("block not found"); the
  date-to-block search treats a pruned block as older than the start date.
- **Destinations** are read through the Blockscout logs API (the public RPC caps `eth_getLogs` at 201 blocks). Blockscout
  indexes behind the RPC tip, so a destination is read only up to `tip - index_lag_blocks` (`config/chains.json`;
  300 blocks on Base Sepolia, about one minute at the measured ~0.2 s per block). Events are de-duplicated by
  `(transaction, logIndex)`.
- **Start of the range** is `census.since_utc` in `config/pelita.json` (one day before the event opened, the same
  window as the pre-build measurement). `--from-block/--to-block` repeat any range.
- **Fleet** comes from `deployments/<chain>.json` (`keeper` or `tank`, `deploy_block`, `wards[]` with `role`
  `guarded`/`control`). No file = chain not deployed; the snapshot then has an empty `fleet`. Status reads are one
  JSON-RPC batch per chain. Pelita's own event topics live in `config/events.json`; a test checks each signature
  against `src/*.sol`.
- **Alerts** text lives in `config/pelita.json` (`alerts.text`). A kind is marked sent for the UTC day only when
  `notify.sh` returns 0, so a failed delivery is tried again next run. Control wards never alert.
- **Failures.** Any RPC or HTTP error ends the run with exit code 1, a failed line in `state/larian.jsonl`, and the
  previous snapshot left in place. No retry loop. The fifth failure in a row sends one warning.

- **Fields the page reads** (added with the schedule, 17 Nov): every fleet event carries `ts`, the block timestamp,
  read in one batch with the census block-time cache. `demo` holds the public Beacon (`chain`, `beacon`,
  `last_beat_ts`, `cooldown_seconds`) for "Try it yourself"; `last_beat_ts` and `cooldown_seconds` are read from the
  contract (`lastPublicBeat()`, `cooldown()`), not from config, because the owner can change the limits on chain.
  `demo` is `null` until a deployment file names a `beacon`.
- **Schedule.** User crontab, every 2 minutes:
  `jalan-jadual.sh PELITA-INDEKS -- /usr/bin/flock -n -E 66 state/indexer.lock /usr/bin/python3 ops/indexer.py`
  (absolute paths, output to `state/indexer.log`). Standard library only, so the system `python3` works under cron's
  `PATH=/usr/bin:/bin`. A run takes about 8 s with no fleet; `flock -n` skips a run while the last one is still going.
  The snapshot is written with `os.replace` in `state/public/`, which the site container mounts read-only as a folder,
  so the page never reads a half-written file.

## Rollback

The census and indexer are read-only. Removing the `PELITA-INDEKS` cron line stops the indexer; the page then shows the
last snapshot with its `generated_at` time.
