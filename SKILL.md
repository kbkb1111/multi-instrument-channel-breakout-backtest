---
name: multi-instrument-channel-breakout-backtest
description: Backtests a simple long-only channel breakout strategy (Donchian-style) across SEVERAL stocks/ETFs as ONE combined portfolio (shared cash pool, optional monthly/quarterly/yearly rebalancing) from one CSV or Excel price file per instrument, and produces an HTML tearsheet. Use only for multi-instrument channel breakout tests - for a single instrument use simple-channel-breakout-backtest; not for moving average, momentum or other strategies.
---

# Multi-Instrument Channel Breakout Backtest

Runs one fixed strategy: a long-only channel breakout on each of several instruments, traded as ONE portfolio with ONE pool of cash. The math lives in `mib_backtest.py` (saved next to this SKILL.md), so every run uses identical rules. Never change the rules, add optimisation, or test other parameter sets unless the user explicitly asks for a separate run.

The user may not be a programmer: explain results in simple words, use a real-world analogy if a concept comes up, and keep replies short.

## Step 1 - Get the price files
- The user gives a folder, or a list of files: one `.csv` / `.xlsx` per instrument. At least 2 instruments. If none are given, ask.
- Each file MUST contain `date`, `open`, `high`, `low`, `close` (case-insensitive, extra columns ignored). The date column may also be called `time` (TradingView exports). Dates may be dd/mm/yyyy or yyyy-mm-dd (or native Excel dates); they are never guessed. If anything is missing the script stops and says which file and column - tell the user in plain words. Do not guess or rebuild columns.
- Excel workbooks must have a single sheet each (one instrument per file). Instrument name = file name, unless the user gives labels (`--names`, same order as the files).

## Step 2 - Scan, then confirm the start date
1. Run the scan (no backtest yet):
```
python mib_backtest.py --folder "<folder>"  --scan
python mib_backtest.py --files "<a.csv>" "<b.csv>" [--names A B] --scan
```
2. Show the user, in a small table: each instrument's first date, last date and bar count, then the **overlapping period** (`overlap_start` to `overlap_end`). (`common_bars` is only the count of days all instruments traded; the backtest itself uses every date any instrument traded.)
3. Ask: start from the **overlap start date** (the first date ALL instruments have data), or a **different start date**? A different date must be on or after the overlap start (the script refuses anything earlier, because some instrument would have no data). Dates are dd/mm/yyyy.

## Step 3 - Ask for the parameters (always ask, never assume)
Ask all of these in one message (use the multiple-choice question tool if available). Only commission and slippage have defaults.
1. **Entry basis** - break above the highest **high** or highest **close** of the previous X bars?
2. **X** - entry lookback in bars.
3. **Exit basis** - break below the lowest **low** or lowest **close** of the previous Y bars?
4. **Y** - exit lookback in bars.
5. **Starting capital** - for the whole portfolio.
6. **Commission** - flat amount per order, on every entry, exit AND rebalance order. Default 0.
7. **Slippage** - percent of the fill price, against you on every fill (entries, exits, rebalance orders). Default 0%.
8. **Rebalancing** - None, Monthly, Quarterly or Yearly.
9. **Output** - HTML only (default); PDF on request.

The same X / Y / bases apply to every instrument (do not offer per-instrument settings).

Fixed rules (do not ask, state them in the confirmation):
- Long only; at most one position per instrument; whole shares only (leftover cash stays in the pool; an entry that cannot afford one share is skipped and flagged).
- **Shared cash pool, equal split at signal:** a buy uses `cash in pool / number of empty slots` (an empty slot = an instrument with no position). Exits return cash to the pool. If several buys fire on the same day they are filled one after another, which gives an equal split.
- Signal on the bar's close, fill at the next bar's open. Channels use the previous X / Y bars only (signal bar excluded), computed from the chosen start date.
- **Calendar:** every date on which AT LEAST ONE instrument traded is a portfolio date (different holidays and trading days are real market behaviour, so nothing is thrown away). On a date when an instrument has no bar its market is closed: it cannot be traded (a signal or order for it waits for its next real bar, never a fill on a closed day), it gets no new signals, it is skipped in rebalancing, and its last close is carried forward so the position is still valued. Channels use each instrument's own previous X / Y bars. The script lists, per instrument, how many portfolio dates it was closed (information, not an error). If the chosen start date is not a day every instrument traded, it moves to the next such day (and says so), so all instruments can be bought on day one.
- **Rebalancing** (if chosen): at the close of the last trading day of each month / of Mar, Jun, Sep, Dec / of each year, every instrument currently held is brought back to `total portfolio equity / number of instruments` (trims first, then top-ups limited by cash; empty slots stay as cash). Fills at that day's close with slippage and commission. A position that has a pending exit signal that day is left alone. The unfinished final period of the data is never rebalanced.
- An open position at the end is marked at the last close (no exit cost).
- Benchmark: equal-weight buy-and-hold (capital / N per instrument, bought at the first bar's open with the same costs), rebalanced on the same schedule so the comparison is fair.

Repeat the chosen settings back in one short line, then run.

## Step 4 - Run the script
1. Check `pandas`, `numpy`, `matplotlib` and `openpyxl` import; install any that are missing (`pip install <pkg>`).
2. Run (on Windows, plain `python` may hit the Microsoft Store stub; if so use `py` or the full path to the real Python install):
```
python mib_backtest.py --folder "<folder>" | --files <f1> <f2> ... [--names <n1> <n2> ...] \
  --start dd/mm/yyyy --entry-basis high|close --x <X> --exit-basis low|close --y <Y> \
  --capital <capital> --commission <commission> --slippage <slippage_pct> \
  --rebalance none|monthly|quarterly|yearly [--pdf] --outdir <output folder>
```
   `--slippage` is in percent: `0.05` means 0.05%. Leave `--start` out to use the overlap start.
3. The script prints JSON. If `"status": "error"`, explain the message in plain words and stop - do not work around it.

## Step 5 - Present the results
- Say where the HTML tearsheet (and PDF if requested) plus the trade list CSV were saved.
- Give 3-5 short lines: CAGR, max drawdown, Sharpe and number of trades for the portfolio vs the equal-weight buy-and-hold, the best and worst instrument by contribution, plus any data warnings. Do not re-list every metric; the tearsheet has them.
- Do not suggest "better" parameters or run extra variations unless asked.

## Tearsheet contents (dark theme)
Strategy rules as selected; portfolio vs equal-weight buy-and-hold (final equity, total return, CAGR, volatility, Sharpe, Sortino, max drawdown, Calmar, longest drawdown); trade statistics (closed trades, open trades, win rate, profit factor, average trade/win/loss, best/worst, average bars held, rebalance orders, average % of equity invested); per-instrument table (trades, win rate, P&L, contribution to portfolio return, time in market, own buy-and-hold); equity curve; drawdown; open-positions-over-time chart; monthly returns heatmap; price chart with channels and trade markers for each instrument; one combined trade list. Ratios use a zero risk-free rate, annualised from the data frequency. All dates dd/mm/yyyy.

**Trade list:** one row per fill, in date order, each tagged by Type: `Strategy entry`, `Strategy exit`, `Rebalance buy`, `Rebalance sell` (or `Open position (marked at last close)` for a position still held at the end). Each row shows date, instrument, signal date, shares, price, commission and value. Trade P&L, return and bars held appear on the exit row (or open-position row) and cover the whole position: all cash in and out including rebalance top-ups/trims, with the return measured on the total cash put in. Rebalance rows have no P&L of their own.
