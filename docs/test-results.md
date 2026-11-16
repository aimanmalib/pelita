# Test results

Offline suite (CI and `scripts/gerbang-ujian.sh`): `forge fmt --check`, `forge build`, `forge test` without
`test/fork/*`, and `python3 -m unittest`. Counts are printed by the commands themselves; this file records runs that
CI cannot repeat.

## Fork tests (live state, read only)

Command: `bash scripts/spike/fork-tests.sh` (nothing is broadcast; `vm.deal` and `vm.prank` change only the local fork).

### 2026-11-17

Dark Lasna target picked at run time: `0x780f37d9b634936e26e3c5610ddaaaedfebcb998` (newest `BlacklistContract` with `debt > 0`).

```
Ran 2 tests for test/fork/BaseSepoliaFork.t.sol:BaseSepoliaForkTest
[PASS] test_Fork_ProxyAnswersDebtAndReserves() (gas: 26505)
[PASS] test_Fork_ProxyDepositToCreditsReserves() (gas: 77886)
Ran 7 tests for test/fork/LasnaFork.t.sol:LasnaForkTest
[PASS] test_Fork_DebtSelectorAnswersOnSystemContract() (gas: 13454)
[PASS] test_Fork_OneWeiReducesDebtWithoutSettling() (gas: 72274)
[PASS] test_Fork_ReservesSelectorAnswersOnSystemContract() (gas: 13320)
[PASS] test_Fork_SettlingDebtEmitsWhitelistContract() (gas: 61893)
[PASS] test_Fork_SurplusGoesToReserves() (gas: 117886)
[PASS] test_Fork_ThirdPartyDepositFromContractSettlesDebt() (gas: 217155)
[PASS] test_Fork_ThirdPartyDepositSettlesDebt() (gas: 68916)
Ran 2 test suites: 9 tests passed, 0 failed, 0 skipped (9 total tests)
```

## Chain facts (E-001)

Command: `bash scripts/spike/readonly.sh` → `docs/evidence/E-001-chain-facts.json`. 2026-11-17: 44 checks, 0 failed.
