# ADR 0013: Census refreshed before submission, the earlier census stays

Status: accepted, 27 Nov 2026

## Context

The H8 census in `docs/measured.md` stopped at 16 Nov 2026 (Lasna: 154 outages, 116 contracts, 97 still dark). The page
reads the indexer snapshot, refreshed every two minutes, so by 27 Nov it showed several times those numbers. A judge
who opened the README and the page side by side would see two different counts without a reason.

The demo video (P3f) narrates the 16 Nov numbers. Rebuilding the narration for one line means a new voice take, a new
timeline and a new final mix, for a figure that was true for its range.

The first re-run on Base Sepolia also failed: `census.debts()` sent the debt reads in one batch of up to 50 calls, while
`sepolia.base.org` refuses more than 25 calls a second (`-32007`). `config/chains.json` already held `rpc_batch_max` and
`rpc_batch_pause_s` for this RPC, but the census ignored them.

## Decision

1. `census.py` batches debt reads and block-timestamp reads by the chain's `rpc_batch_max`, with `rpc_batch_pause_s`
   between batches (regression test `tests/test_census.py` `BatchLimitTest`).
2. A new census `docs/evidence/E-006-census.json` covers Lasna from the same start date to 27 Nov, equal to the page
   snapshot for the same block range. Base Sepolia is not in it: its long range is read through the Blockscout logs
   API, which answered HTTP 429 to every request from this host for 30 minutes (six tries, five minutes apart, and a
   single plain request). The Base Sepolia row stays at 16 Nov and the README says why. `E-003-census.json` is
   unchanged. A later census can add Base Sepolia as a new evidence file listed in `CENSUS_FILES`.
3. `scripts/measure/report.py` prints every census in H8, newest first, with its end time. The README and the form text
   quote the newest census; the README says the video quotes the earlier one.

## Rollback

Delete `E-006-census.json` and run `python3 scripts/measure/report.py`: H8 shows only the 16 Nov census again, and the
README figures test turns red until the README and form text quote it again.
