# ADR 0015: Keeper tank before judging, and the demo video through the shared video pipeline

Status: accepted, 27 Nov 2026

## Context

The plan asks for at least 12 `lREACT` in the Keeper before judging, so the Lasna wards stay relit while the judges
look. On 27 Nov the Keeper held 7.09 `lREACT`; the deployer held 1.07 `lREACT` on Lasna and 0.032 ETH on Base Sepolia.
The faucet contract swaps Base Sepolia ETH for `lREACT` at 100 `lREACT` per ETH (0.01 ETH gave 1.0 `lREACT` again on
27 Nov, as on 23 Nov).

Separately, the shared checklist for our buildathon entries asks, from 30 Nov, that the demo video comes out of the
shared video pipeline (it writes `video/JANA.json` with the hash of the file the judges watch, and the voice line
from the owner's cloned voice). The current demo video was made by hand with the same method but outside that pipeline.

## Decision

1. Swap 0.01 ETH first (the small first try), then 0.015 ETH, and move the bridged `lREACT` to the Keeper with one
   plain transfer, keeping 0.2 `lREACT` on the deployer for gas. Result: Keeper 10.46 `lREACT`
   (`docs/evidence/E-007-keeper-topup.json`). The deployer keeps 0.007 ETH on Base Sepolia for gas; the Tank pays the
   Base Sepolia callbacks from its own balance and is not touched.
2. The 1.54 `lREACT` short of 12 (about 0.016 test ETH) goes to the owner in the hand-over message, with the faucet
   steps. The Keeper does not stop below 12; 12 is the margin for the judging weeks.
3. The demo video is rendered again through the shared pipeline before the hand-over message, so the owner uploads
   one video, once. The script, captures and figures stay as they are (`docs/hantar/SKRIP-VIDEO.md`).

## Rollback

The top-up cannot be undone and does not need to be: it is test currency. If the pipeline video is worse than the
current one, the current file stays the submitted video and the checklist line is answered with a written reason.
