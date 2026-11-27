# Demo video script

Narration in English, read by an AI clone of the author's own voice (ElevenLabs). Pictures are captures of the real page
and of the chain explorers (`docs/media/video/tangkap.py`). Every number is taken from [`docs/measured.md`](../measured.md);
the last column names the section. Timings come from `docs/media/video/garis.json`.

| Time | Picture | Narration | Source |
|---|---|---|---|
| 0–9 s | Census grid of Lasna contracts, part dark, with counters | Since November 4, 116 reactive contracts on Lasna went dark. 97 are still dark. | H8 |
| 9–14.2 s | One control Flicker, dark | They ran out of gas money, and they got no warning. | H3 |
| 14.2–23.4 s | The live page, then the fleet | I'm not a developer. I can't watch a dashboard. So I built Pelita. I fill one tank. It does the rest. |  |
| 23.4–36.2 s | Explorer: the outage, the Keeper reaction, the lamp lit again | Here a contract runs dry. Reactive's own system contract announces it. Pelita hears that event and refuels it in the same reaction. |  |
| 36.2–47 s | Blockscout callback, then the control Lantern | On Base Sepolia the refill arrives as a callback. Its twin without Pelita received 4 of 462 heartbeats. | H4 |
| 47–59 s | Measured results | 52 outages on Lasna, 17 on Base Sepolia. Every one was relit. Median: 1 second. Every hash is in the repo. | H1, H2 |
| 59–67 s | Fuel gauge, then the dark list | The page checks any contract's fuel, and shows who is dark right now. Anyone can relight them. |  |
| 67–73.4 s | How it works and the cost of one relight | No polling bot. It costs nothing until something goes dark. | H5 |
| 73.4–80 s | End card | Pelita. Keep it lit. |  |

End card: Pelita · pelita.sasateguh.com · github.com/aimanmalib/pelita · Narration: AI clone of my own voice · Built with
Claude Code · Reactive Omni Buildathon, Set It and Forget It · testnet only · Music: Sascha Ende, ende.app (CC BY 4.0).
