# Multi-Instrument Channel Breakout Backtest (Claude skill)

Tests a simple "channel breakout" trading idea on **several stocks/ETFs at once, as one combined portfolio**, and builds a dark-themed HTML report.

Think of it as one company bank account shared by several project managers (one per stock). Each one can spend from the shared account when they spot an opportunity, and money returns to the account when they sell.

## What it does
- Buys an instrument when its close breaks above the highest high/close of the previous X bars; sells when the close falls below the lowest low/close of the previous Y bars. Long only.
- One shared cash pool. Each buy uses `cash in pool / number of empty slots`.
- Optional rebalancing (monthly / quarterly / yearly) at the close of the last trading day of the period: held positions go back to `total equity / number of instruments`.
- Same commission (flat per order) and slippage (% against you) on every entry, exit and rebalance order.
- Uses the overlapping period of all instruments (shows the overlap start and lets you choose a later start date). Inside it, every date on which any market traded is kept: if one market is closed (holiday), it simply can't be traded that day, and its last price is carried forward.
- Compares against an equal-weight buy-and-hold of the same instruments.

## Files
| File | Purpose |
|---|---|
| `SKILL.md` | Instructions Claude follows when the skill is used |
| `mib_backtest.py` | The backtest engine and report builder |
| `docs/` | Product requirements, implementation plan, to-do list |

## Install
Copy this whole folder into your Claude skills folder (for example `~/.claude/skills/multi-instrument-channel-breakout-backtest/`). It needs Python with `pandas`, `numpy`, `matplotlib` and `openpyxl` (`pip install pandas numpy matplotlib openpyxl`).

## How to use
Ask Claude for a "multi instrument channel breakout backtest" and point it to a folder with one price file per instrument (columns: date, open, high, low, close; dates dd/mm/yyyy). Claude scans the files, shows the overlapping period, then asks for the settings.

This skill is a multi-instrument sibling of the single-instrument `simple-channel-breakout-backtest` skill, which it does not modify or depend on.

Backtests are not financial advice; past performance does not guarantee future results.

## Changelog
- **[28/10/2026]** Version 1.0 - final. Published to GitHub.
- **[28/10/2026]** Created the skill: shared-pool portfolio engine, overlap/start-date scan, rebalancing (none/monthly/quarterly/yearly), dark HTML tearsheet, optional PDF, trades and rebalance CSVs.
- **[28/10/2026]** Trade list now shows every fill in date order, tagged Strategy entry / Strategy exit / Rebalance buy / Rebalance sell (or Open position). The separate rebalance table and rebalance CSV were removed; results are unchanged.
- **[28/10/2026]** Price files may now use a `time` column instead of `date`, and dates in yyyy-mm-dd as well as dd/mm/yyyy (TradingView exports). Report dates are still shown as dd/mm/yyyy.
- **[28/10/2026]** Different market holidays are no longer thrown away. The portfolio calendar is now every date any instrument traded; a closed market can't be traded that day (orders wait for its next bar, no signals, skipped in rebalancing) and its last close is carried forward for valuation. The old "bars ignored" data warning became an information line. Re-tested: single-instrument run still matches the original skill; a signal followed by a closed day fills on the next real bar; no fills on closed days in the real 3-file run.
- **[28/10/2026]** Tested: 1-instrument run matches the original skill exactly (trades and final equity, with commission and slippage); P&L reconciles to final equity; equal-split and exit-funds-buy rules verified; error messages checked.
