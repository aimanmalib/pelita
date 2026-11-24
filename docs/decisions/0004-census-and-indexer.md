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
- **Destinations** are read with `eth_getLogs` on the chain's RPC when the range fits in `rpc_logs_max_windows` windows
  of `get_logs_max_blocks` (`config/chains.json`; 20 × 201 blocks on Base Sepolia), and through the Blockscout logs
  API only for a longer backfill (the first run from `census.since_utc`, or catching up after a long outage). The
  range ends at `tip - index_lag_blocks` (300 blocks on Base Sepolia), because Blockscout indexes behind the RPC tip.
  Events are de-duplicated by `(transaction, logIndex)`, so both sources give the same census (tested).
  *Amended 17 Nov:* the first version called Blockscout on every 2-minute run; after a few runs the public API
  answered `429 Too Many Requests` from this host and four runs in a row failed. The 2-minute steps (about 60 blocks)
  now never call Blockscout.
- **Start of the range** is `census.since_utc` in `config/pelita.json` (one day before the event opened, the same
  window as the pre-build measurement). `--from-block/--to-block` repeat any range.
- **Fleet** comes from `deployments/<chain>.json` (`keeper` or `tank`, `deploy_block`, `wards[]` with `role`
  `guarded`/`control`). No file = chain not deployed; the snapshot then has an empty `fleet`. Status reads are one
  JSON-RPC batch per chain. Pelita's own event topics live in `config/events.json`; a test checks each signature
  against `src/*.sol`.
- **Alerts** text lives in `config/pelita.json` (`alerts.text`). A kind is marked sent for the UTC day only when
  `notify.sh` returns 0, so a failed delivery is tried again next run. Control wards never alert.
- **Failures.** An error while reading one chain's census (Blockscout's 429, a timeout) does not fail the run: the
  snapshot keeps that chain's last good census with `stale: true`, `stale_since` and `error`, and the run line in
  `state/larian.jsonl` lists it under `stale`. A failed Blockscout range is not tried again for
  `indexer.blockscout_retry_seconds` (`config/pelita.json`, 900 s); a failed RPC range is tried on the next run. The
  fifth stale run in a row for a chain sends one warning. Any other RPC or HTTP error (block number, fleet, filters)
  ends the run with exit code 1, a failed line, and the previous snapshot left in place. No retry loop. The fifth
  failure in a row sends one warning.

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

## Measured (17 Nov, after the 429 fix)

- Ten cron runs in a row, 04:50–05:08 UTC (`state/larian.jsonl` ts 1794891004–1794892083): all `ok`, none `stale`,
  5.5–8.6 s each. Before the fix, the five runs from 04:38 to 04:46 UTC failed with `HTTP Error 429`.
- Public snapshot `https://pelita.sasateguh.com/data/snapshot.json`, read twice right after: HTTP 200, age 15 s and 16 s.
- Base Sepolia RPC `eth_getLogs` on the callback proxy over 201 blocks answered for ranges ending 500, 3,000 and
  20,000 blocks behind the tip; Blockscout still answered 429 from this host at the same time.

## Measured (24 Nov): Base Sepolia public RPC 429

- `state/larian.jsonl` from 23 Nov 09:08 UTC: 462 runs, 152 failed (33 %); 147 of them `HTTP Error 429`, one Lasna
  `-32007 25/second request limit`, one 503, two timeouts. Longest failing streak 5, twice (two warnings). 18–22 Nov: 0–1
  failed runs a day.
- The failures began with the Base Sepolia deployment (23 Nov 09:27): the indexer now reads the fleet, its events and
  the demo Beacon on Base Sepolia every 2 minutes, about 6–9 requests a run to `sepolia.base.org`. In 20 instrumented
  `collect()` passes, the 2 failures were both 429 from `https://sepolia.base.org`; Lasna took 10–11 requests a run
  without a 429.
- Cause in code: only the census was isolated per chain. `latest_block()`, the fleet reads, the demo read and
  `rnk_getFilters` were not, so one 429 on one chain threw away every chain's fresh numbers, and the error named
  neither the chain nor the host.
- `https://base-sepolia-rpc.publicnode.com` (no key) answered `eth_chainId` = `0x14a34` (84532), 3 of 3 HTTP 200,
  0.56–0.79 s.

Decisions:

- **Per-chain isolation.** Each chain's reads run in `Indexer.chain_step`. A failure keeps that chain's last good
  census and fleet views marked `stale` (fleet alerts skip stale views), the other chains stay fresh and the snapshot
  is written. `state/larian.jsonl` lists the chain in `stale` and its error in `chain_errors`. Only a run where every
  chain failed is a failed run that keeps the previous snapshot.
- **One warning per failing chain.** `state.chain_stale[<chain>].runs` counts failed runs in a row. At
  `rpc_failures_before_warn` (unchanged) it sends the `rpc_failures` warning once, its `{error}` starting with
  `<chain> <host>:`.
- **Fallback endpoints, indexer only.** `rpc_fallback` (optional list) in `config/chains.json`; Base Sepolia lists
  publicnode. `pelitarpc.Client` tries the next endpoint on HTTP 429/5xx, a timeout or connection error, or a
  "request limit" reply (-32005/-32007). Each endpoint is tried once per call, with no sleep. After a refusal the
  client starts on the endpoint that answered for the rest of the run. A node error (pruned block, revert) does not
  move. When every endpoint refuses, the client raises `pelitarpc.Unavailable` (an `OSError`, not `RpcError`, so
  `debts()` cannot turn it into a dash), and the message names every host. The site CSP is still built from `rpc`
  alone, so the fallback never reaches the browser.
- Same pattern as viem's `fallback([http(a), http(b)])` transport, written again in the standard library (ADR 0001).
- Regression tests: `tests/test_indexer_rpc_limit.py`. They failed on `f39ec90`: a 429 on Base Sepolia made `run()`
  return 1, and no warning named the chain.

After 6.5 hours live (24 Nov, 00:34–07:10 UTC, runs with `ts >= 1795480419`, the fix's commit time): 200 runs,
200 `ok` (100 %, against 67 % before), longest failing streak 0, no run with `base-sepolia` in `stale`, no
`chain_errors`; `state/indexer.json` holds no `chain_stale` entry and `failures` is 0. The run log does not record
whether the fallback answered a call, so these numbers do not separate "the fallback absorbed a 429" from "no 429
came". Counted with:

```sh
python3 -c 'import json; r=[json.loads(l) for l in open("state/larian.jsonl") if l.strip()]; r=[x for x in r if x["ts"]>=1795480419]; print(len(r), sum(x["ok"] for x in r), sum("base-sepolia" in x.get("stale",[]) for x in r), sum("chain_errors" in x for x in r))'
```

## Rollback

The census and indexer are read-only. Removing the `PELITA-INDEKS` cron line stops the indexer; the page then shows the
last snapshot with its `generated_at` time. To undo the 24 Nov per-chain isolation and fallback, `git revert` its commit
(cron runs the old code on its next run). To drop only the fallback, remove `rpc_fallback` from `config/chains.json`.
