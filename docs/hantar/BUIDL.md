# Pelita: submission form text

The text for each field of the DoraHacks submission form, in English. Every figure is from
[docs/measured.md](../measured.md); every address is from [`deployments/`](../../deployments/); the full-loop hashes are
the first loop of each path in the README. `tests/test_hantar_figures.py` checks all three.

## Name

Pelita

## Vision

Reactive contracts go dark when their gas money runs out, and no alert goes out. Pelita hears the network's own debt
event and refuels the contract in seconds. No polling bot. No babysitting.

## Description

<!-- description start -->
## What it is

Pelita keeps reactive contracts lit.

A reactive contract pays for every reaction. When its balance hits zero, Reactive Network stops calling it. There is no
alert. It stays dark until someone notices.

Pelita is a reactive contract that watches for that exact moment. Reactive's system contract emits `BlacklistContract`
when a contract goes into debt. Pelita subscribes to that event for the contracts I care about and refuels them from
one tank. On Lasna it calls `depositTo` in the same reaction. On Base Sepolia it sends a callback to a small tank
contract that pays the callback proxy.

"Pelita" is Malay for an oil lamp.

## Why I built it

I am not a developer. I build with AI coding tools and I run several projects at once. I cannot watch a dashboard. I
want to fill one tank and forget it.

I measured the problem on chain first. Since November 4, 2026, my census counted 116 contracts on Lasna that went dark
this way, 154 outages in all. 97 of them were still dark at the end of the counted range.

## What you can check

- 52 outages of my demo contract on Lasna and 17 on Base Sepolia, each caused on purpose and each relit. Median time
  from dark to lit: 1 s on both chains, by block timestamps. Every hash is in the repo.
- A control contract with no Pelita. When last read it had been dark for 32.1 hours and still owed 0.0131257 `lREACT`.
- What a relight costs Pelita: a median 0.017684 `lREACT` for the Keeper's reaction on Lasna, and 0.000000695094 ETH
  for the callback on Base Sepolia.
- A live page: my fleet, a fuel gauge for any contract, and the contracts that are dark right now.
- You can cause an outage yourself with one `cast send` on Base Sepolia. Pelita relights it while you watch.

## Why it needs Reactive

Without Reactive this is a bot that polls balances. That is the keeper reactive contracts were meant to remove. Pelita
is triggered by the network's own event, filtered to one address, so nothing is billed while nothing goes dark.

## Limits

Testnet only. One owner per deployment. Events that arrive while a contract is dark are lost. Pelita makes that window
short, not zero. Prior art: Reactivate, a 2025 winner, solved this for the previous network version with a different
design. Other entries in this buildathon also listen for the debt event and pay the debt; the numbers above are for
Pelita only.

## AI disclosure

I built this with Claude Code: the contracts, tests, scripts, page and README were written with an AI coding agent that
I directed. The chain measurements come from scripts in the repo and anyone can run them again. The narration in the
video is an AI clone of my own voice (ElevenLabs).
<!-- description end -->

## Form questions

### Deployed contract addresses, and which network?

| Contract | Network | Address |
|---|---|---|
| PelitaKeeper | Reactive Lasna testnet | `0xfD15ABB7DeFb73B10942BB1207B1e24cCfA138Fa` |
| Flicker, guarded | Reactive Lasna testnet | `0xa4c7BDDbA75955C915FC38753037e82c32d240B2` |
| Flicker, control (no Pelita) | Reactive Lasna testnet | `0x42CdFE8C54c2395eaca20ba5cdaFfFbDf6061458` |
| PelitaTank | Base Sepolia | `0xeDF0239e5661097228a570B8Ad05707562886bCf` |
| Beacon | Base Sepolia | `0x90832735001E807Dde8CD0f5181F07b85BEDb7a4` |
| Lantern, guarded | Base Sepolia | `0xF5f37156f2C3414735E6085aAeCC9940e6C77904` |
| Lantern, control (no Pelita) | Base Sepolia | `0xc8F9A1F1922e734ab3a4f86DAbF7788A0A9EE95b` |

Source is verified for each one; the links are in `deployments/`.

### Transaction hashes showing the full loop

Lasna, one path:
- The guarded Flicker goes dark (`BlacklistContract`): `0x07de1f4ff24a5eb8c58e982dadcfcab67905b1eed0c3cfd0fcfc4be5eca6d656`
- The Keeper reacts, with `Refueled` and `WhitelistContract` in the same transaction: `0xac7d0ec7db5a217fb92db3628e5e670427e873305c9974c9b0227325937212c6`

Base Sepolia, across chains:
- The guarded Lantern goes dark on the callback proxy: `0x43881c5c15012332a5e6604cb39a698e640cb18e880a646d6aa0da2dbd692729`
- The Keeper reacts on Lasna (`RefuelRequested`): `0x239574bc45f48d8c0326f0bc08ed05966e16cf4112ecfb09010293711bc562f8`
- The Tank's `refuel` callback pays the debt (`Refueled`, `WhitelistContract`): `0x602cdda51c889be52834b6b638ad46b5939ebc84cf62d324e36480564cfce1fb`

Demo loop:
- `poke()` makes the Beacon emit a `Beat`: `0xb001f0f3d765a6f01ef6fbf28e46c5fb2df346c89c69528750df614fe07c48ef`
- The Flicker reacts on Lasna: `0x597fc3964da8c294efa1301f2a1dabf7e20c3aba9f0f37f67bfe9315aff43293`
- The `Lit` callback lands in the Lantern: `0x70f8bd06b89fa6093a952e8f4a260aa77d98e766026de266d950446fc941bece`

Every later outage and relight is listed with its hashes in `docs/measured.md`.

### Latency (Every Second Counts)

Not in that track. For reference, dark to lit took a median of 1 s on Lasna and 1 s on Base Sepolia, by block
timestamps. Method and every hash: `docs/measured.md`.

### First time building with Reactive?

First time building with Reactive. Not my first smart contract.

### What was the hardest part?

Getting the first callback through. The Base Sepolia callback proxy needs more gas left than my first demo contract
asked for, and the network sends each delivery with exactly the gas the reactive contract requested, so that contract
could never be delivered. I found it by replaying a delivery with `eth_call` on the block before it, then raised the
callback gas and made the deployer refuse anything under a measured floor.

### How did you hear about the buildathon?

The DoraHacks listing.
