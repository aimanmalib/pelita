# ADR 0008: Callback gas floor on Base Sepolia, and replacing a demo pair

Status: accepted, 23 Nov 2026

## Context

The first public demo beat (`0xc04b6749…`, E-004) was refused by the Base Sepolia callback proxy with
`NotAuthorized()` while the network operator was rotating callback senders. After the rotation, deliveries from the new
sender succeeded for other contracts, so a second beat was sent (`0x2566ba92…`, Base block 62765810). The Flicker on
Lasna forwarded it, and the proxy delivery `0xb8bd5de5…` (block 62765816) reverted with no data.

Measured with read-only calls on the parent block:

- The Lantern call alone (`lit(...)` from the proxy address) succeeds.
- The whole `deliverCallback` succeeds with a 200000 or 300000 gas limit and reverts at 100000 with
  `InsufficientGas(55561, 130000)` (selector `0x23e228cb`); `cast estimate` gives 175776.
- The operator submits every delivery with the transaction gas limit equal to the gas limit the reactive contract asked
  for. The 21 other deliveries in the same window asked for 300000 to 2000000 and all succeeded.

So the proxy needs about 130000 gas left after its own checks, and a callback that asks for 100000 can never be
delivered. The spike Flicker was deployed with `flicker_callback_gas = 100000`, an immutable constructor value.

## Decision

- `config/pelita.json` `demo.flicker_callback_gas` = 300000, the smallest limit seen succeeding on this proxy. The
  Keeper's destination `callback_gas` (400000) already clears the floor.
- `config/chains.json` gets `callback_gas_min` per destination (Base Sepolia: 200000, above the measured 175776).
  The deployer refuses a Keeper or Flicker callback gas below it, and a config test checks it.
- The deployer replaces a contract whose fixed constructor values differ from config (`IMMUTABLE_KINDS`: Flicker; the
  Beacon has setters and is kept). The old record moves to `retired` in `deployments/<chain>.json`; a contract that
  pointed at it (the Lantern) is replaced by the existing rule; a retired guarded contract still protected by the
  Keeper is released, so the Keeper stops paying for it.
- The guarded pair was replaced on 23 Nov: Flicker `0xa4c7BDDbA75955C915FC38753037e82c32d240B2` (Lasna), Lantern
  `0xF5f37156f2C3414735E6085aAeCC9940e6C77904` (Base Sepolia). To pay for it, 0.15 `lREACT` was withdrawn from the
  Keeper to the deployer with the owner's `withdraw` (the Keeper is topped up in P2b).

## Consequences

- The retired pair (`0xc8deb0e8…` on both chains) stays on chain. Its Flicker still reacts to beats until its
  reserves run out, then stays dark; nothing pays for it any more.
- A destination added later needs its own measured `callback_gas_min`; without one the check is 0.

## Rollback

Set `flicker_callback_gas` back and run the deployer: it would deploy another pair, which the proxy would again refuse.
There is no useful rollback; the measurement stands.
