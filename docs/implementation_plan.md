# Implementation plan - Multi-Instrument Channel Breakout Backtest

1. Reuse the data loading, metrics, monthly table and formatting code from the original `scb_backtest.py`.
2. Add `--scan` mode (date ranges + overlap) and start-date validation (`align`).
3. Portfolio engine (`run`): per bar - exits, entries from shared pool, new signals, rebalance at close, mark equity.
4. Rebalance calendar (`rebalance_days`) and order logic (`rebalance_step`), shared with the benchmark.
5. Per-instrument stats, dark charts, HTML template, optional PDF, CSV outputs.
6. SKILL.md flow: files -> scan -> confirm start date -> parameters -> run -> present.
7. Test: 1-instrument regression vs original skill, P&L reconciliation, equal-split and exit-funds-buy scenarios, rebalance dates/costs, error paths.

## Changelog
- **[28/10/2026]** Plan agreed and fully implemented.
- **[28/10/2026]** Steps 2-4 changed: `align` builds the union calendar (start moves to the first day all instruments have a bar); `run` tracks `has[t,i]` (market open), carries closes forward, keeps pending orders until the market's next bar, skips closed markets in signals and rebalancing, counts bars held per instrument's own bars; channels computed per instrument on its own bars.
- **[28/10/2026]** Step 5 changed: one fill-level trade list (`trade_rows`) merging strategy trades and rebalance orders, tagged by Type; `REB_HDR`, `reb_rows`, rebalance table and rebalance CSV removed.
