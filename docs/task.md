# To-do - Multi-Instrument Channel Breakout Backtest

- [x] Clarify requirements (portfolio, shared pool, start date choice, rebalancing, costs)
- [x] Build `mib_backtest.py` (scan, engine, rebalancing, charts, HTML, PDF, CSVs)
- [x] Write `SKILL.md`
- [x] Regression test against the original skill (1 instrument, identical results)
- [x] Verify equal split, exit-funds-buy, rebalance dates and costs, error messages
- [x] README, PRD, implementation plan
- [x] Try the skill on real price files (3 TradingView daily files: BCOM, SPX, XAUUSD)
- [x] Open the HTML in a browser and check the layout

## Changelog
- **[28/10/2026]** All build and test items completed.
- **[28/10/2026]** Added support for `time` date column and yyyy-mm-dd dates (needed for TradingView exports: BCOM, SPX, XAUUSD); scan works on them.
- **[28/10/2026]** Union calendar with closed-market handling implemented and tested (regression vs original skill, closed-day scenario, real 3-file run reconciles, no fills on closed days).
- **[28/10/2026]** Merged rebalance orders into the trade list with Type tags; re-tested (results unchanged, cash flows reconcile, 1-instrument run still matches the original skill).
