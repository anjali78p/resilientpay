# TTR Results

| Scenario | Run 1 | Run 2 | Run 3 | Average | SLA (<60 s) |
|---|---|---|---|---|---|
| API crash (restart: always) | 2.65 | 2.07 | 1.84 | 2.19 s | Pass |
| Nginx crash (restart: always) | 1.08 | 1.56 | 1.54 | 1.39 s | Pass |
| DB crash (restart: always) | 4.38 | 4.35 | 4.39 | 4.37 s | Pass |
| API crash (no restart policy) | None | - | - | No recovery | Fail |

Data check: balances stayed 800 / 700 after all tests (0 lost, 0 duplicate transfers).