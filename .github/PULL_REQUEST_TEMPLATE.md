## What and why

## How I tested it

- [ ] `bash scripts/gerbang-ujian.sh` (format, build, Solidity tests without fork tests, Python tests, README links)
- [ ] `bash scripts/spike/fork-tests.sh` (if this touches how the contracts read `debt`, `reserves` or `depositTo`)
- [ ] If this changes what `react()` or `refuel()` do: a test that fails without this change
- [ ] If this changes text on the page: `web/lang/en.json` and `web/lang/ms.json` have the same keys
