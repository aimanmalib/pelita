# AI usage

Pelita was built for the Reactive Omni Buildathon, Set It and Forget It track. That track is open to people building
with AI coding tools, and this project was built that way. This file says what the AI did, what I did, and what has no
AI in it at all.

## What the AI wrote

I built Pelita with Claude Code, an AI coding agent that I directed. It wrote:

- the contracts in `src/` and their tests in `test/`;
- the scripts in `scripts/` and `ops/` (deploy, verify, census, indexer, uptime watch) and their tests in `tests/`;
- the page in `web/`, in English and Malay;
- this README, the documents in `docs/` and the submission text in `docs/hantar/`.

## What I did

I chose the problem, set the scope and the limits (testnet only, no proxy, no polling bot), and decided each trade-off
recorded in [docs/decisions/](decisions/). I own the test keys and the testnet funds, and I press Submit myself.

## What the AI did not produce

- **Measurements.** Every figure in [docs/measured.md](measured.md) is written by a script from chain data; the
  evidence files in [docs/evidence/](evidence/) hold the transaction hashes. Anyone can run the scripts again.
- **The product.** Pelita has no AI in it. The keeper reacts to a chain log with fixed rules.
- **The video pictures.** They are captures of the real page and of the chain explorers, not generated images.

## Voice and music in the demo video

The narration is an AI clone of my own voice (ElevenLabs). The end card of the video says so. The music is by Sascha
Ende (ende.app), CC BY 4.0.
