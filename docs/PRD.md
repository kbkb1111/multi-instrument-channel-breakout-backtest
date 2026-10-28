# PRD - Multi-Instrument Channel Breakout Backtest

## Goal
Let the user backtest the same simple channel breakout strategy used in `simple-channel-breakout-backtest` across several instruments as ONE portfolio, and read the result in a clear tearsheet.

## Requirements
- Input: one CSV/Excel price file per instrument (date, open, high, low, close), at least 2 instruments. The date column may be named `time`; dates may be dd/mm/yyyy or yyyy-mm-dd.
- Same parameters for all instruments: entry basis + X, exit basis + Y, capital, commission, slippage.
- Shared cash pool; each entry uses cash / number of empty slots; whole shares.
- Rebalancing: none / monthly / quarterly / yearly, at the close of the last trading day of the period; held positions go to total equity / N.
- Commission and slippage apply to every entry, exit and rebalance order.
- Date handling: use the overlapping period; show the overlap start; user may pick a later start date. Within it, keep every date any instrument traded (market holidays are real behaviour): a closed market cannot trade that day, orders wait for its next bar, its last close is carried forward for valuation.
- Output: dark HTML tearsheet (optional PDF) and a trade list CSV. The trade list shows every fill (strategy entries/exits and rebalance buys/sells) in date order, tagged by type. Dates dd/mm/yyyy.
- Benchmark: equal-weight buy-and-hold, rebalanced on the same schedule.
- Original single-instrument skill stays untouched.

## Out of scope
Per-instrument parameters, short selling, parameter optimisation, instruments joining the portfolio before the overlap start.

## Changelog
- **[28/10/2026]** First version of requirements, agreed with the user.
- **[28/10/2026]** Calendar changed from "common dates only" to "all dates any instrument traded" with closed-market handling (user request: holidays are genuine market behaviour).
- **[28/10/2026]** Rebalance orders merged into the main trade list with a Type tag (user request); separate rebalance table/CSV dropped.
