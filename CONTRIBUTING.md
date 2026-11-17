# Contributing

Thanks for helping. Pelita moves test coins on its owner's behalf, so a change to when or how much it pays gets extra
scrutiny.

## Set up

[Foundry](https://getfoundry.sh) 1.8.7 and Python 3.12 (standard library only; nothing to install with pip).

```sh
git clone --recurse-submodules https://github.com/aimanmalib/pelita
cd pelita
bash scripts/gerbang-ujian.sh       # format, build, Solidity tests, Python tests, README links (offline)
bash scripts/spike/fork-tests.sh    # read-only tests against live Lasna and Base Sepolia state
```

If Foundry is not in your `PATH`, set `FOUNDRY_BIN` to the folder that holds `forge`, `cast` and `anvil`.

## Before you open a pull request

- Run `bash scripts/gerbang-ujian.sh`; CI runs the same script.
- `react()` and `refuel()` must not revert for an ordinary log or state: the network bills a reverted reaction too.
  Every refusal is an event with a reason code ([docs/SECURITY.md](docs/SECURITY.md)). A change here needs a test that
  fails without your change.
- No proxy pattern, `delegatecall` or `selfdestruct` in the contracts.
- Values that an operator may change (limits, gas, addresses, timings) live in `config/`, not in code.
- Text on the page goes in `web/lang/en.json` and `web/lang/ms.json`, in English and Malay with the same keys.
- Never put a private key, keystore or password in a command line, a log, a test fixture or a commit.
- One topic per pull request; describe how you tested it.

## Reporting security issues

Please don't open a public issue. Use
[private vulnerability reporting](https://github.com/aimanmalib/pelita/security/advisories/new).

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE) and that you follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
