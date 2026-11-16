# Security notes

**Testnet only. Not audited.** Pelita runs on Reactive Lasna (chain 5318007) and Base Sepolia (chain 84532) with test
coins. Do not deploy it with real money.

## Contracts and who may call what

| Contract | Chain | Function | Caller |
|---|---|---|---|
| `PelitaKeeper` | Reactive Lasna | `react(log)` | the system contract only (`onlySystem`) |
| | | `setChain`, `protect`, `release`, `withdraw`, `setFloor`, `setLowMark`, `pause`, `unpause`, `transferOwnership` | owner |
| | | `acceptOwnership` | pending owner |
| | | `coverDebt` | anyone (it only pays the keeper's own debt) |
| `PelitaTank` | destination | `refuel(...)` | the callback proxy (`onlyServiceProvider`), carrying the keeper as sender (`onlyCallbackSender`) |
| | | `pay(amount)` | the callback proxy only (charges for callbacks) |
| | | `withdraw`, `setLimits`, `pause`, `unpause`, `transferOwnership` | owner |
| | | `coverDebt` | anyone |
| `Beacon` (demo) | destination | `poke()` | anyone, once per cooldown and a limited number per window |
| | | `pokeOwner`, `setLimits` | owner |
| `Flicker` (demo) | Reactive Lasna | `react(log)` | system contract only |
| | | `setLantern` | owner, once |
| `Lantern` (demo) | destination | `lit(...)` | the callback proxy, carrying `Flicker` as sender |

Ownership moves in two steps (`transferOwnership` then `acceptOwnership`), so a typo cannot hand the contracts to a
dead address. There is no proxy pattern, no `delegatecall` and no `selfdestruct`.

## Limits on spending

Each protected contract ("ward") has its own limits, set by the owner in `protect` from `config/pelita.json`:

- **Per refuel:** the keeper pays `debt + refill` only when the debt is at most `maxOwed`. `refill` is capped at 1 ether
  by the contract. On a destination the tank also refuses any single payment above its own `maxPerRefuel`.
- **Per day:** at most `dailyCap` refuels per ward in a 24-hour window (1 to 50). The window is measured with
  `block.timestamp`, because block intervals differ from chain to chain.
- **Floor:** the keeper and the tank each keep a `selfFloor` they never spend on refuels. It pays their own fees, so
  the keeper can still react after a busy day.

The invariant tests (`test/invariant/`) drive the keeper with random logs, debts, failures and time jumps and check
three properties: spend per ward per window stays within `dailyCap × (maxOwed + refill)` and `dailyCap` refuels; an
address that was never registered is never paid; a refuel never takes the keeper below its floor.

## Why `react()` and `refuel()` do not revert

The network bills a reactive transaction and a callback even when it reverts. A contract that reverts on a log it
does not like would pay for nothing, again and again. So both functions return early instead, and every refusal is an
event with a reason code:

- Keeper `GaveUp(chainId, target, reason)`: 1 daily cap reached · 2 debt above `maxOwed` · 3 tank below
  `amount + selfFloor` · 4 a call to the biller failed (reading debt, depositing, or requesting the callback).
- Tank `Skipped(seq, target, reason)`: 1 nothing owed · 2 debt above `maxOwed` · 3 above `maxPerRefuel` or below
  `amount + selfFloor` · 4 a call to the proxy failed · 5 tank paused.

Only an unauthorised caller makes them revert, which is the access check doing its job.

## When the tank is empty

The tank is the contract's own balance, topped up with a plain transfer. When it runs low the keeper emits
`LowTank(balance)` and the off-chain indexer sends one alert. When it is empty the keeper gives up with reason 3; it
does not borrow, and the ward stays dark until someone refuels it. Anyone can relight any dark contract directly with
the biller's `depositTo` (no permission needed), and anyone can call `coverDebt()` on the keeper itself.

## Known limits

- **Anyone can request a callback to `PelitaTank` or `Lantern`.** The callback proxy bills the recipient, including for
  callbacks that fail the sender check. A stranger could therefore drain the tank slowly by paying for their own
  reactive contract to aim callbacks at it. On testnet this costs the attacker far more than it costs us; the
  low-tank alert catches it, and the owner can `pause` and `withdraw`.
- **The keeper's lint warnings are deliberate.** Forge's linter flags events emitted after `depositTo`
  (reentrancy-events) and the use of `block.timestamp`. The biller is the network's own system contract or callback
  proxy, fixed per chain by the owner; the state change that matters (`used++`) happens in the same branch, and the
  daily window is 24 hours, far wider than any timestamp drift.
- **One test key.** All contracts are deployed and owned by a single test key kept outside the repository. It has never
  held real funds.

## Reporting

Please report problems privately through GitHub's "Report a vulnerability" on this repository.
