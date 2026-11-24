# solana-desk-scanner

Paper-trading research scanner for Solana DEX tokens. **No real funds, no wallets, no private keys, no paid services.**
Every "trade" in this repo is a hypothetical paper trade used to study which entry and exit rules would have worked.

## What runs
- `ledger/nearmiss/scanner.py run` — one scan: reads free public market data (GeckoTerminal, DexScreener), logs candidate rows to
  `ledger/nearmiss/near_misses.csv` and simulates their exits on paper.
- After each scan, hooks in `ledger/learning/` update paper books and research logs:
  `learning.py` (paper books, `trades.csv`, `book.json`), `exits.py` (alternative exit rules, `exits.csv`), `features.py` (entry features, `features.csv`),
  `copycat_filter.py` (copycat / fake-liquidity filter, `symbols.json`), `ta.py` (1-minute-candle price-action setups, `ta_*.csv`), `analyze.py` (daily summary).
- Python 3.9+ standard library only. No API keys or secrets are needed or stored.

## Schedule
`.github/workflows/scanner.yml` runs on a GitHub Actions schedule. Each job scans every 5 minutes for about 20 minutes and commits the changed
data files back to this repo (`[skip ci]`), using only the built-in `GITHUB_TOKEN`. One job at a time (concurrency group).

## Local use
```
DESK_ROOT=$(pwd) python3 ledger/nearmiss/scanner.py run
python3 ledger/learning/clean_stats.py
python3 ledger/learning/ta.py report
```
`DESK_ROOT` is the folder that contains `ledger/` (defaults to the repo root).

Nothing here is financial advice. Results are simulated, include an assumed 3% round-trip fee plus slippage, and most strategies tested lose money.
