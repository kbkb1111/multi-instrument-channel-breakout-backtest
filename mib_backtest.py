#!/usr/bin/env python3
"""Multi-instrument channel breakout backtest -> HTML tearsheet (+ optional PDF).

Long only, ONE combined portfolio over several instruments (one price file each).
Signals on a bar's close, fills at the next bar's open.
Shared cash pool: a buy uses (cash in pool / number of empty slots), whole shares only.
Optional rebalance at the close of the last trading day of the month / quarter / year:
every HELD instrument is brought back to (total equity / number of instruments).
Commission and slippage apply to every fill: entries, exits and rebalance orders.

Modes:  --scan  prints each file's date range and the overlapping period (no backtest).
"""
import argparse, base64, glob, io, json, os, sys
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

DF = "%d/%m/%Y"  # every date shown to the user uses dd/mm/yyyy
REQUIRED = ["date", "open", "high", "low", "close"]
EXTS = (".csv", ".txt", ".xlsx", ".xlsm", ".xls")


def fail(msg):
    print(json.dumps({"status": "error", "message": msg}))
    sys.exit(1)


# ---------------------------------------------------------------- data
def load(path):
    tag = "[%s] " % os.path.basename(path)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        xl = pd.ExcelFile(path)
        if len(xl.sheet_names) > 1:
            fail(tag + "Workbook has several sheets: %s. Use one file (or one single-sheet workbook) per instrument." % xl.sheet_names)
        raw = xl.parse(xl.sheet_names[0])
    elif ext in (".csv", ".txt"):
        raw = pd.read_csv(path, dtype=str)  # read as text so dates are never guessed
    else:
        fail(tag + "Unsupported file type '%s'. Use .csv or .xlsx." % ext)

    cols = {str(c).strip().lower(): c for c in raw.columns}
    if "date" not in cols and "time" in cols:  # TradingView exports call the date column "time"
        cols["date"] = cols["time"]
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        fail(tag + "Missing required column(s): %s. Found: %s. The file must contain date, open, high, low, close."
             % (", ".join(missing), [str(c) for c in raw.columns]))
    df = pd.DataFrame({c: raw[cols[c]] for c in REQUIRED})

    def to_date(v):
        if isinstance(v, (pd.Timestamp, datetime)):
            return pd.Timestamp(v)
        for fmt in (DF, "%Y-%m-%d"):  # dd/mm/yyyy or ISO yyyy-mm-dd; never guessed
            try:
                return pd.Timestamp(datetime.strptime(str(v).strip()[:10], fmt))
            except Exception:
                pass
        return pd.NaT
    df["date"] = df["date"].map(to_date)
    bad = df.index[df["date"].isna()].tolist()
    if bad:
        fail(tag + "Could not read dates as dd/mm/yyyy or yyyy-mm-dd in %d row(s), e.g. file rows %s." % (len(bad), [i + 2 for i in bad[:10]]))
    for c in REQUIRED[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    bad = df.index[df[REQUIRED[1:]].isna().any(axis=1)].tolist()
    if bad:
        fail(tag + "Non-numeric or blank prices in %d row(s), e.g. file rows %s." % (len(bad), [i + 2 for i in bad[:10]]))
    if df["date"].duplicated().any():
        fail(tag + "Duplicate dates found, e.g. %s." % df.loc[df["date"].duplicated(), "date"].dt.strftime(DF).tolist()[:5])
    df = df.sort_values("date").reset_index(drop=True)
    warn = []
    odd = ((df.high < df[["open", "close"]].max(axis=1)) | (df.low > df[["open", "close"]].min(axis=1))).sum()
    if odd:
        warn.append("%s%d bar(s) where high/low do not contain open/close - check the data." % (tag, odd))
    return df, warn


def collect(p):
    if p.folder:
        files = sorted(f for f in glob.glob(os.path.join(p.folder, "*")) if os.path.splitext(f)[1].lower() in EXTS)
    else:
        files = list(p.files or [])
    if not files:
        fail("No price files given. Use --files a.csv b.csv ... or --folder <folder>.")
    if len(files) < 2 and not p.allow_single:
        fail("This skill needs at least 2 instruments (got %d). For a single instrument use the simple-channel-breakout-backtest skill." % len(files))
    names = p.names if p.names else [os.path.splitext(os.path.basename(f))[0] for f in files]
    if len(names) != len(files):
        fail("Got %d name(s) for %d file(s). Give one name per file, in the same order." % (len(names), len(files)))
    if len(set(names)) != len(names):
        fail("Instrument names must be unique: %s." % names)
    data, warns = {}, []
    for f, nm in zip(files, names):
        data[nm], w = load(f)
        warns += w
    return files, names, data, warns


def overlap(data):
    ov_start = max(d.date.iloc[0] for d in data.values())
    ov_end = min(d.date.iloc[-1] for d in data.values())
    if ov_start > ov_end:
        fail("The instruments' date ranges do not overlap (latest first date %s is after earliest last date %s)."
             % (dt(ov_start), dt(ov_end)))
    common = sorted(set.intersection(*[set(d.date) for d in data.values()]))
    if not common:
        fail("The instruments share no common trading dates.")
    return ov_start, ov_end, common


def align(data, names, start):
    """Portfolio calendar = every date on which at least one instrument has a bar. A market with no bar on a date
    is closed that day: it cannot trade, and its last close is carried forward (see run)."""
    ov_start, ov_end, common = overlap(data)
    if start is not None and start < ov_start:
        fail("Start date %s is before the overlap start %s (not every instrument has data before then). Use %s or later."
             % (dt(start), dt(ov_start), dt(ov_start)))
    st = start if start is not None else ov_start
    common = [d for d in common if d >= st]
    if not common:
        fail("No date on or after %s on which every instrument has a bar." % dt(st))
    st_eff = common[0]  # first day every instrument has a bar, so all can be bought / benchmarked from day one
    own = {k: data[k][(data[k].date >= st_eff) & (data[k].date <= ov_end)].set_index("date") for k in names}
    union = pd.DatetimeIndex(sorted(set().union(*[set(d.index) for d in own.values()])), name="date")
    warns = []
    if st_eff != st:
        warns.append("Start moved from %s to %s: the first date on or after it on which every instrument has a bar." % (dt(st), dt(st_eff)))
    fr = {}
    for k in names:
        fr[k] = own[k].reindex(union).reset_index()  # NaN prices on dates this market had no bar
        missing = len(union) - len(own[k])
        if missing:
            warns.append("%s: no bar on %d of the %d portfolio dates (market closed that day). No trading in it on those days; "
                         "its last close is carried forward." % (k, missing, len(union)))
    return fr, union, st_eff, ov_end, warns


# ---------------------------------------------------------------- engine
def rebalance_days(dates, freq):
    """Flag the last trading day of each month / quarter-end month / year.
    A day counts only when a later bar exists in a different month, so the unfinished final period is never rebalanced."""
    n = len(dates); flag = np.zeros(n, bool)
    if freq == "none":
        return flag
    ym = (dates.year * 100 + dates.month).to_numpy()
    for t in range(n - 1):
        if ym[t + 1] != ym[t]:
            m = dates[t].month
            if freq == "monthly" or (freq == "quarterly" and m % 3 == 0) or (freq == "yearly" and m == 12):
                flag[t] = True
    return flag


def rebalance_step(cash, shares, c, skip, s, comm):
    """Bring every held instrument (not in `skip`) to equity/N, at the close, whole shares.
    Trims first, then top-ups capped by cash. Returns new cash and a list of orders. Mutates `shares`."""
    N = len(shares)
    equity = cash + float((shares * c).sum())
    tgt = np.maximum(np.floor(equity / N / c), 1).astype(int)  # never trims a position to zero
    orders = []
    for i in range(N):
        if shares[i] > 0 and not skip[i] and tgt[i] < shares[i]:
            q = int(shares[i] - tgt[i]); px = c[i] * (1 - s)
            cash += q * px - comm; shares[i] -= q; orders.append((i, "Sell", q, px, comm))
    for i in range(N):
        if shares[i] > 0 and not skip[i] and tgt[i] > shares[i]:
            px = c[i] * (1 + s)
            q = min(int(tgt[i] - shares[i]), int(np.floor((cash - comm) / px))) if cash > comm else 0
            if q >= 1:
                cash -= q * px + comm; shares[i] += q; orders.append((i, "Buy", q, px, comm))
    return cash, orders


def run(fr, names, dates, p, rflag):
    N, n = len(names), len(dates)
    O, Cr = (np.column_stack([fr[k][c].to_numpy(float) for k in names]) for c in ("open", "close"))
    has = ~np.isnan(Cr)                           # False = that market has no bar on that date (closed)
    C = pd.DataFrame(Cr).ffill().to_numpy()       # closed market: last close carried forward for valuation only
    cb = np.cumsum(has, axis=0)                   # running count of each instrument's own bars
    upper, lower = np.full((n, N), np.nan), np.full((n, N), np.nan)
    for i, k in enumerate(names):                 # channels use each instrument's OWN previous X / Y bars
        d = fr[k].set_index("date")
        ent = (d["high"] if p.entry_basis == "high" else d["close"]).dropna()
        ext = (d["low"] if p.exit_basis == "low" else d["close"]).dropna()
        upper[:, i] = ent.rolling(p.x).max().shift(1).reindex(dates).to_numpy()   # current bar excluded
        lower[:, i] = ext.rolling(p.y).min().shift(1).reindex(dates).to_numpy()
    s, comm = p.slippage / 100.0, p.commission

    cash, shares, pending, sigd, skipped = p.capital, np.zeros(N, int), [None] * N, [None] * N, 0
    cur, trades, rebs = [None] * N, [], []
    eq, nheld, invested, held = np.zeros(n), np.zeros(n, int), np.zeros(n), np.zeros((n, N), bool)
    for t in range(n):
        for i in range(N):                       # 1) exits first: they free cash for entries (only if that market is open)
            if pending[i] == "sell" and has[t, i]:
                px = O[t, i] * (1 - s); proceeds = shares[i] * px - comm; cash += proceeds
                cu = cur[i]; cu["proceeds"] += proceeds
                cu.update(exit_signal_date=sigd[i], exit_date=dates[t], exit_price=px, exit_shares=int(shares[i]),
                          exit_comm=comm, bars=int(cb[t, i] - cb[cu["entry_i"], i]), status="Closed")
                trades.append(cu); shares[i] = 0; cur[i] = None; pending[i] = None
        for i in range(N):                       # 2) entries: cash in pool / number of empty slots
            if pending[i] == "buy" and has[t, i]:
                empty = int((shares == 0).sum()); budget = cash / empty
                px = O[t, i] * (1 + s); qty = int(np.floor((budget - comm) / px)) if budget > comm else 0
                if qty >= 1:
                    cost = qty * px + comm; cash -= cost; shares[i] = qty
                    cur[i] = dict(instrument=names[i], signal_date=sigd[i], entry_date=dates[t], entry_price=px,
                                  shares=qty, entry_comm=comm, cost=cost, proceeds=0.0, entry_i=t)
                else:
                    skipped += 1
                pending[i] = None
        if t < n - 1:                            # 3) new signals from today's close (only markets that have a bar today)
            for i in range(N):
                if not has[t, i] or pending[i] is not None:
                    continue
                if shares[i] == 0 and not np.isnan(upper[t, i]) and C[t, i] > upper[t, i]:
                    pending[i] = "buy"; sigd[i] = dates[t]
                elif shares[i] > 0 and not np.isnan(lower[t, i]) and C[t, i] < lower[t, i]:
                    pending[i] = "sell"; sigd[i] = dates[t]
        if rflag[t]:                             # 4) rebalance at today's close (open markets only, not positions about to exit)
            skip = np.array([pending[i] == "sell" or not has[t, i] for i in range(N)])
            cash, orders = rebalance_step(cash, shares, C[t], skip, s, comm)
            for i, side, q, px, cm in orders:
                rebs.append(dict(date=dates[t], instrument=names[i], side=side, shares=q, price=px, commission=cm))
                if side == "Buy": cur[i]["cost"] += q * px + cm
                else: cur[i]["proceeds"] += q * px - cm
        eq[t] = cash + float((shares * C[t]).sum()); held[t] = shares > 0; nheld[t] = held[t].sum()
        invested[t] = float((shares * C[t]).sum()) / eq[t] if eq[t] > 0 else 0.0
    for i in range(N):                           # still open at the end: mark to last close, no exit costs
        if cur[i] is not None:
            cu = cur[i]; cu["proceeds"] += shares[i] * C[-1, i]
            cu.update(exit_signal_date=pd.NaT, exit_date=dates[n - 1], exit_price=C[-1, i], exit_shares=int(shares[i]),
                      exit_comm=0.0, bars=int(cb[n - 1, i] - cb[cu["entry_i"], i]), status="Open (marked at last close)")
            trades.append(cu)
    for tr in trades:
        tr["pnl"] = tr["proceeds"] - tr["cost"]; tr["ret"] = tr["pnl"] / tr["cost"]
    trades.sort(key=lambda r: (r["entry_date"], names.index(r["instrument"])))

    # benchmark: equal weight, bought at the first open with the same costs, rebalanced on the same schedule
    bpx = O[0] * (1 + s); bsh = np.floor((p.capital / N - comm) / bpx).astype(int)
    if (bsh < 1).any():
        fail("Starting capital is too small: each instrument gets %.2f, which cannot buy one share of %s at the first bar's open."
             % (p.capital / N, [names[i] for i in np.where(bsh < 1)[0]]))
    bcash = p.capital - float((bsh * bpx).sum()) - comm * N; beq = np.zeros(n)
    for t in range(n):
        if rflag[t]:
            bcash, _ = rebalance_step(bcash, bsh, C[t], ~has[t], s, comm)
        beq[t] = bcash + float((bsh * C[t]).sum())
    out = dict(eq=pd.Series(eq, dates), bh=pd.Series(beq, dates), nheld=nheld, invested=invested, held=held,
               trades=trades, rebs=rebs, upper=upper, lower=lower, skipped=skipped, O=O, C=C)
    return out


# ---------------------------------------------------------------- metrics
def periods_per_year(dates):
    d = dates.diff().dt.days.median()
    return 252 if d <= 4 else 52 if d <= 10 else 12 if d <= 40 else 4 if d <= 120 else 1


def stats(eq, cap, ppy):
    r = eq.pct_change().fillna(eq.iloc[0] / cap - 1)
    yrs = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    tot = eq.iloc[-1] / cap - 1
    cagr = (eq.iloc[-1] / cap) ** (1 / yrs) - 1 if eq.iloc[-1] > 0 else -1
    sd = r.std(); dn = np.sqrt((np.minimum(r, 0) ** 2).mean())
    peak = np.maximum.accumulate(np.r_[cap, eq.to_numpy()])[1:]
    dd = eq / peak - 1
    longest, start = 0, None  # longest drawdown duration (calendar days, peak to recovery or end)
    for d, v in dd.items():
        if v < 0 and start is None: start = d
        if v >= 0 and start is not None: longest = max(longest, (d - start).days); start = None
    if start is not None: longest = max(longest, (dd.index[-1] - start).days)
    mdd = dd.min()
    return dict(total_return=tot, cagr=cagr, ann_vol=sd * np.sqrt(ppy),
                sharpe=r.mean() / sd * np.sqrt(ppy) if sd > 0 else np.nan,
                sortino=r.mean() / dn * np.sqrt(ppy) if dn > 0 else np.nan,
                max_dd=mdd, calmar=cagr / abs(mdd) if mdd < 0 else np.nan,
                longest_dd_days=longest, final_equity=eq.iloc[-1]), dd


def trade_stats(trades, exposure):
    closed = [t for t in trades if t["status"] == "Closed"]
    rets = np.array([t["ret"] for t in closed]); pnl = np.array([t["pnl"] for t in closed])
    w, lo = pnl[pnl > 0], pnl[pnl <= 0]
    return dict(n_trades=len(closed), open_trade=len(trades) - len(closed),
                win_rate=(pnl > 0).mean() if len(pnl) else np.nan,
                profit_factor=w.sum() / abs(lo.sum()) if lo.sum() < 0 else (np.inf if len(w) else np.nan),
                avg_trade=rets.mean() if len(rets) else np.nan,
                avg_win=rets[rets > 0].mean() if (rets > 0).any() else np.nan,
                avg_loss=rets[rets <= 0].mean() if (rets <= 0).any() else np.nan,
                best=rets.max() if len(rets) else np.nan, worst=rets.min() if len(rets) else np.nan,
                avg_bars=np.mean([t["bars"] for t in closed]) if closed else np.nan,
                exposure=exposure)


def per_instrument(names, trades, held, O, C, cap):
    rows = []
    for i, k in enumerate(names):
        tr = [t for t in trades if t["instrument"] == k]
        cl = [t for t in tr if t["status"] == "Closed"]; pnl = sum(t["pnl"] for t in tr)
        rows.append(dict(name=k, closed=len(cl), open=len(tr) - len(cl),
                         win=(np.mean([t["pnl"] > 0 for t in cl]) if cl else np.nan),
                         pnl=pnl, contrib=pnl / cap, time_in=held[:, i].mean(), own_bh=C[-1, i] / O[0, i] - 1))
    return rows


def monthly_table(eq, cap):
    try: m = eq.resample("ME").last()
    except ValueError: m = eq.resample("M").last()
    r = m.pct_change(); r.iloc[0] = m.iloc[0] / cap - 1
    tab = pd.DataFrame({"y": r.index.year, "m": r.index.month, "r": r.values}).pivot(index="y", columns="m", values="r")
    tab = tab.reindex(columns=range(1, 13))
    y = eq.groupby(eq.index.year).last()
    yr = y.pct_change(); yr.iloc[0] = y.iloc[0] / cap - 1
    tab["Year"] = yr.values
    return tab


# ---------------------------------------------------------------- charts (dark theme)
BG, PANEL, INK, MUTE, GRID = "#0f141a", "#171e27", "#e6e9ee", "#9aa4b2", "#2a3441"
BLUE, GOLD, GREEN, RED = "#5aa9ff", "#e0b04a", "#3fb27f", "#e5675f"
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.alpha": .35, "grid.color": GRID, "figure.facecolor": BG, "axes.facecolor": PANEL,
                     "savefig.facecolor": BG, "text.color": INK, "axes.labelcolor": INK, "axes.edgecolor": GRID,
                     "xtick.color": MUTE, "ytick.color": MUTE, "axes.titlecolor": INK, "legend.labelcolor": INK})
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def charts(names, dates, fr, R, eq, bh, dd, bdd, mt):
    figs = {}
    f, ax = plt.subplots(figsize=(10, 3.8))
    ax.plot(eq.index, eq, color=BLUE, lw=1.4, label="Portfolio"); ax.plot(bh.index, bh, color=GOLD, lw=1.1, label="Equal-weight buy & hold")
    ax.set_title("Equity curve"); ax.legend(frameon=False); figs["equity"] = f
    f, ax = plt.subplots(figsize=(10, 2.6))
    ax.fill_between(dd.index, dd * 100, 0, color=BLUE, alpha=.35, label="Portfolio")
    ax.plot(bdd.index, bdd * 100, color=GOLD, lw=1, label="Equal-weight buy & hold")
    ax.set_title("Drawdown (%)"); ax.legend(frameon=False); figs["drawdown"] = f
    f, ax = plt.subplots(figsize=(10, 2.4))
    ax.step(dates, R["nheld"], where="post", color=GREEN, lw=1.1)
    ax.set_ylim(0, len(names) + .5); ax.set_yticks(range(len(names) + 1))
    ax.set_title("Open positions (of %d instruments)" % len(names)); figs["positions"] = f
    f, ax = plt.subplots(figsize=(10, max(1.6, .32 * len(mt) + 1)))
    v = mt.to_numpy(float) * 100; lim = np.nanmax(np.abs(v[:, :12])) if np.isfinite(v[:, :12]).any() else 1
    ax.imshow(np.ma.masked_invalid(v[:, :12]), cmap="RdYlGn", vmin=-lim, vmax=lim, aspect="auto")
    for i in range(v.shape[0]):
        for j in range(12):
            if np.isfinite(v[i, j]): ax.text(j, i, "%.1f" % v[i, j], ha="center", va="center", fontsize=7, color="#111")
    ax.set_xticks(range(12), MONTHS); ax.set_yticks(range(len(mt)), mt.index); ax.grid(False)
    ax.set_title("Monthly returns (%)"); figs["monthly"] = f
    for i, k in enumerate(names):
        f, ax = plt.subplots(figsize=(10, 3.6))
        ax.plot(dates, R["C"][:, i], color=MUTE, lw=1, label="Close")  # carried forward on days the market was closed
        ax.plot(dates, pd.Series(R["upper"][:, i]).ffill().to_numpy(), color=GREEN, lw=.7, ls="--", label="Entry channel")
        ax.plot(dates, pd.Series(R["lower"][:, i]).ffill().to_numpy(), color=RED, lw=.7, ls="--", label="Exit channel")
        tr = [t for t in R["trades"] if t["instrument"] == k]; cl = [t for t in tr if t["status"] == "Closed"]
        ax.scatter([t["entry_date"] for t in tr], [t["entry_price"] for t in tr], marker="^", color=GREEN, s=36, zorder=3, label="Entry")
        ax.scatter([t["exit_date"] for t in cl], [t["exit_price"] for t in cl], marker="v", color=RED, s=36, zorder=3, label="Exit")
        ax.set_title("%s - price, channels and trades" % k); ax.legend(frameon=False, ncol=5, fontsize=8); figs["price_%d" % i] = f
    for f in figs.values(): f.tight_layout()
    return figs


def b64(fig):
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=130); return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------- formatting
def pct(v): return "-" if v is None or not np.isfinite(v) else "%.2f%%" % (v * 100)
def num(v, d=2): return "-" if v is None or not np.isfinite(v) else ("%.*f" % (d, v) if v != np.inf else "inf")
def money(v): return "-" if v is None or not np.isfinite(v) else "{:,.2f}".format(v)
def dt(v): return "-" if v is None or pd.isna(v) else pd.Timestamp(v).strftime(DF)

FREQ_TXT = {"none": "None (no rebalancing)",
            "monthly": "Monthly - at the close of the last trading day of each month",
            "quarterly": "Quarterly - at the close of the last trading day of Mar, Jun, Sep and Dec",
            "yearly": "Yearly - at the close of the last trading day of each year"}


def build_rows(p, names, files, dates, st, s, b, ts, pi, nreb):
    rules = [
        ("Instruments (%d)" % len(names), ", ".join(names)),
        ("Period", "%s to %s (%d portfolio dates)" % (dt(dates[0]), dt(dates[-1]), len(dates))),
        ("Calendar", "Every date on which at least one instrument traded. A market with no bar on a date is closed: it cannot be "
                     "traded that day (orders wait for its next bar) and its last close is carried forward for valuation"),
        ("Entry", "Buy at next bar open when close > highest %s of the previous %d bars" % (p.entry_basis, p.x)),
        ("Exit", "Sell at next bar open when close < lowest %s of the previous %d bars" % (p.exit_basis, p.y)),
        ("Direction / sizing", "Long only, one position per instrument, whole shares only. Shared cash pool: each entry uses cash in pool / number of empty slots"),
        ("Rebalancing", FREQ_TXT[p.rebalance] + ("; held positions are brought back to total equity / %d" % len(names) if p.rebalance != "none" else "")),
        ("Starting capital", money(p.capital)),
        ("Commission", "%s flat per order (every entry, exit and rebalance order)" % money(p.commission)),
        ("Slippage", "%.4g%% of the fill price, against you on every fill (entries, exits and rebalance orders)" % p.slippage),
        ("Benchmark", "Equal-weight buy & hold: capital / %d per instrument bought at the first bar open (same costs)%s"
         % (len(names), "; rebalanced on the same schedule" if p.rebalance != "none" else "")),
    ]
    perf = [("Final equity", money(s["final_equity"]), money(b["final_equity"])),
            ("Total return", pct(s["total_return"]), pct(b["total_return"])),
            ("CAGR", pct(s["cagr"]), pct(b["cagr"])),
            ("Annualised volatility", pct(s["ann_vol"]), pct(b["ann_vol"])),
            ("Sharpe ratio (rf = 0)", num(s["sharpe"]), num(b["sharpe"])),
            ("Sortino ratio (rf = 0)", num(s["sortino"]), num(b["sortino"])),
            ("Max drawdown", pct(s["max_dd"]), pct(b["max_dd"])),
            ("Calmar ratio", num(s["calmar"]), num(b["calmar"])),
            ("Longest drawdown (days)", str(s["longest_dd_days"]), str(b["longest_dd_days"]))]
    trade = [("Closed trades", str(ts["n_trades"])), ("Open trades at end", str(ts["open_trade"])),
             ("Win rate", pct(ts["win_rate"])), ("Profit factor", num(ts["profit_factor"])),
             ("Average trade", pct(ts["avg_trade"])), ("Average win", pct(ts["avg_win"])),
             ("Average loss", pct(ts["avg_loss"])), ("Best trade", pct(ts["best"])), ("Worst trade", pct(ts["worst"])),
             ("Average bars held", num(ts["avg_bars"], 1)), ("Rebalance orders", str(nreb)),
             ("Average % of equity invested", pct(ts["exposure"]))]
    inst = [(r["name"], str(r["closed"]), str(r["open"]), pct(r["win"]), money(r["pnl"]), pct(r["contrib"]),
             pct(r["time_in"]), pct(r["own_bh"])) for r in pi]
    return rules, perf, trade, inst


INST_HDR = ["Instrument", "Closed trades", "Open", "Win rate", "Total P&L", "Contribution to portfolio return",
            "Time in market", "Own buy & hold (first open to last close)"]
TRADE_HDR = ["#", "Date", "Instrument", "Type", "Signal date", "Shares", "Price", "Commission", "Value",
             "Trade P&L", "Trade return", "Bars held"]


def trade_rows(trades, rebs, names):
    """One row per fill, in date order, tagged Strategy entry / Strategy exit / Rebalance buy / Rebalance sell.
    P&L, return and bars are the whole position's result and appear on the exit row (or the open-position row)."""
    ev = []  # (date, order within the day, instrument index, row without number)
    for t in trades:
        k = names.index(t["instrument"])
        ev.append((t["entry_date"], 1, k, [dt(t["entry_date"]), t["instrument"], "Strategy entry", dt(t["signal_date"]),
                   str(int(t["shares"])), num(t["entry_price"], 4), money(t["entry_comm"]),
                   money(t["shares"] * t["entry_price"]), "-", "-", "-"]))
        closed = t["status"] == "Closed"
        ev.append((t["exit_date"], 0 if closed else 3, k, [dt(t["exit_date"]), t["instrument"],
                   "Strategy exit" if closed else "Open position (marked at last close)",
                   dt(t["exit_signal_date"]), str(t["exit_shares"]), num(t["exit_price"], 4), money(t["exit_comm"]),
                   money(t["exit_shares"] * t["exit_price"]), money(t["pnl"]), pct(t["ret"]), str(t["bars"])]))
    for r in rebs:
        ev.append((r["date"], 2, names.index(r["instrument"]), [dt(r["date"]), r["instrument"], "Rebalance " + r["side"].lower(),
                   "-", str(r["shares"]), num(r["price"], 4), money(r["commission"]), money(r["shares"] * r["price"]), "-", "-", "-"]))
    ev.sort(key=lambda e: e[:3])
    return [tuple([str(i + 1)] + e[3]) for i, e in enumerate(ev)]


TEMPLATE = """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>@@TITLE@@</title><style>
:root{--ink:#e6e9ee;--mute:#9aa4b2;--line:#2a3441;--accent:#5aa9ff;--bg:#0f141a;--panel:#171e27}
body{font-family:'Segoe UI',Arial,sans-serif;color:var(--ink);background:var(--bg);margin:0}
.wrap{max-width:1080px;margin:0 auto;padding:28px 16px}
header{border-bottom:3px solid var(--accent);padding-bottom:10px;margin-bottom:18px}
h1{margin:0;font-size:26px;color:var(--accent)} .sub{color:var(--mute);font-size:13px}
h2{font-size:16px;color:var(--accent);border-bottom:1px solid var(--line);padding-bottom:4px;margin-top:28px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
td,th{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left} th{background:var(--panel);font-weight:600}
.grid{display:grid;grid-template-columns:1.4fr 1fr;gap:22px} .num td:not(:first-child),.num th:not(:first-child){text-align:right}
.mon td,.mon th{text-align:center;font-size:11.5px;padding:4px} img{width:100%;height:auto;border-radius:4px}
.scroll{overflow-x:auto} .trades td,.trades th{white-space:nowrap;font-size:11.5px}
.warn{background:#3a2f17;border-left:3px solid #e0b04a;padding:6px 10px;font-size:12.5px}
.note{color:var(--mute);font-size:11.5px}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style></head><body><div class='wrap'>
<header><h1>@@TITLE@@</h1><div class='sub'>Backtest tearsheet &middot; generated @@DATE@@</div></header>@@WARN@@
<h2>Strategy rules</h2>@@RULES@@
<div class='grid'><div><h2>Portfolio vs equal-weight buy &amp; hold</h2>@@PERF@@</div><div><h2>Trade statistics</h2>@@TRADE@@</div></div>
<h2>By instrument</h2><div class='scroll'>@@INST@@</div>
<h2>Equity curve</h2>@@EQUITY@@<h2>Drawdown</h2>@@DD@@<h2>Open positions</h2>@@POS@@
<h2>Monthly returns (%)</h2><div class='scroll'>@@MONTHLY@@</div>
<h2>Price, channels and trades</h2>@@PRICES@@
<h2>Trade list</h2><div class='scroll'>@@TRADES@@</div>
<p class='note'>Signals are evaluated on each bar's close and filled at the next bar's open. Channels use the previous X / Y bars only (the signal bar is excluded). Whole shares only; leftover cash stays in the pool. Rebalance orders fill at the close of the rebalance day. A trade's P&amp;L is all cash in and out of that position (entry, rebalance top-ups and trims, exit) and its return is on the total cash put in. Ratios use a zero risk-free rate and are annualised from the data frequency. Past performance in a backtest does not guarantee future results.</p>
</div></body></html>"""


def html(p, names, rules, perf, trade, inst, trows, mt, figs, warns, today):
    def tbl(rows, hdr=None, cls=""):
        h = "<tr>%s</tr>" % "".join("<th>%s</th>" % x for x in hdr) if hdr else ""
        return "<table class='%s'>%s%s</table>" % (cls, h, "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % x for x in r) for r in rows))
    def mcell(v):
        if not np.isfinite(v): return "<td></td>"
        a = min(abs(v) / 0.10, 1); col = "rgba(46,125,79,%.2f)" % a if v >= 0 else "rgba(178,58,58,%.2f)" % a
        return "<td style='background:%s'>%.1f</td>" % (col, v * 100)
    mhtml = "<table class='mon'><tr><th></th>%s<th>Year</th></tr>%s</table>" % (
        "".join("<th>%s</th>" % m for m in MONTHS),
        "".join("<tr><th>%s</th>%s</tr>" % (y, "".join(mcell(v) for v in r)) for y, r in zip(mt.index, mt.to_numpy(float))))
    img = lambda k: "<img src='data:image/png;base64,%s'/>" % b64(figs[k])
    fill = {"TITLE": "Multi-Instrument Channel Breakout (%d instruments)" % len(names), "DATE": today,
            "WARN": "".join("<p class='warn'>Data warning: %s</p>" % x for x in warns),
            "RULES": tbl(rules), "PERF": tbl(perf, ["Metric", "Portfolio", "Equal-weight buy & hold"], "num"),
            "TRADE": tbl(trade, ["Metric", "Value"], "num"), "INST": tbl(inst, INST_HDR, "num"),
            "EQUITY": img("equity"), "DD": img("drawdown"), "POS": img("positions"), "MONTHLY": mhtml,
            "PRICES": "".join(img("price_%d" % i) for i in range(len(names))),
            "TRADES": tbl(trows, TRADE_HDR, "trades") if trows else "<p class='note'>No trades were triggered.</p>"}
    out = TEMPLATE
    for k, v in fill.items(): out = out.replace("@@%s@@" % k, v)
    return out


def pdf(path, p, names, rules, perf, trade, inst, trows, figs):
    def table_page(pp, title, blocks):
        f = plt.figure(figsize=(11.69, 8.27), facecolor="white"); f.suptitle(title, x=.05, ha="left", fontsize=15, color="#1f3a5f", weight="bold")
        y = .9
        for sub, rows, hdr, widths in blocks:
            h = .028 * (len(rows) + (1 if hdr else 0))
            f.text(.05, y, sub, fontsize=11, color="#1f3a5f", weight="bold")
            ax = f.add_axes([.05, y - h - .01, .9, h]); ax.axis("off")
            t = ax.table(cellText=rows, colLabels=hdr, colWidths=widths, loc="upper left", cellLoc="left")
            t.auto_set_font_size(False); t.set_fontsize(7)
            for (r, _), cell in t.get_celld().items():
                cell.set_edgecolor("#dfe3e8")
                if hdr and r == 0: cell.set_facecolor("#f6f8fa")
            y -= h + .07
        pp.savefig(f, facecolor="white"); plt.close(f)
    with PdfPages(path) as pp:
        table_page(pp, "Multi-Instrument Channel Breakout (%d instruments)" % len(names),
                   [("Strategy rules", rules, None, [.2, .8]),
                    ("Portfolio vs equal-weight buy & hold", perf, ["Metric", "Portfolio", "Equal-weight buy & hold"], [.4, .3, .3])])
        table_page(pp, "Trade statistics and instruments",
                   [("Trade statistics", trade, ["Metric", "Value"], [.5, .5]), ("By instrument", inst, INST_HDR, None)])
        for k, f in figs.items():
            f.set_size_inches(11.69, 8.27 if k == "monthly" else 5); pp.savefig(f)
        for i in range(0, max(len(trows), 1), 25):
            chunk = trows[i:i + 25] or [["-"] * len(TRADE_HDR)]
            table_page(pp, "Trade list" + (" (cont.)" if i else ""), [("", chunk, TRADE_HDR, None)])


# ---------------------------------------------------------------- main
def parse_date(v):
    try: return pd.Timestamp(datetime.strptime(v.strip(), DF))
    except Exception: fail("Could not read start date '%s'. Use dd/mm/yyyy." % v)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--files", nargs="+"); a.add_argument("--folder")
    a.add_argument("--names", nargs="+", help="one label per file, same order; defaults to file names")
    a.add_argument("--scan", action="store_true", help="only report date ranges and the overlapping period")
    a.add_argument("--start", help="start date dd/mm/yyyy; defaults to the overlap start")
    a.add_argument("--entry-basis", choices=["high", "close"]); a.add_argument("--x", type=int)
    a.add_argument("--exit-basis", choices=["low", "close"]); a.add_argument("--y", type=int)
    a.add_argument("--capital", type=float)
    a.add_argument("--commission", type=float, default=0.0)
    a.add_argument("--slippage", type=float, default=0.0, help="percent, e.g. 0.05 = 0.05%%")
    a.add_argument("--rebalance", choices=["none", "monthly", "quarterly", "yearly"], default="none")
    a.add_argument("--pdf", action="store_true"); a.add_argument("--outdir", default=".")
    a.add_argument("--allow-single", action="store_true", help=argparse.SUPPRESS)  # testing only
    p = a.parse_args()

    files, names, data, warns = collect(p)
    if p.scan:
        ov_start, ov_end, common = overlap(data)
        print(json.dumps({"status": "ok", "mode": "scan",
                          "instruments": [dict(name=k, file=os.path.basename(f), first=dt(data[k].date.iloc[0]),
                                               last=dt(data[k].date.iloc[-1]), bars=len(data[k])) for k, f in zip(names, files)],
                          "overlap_start": dt(ov_start), "overlap_end": dt(ov_end), "common_bars": len(common),
                          "first_common_date": dt(common[0]), "warnings": warns}, indent=1))
        return

    for k in ("entry_basis", "x", "exit_basis", "y", "capital"):
        if getattr(p, k) is None: fail("Missing --%s." % k.replace("_", "-"))
    if p.x < 1 or p.y < 1: fail("X and Y must be whole numbers of at least 1.")
    if p.capital <= 0: fail("Starting capital must be positive.")
    if p.commission < 0 or p.slippage < 0: fail("Commission and slippage cannot be negative.")
    if p.commission >= p.capital / len(names): fail("Commission is larger than the capital available per instrument.")

    fr, dates, st, ov_end, w2 = align(data, names, parse_date(p.start) if p.start else None)
    warns += w2
    for k in names:
        nb = int(fr[k]["close"].notna().sum())
        if nb <= max(p.x, p.y) + 1: fail("%s has only %d bars from the start date - not enough for X=%d / Y=%d." % (k, nb, p.x, p.y))
    rflag = rebalance_days(dates, p.rebalance)
    R = run(fr, names, dates, p, rflag)
    if R["skipped"]:
        warns.append("%d entry signal(s) skipped: not enough cash to buy one whole share." % R["skipped"])
    ppy = periods_per_year(pd.Series(dates))
    s, dd = stats(R["eq"], p.capital, ppy); b, bdd = stats(R["bh"], p.capital, ppy)
    ts = trade_stats(R["trades"], R["invested"].mean())
    pi = per_instrument(names, R["trades"], R["held"], R["O"], R["C"], p.capital)
    mt = monthly_table(R["eq"], p.capital)
    figs = charts(names, dates, fr, R, R["eq"], R["bh"], dd, bdd, mt)
    rules, perf, trade, inst = build_rows(p, names, files, dates, st, s, b, ts, pi, len(R["rebs"]))
    trows = trade_rows(R["trades"], R["rebs"], names)

    os.makedirs(p.outdir, exist_ok=True)
    stem = "multi%d_breakout_E%s%d_X%s%d_%s" % (len(names), p.entry_basis[0].upper(), p.x, p.exit_basis[0].upper(), p.y, p.rebalance)
    out = {"status": "ok", "html": os.path.join(p.outdir, stem + ".html")}
    with open(out["html"], "w", encoding="utf-8") as fh:
        fh.write(html(p, names, rules, perf, trade, inst, trows, mt, figs, warns, datetime.now().strftime(DF)))
    out["trades_csv"] = os.path.join(p.outdir, stem + "_trades.csv")
    pd.DataFrame(trows, columns=TRADE_HDR).to_csv(out["trades_csv"], index=False)
    if p.pdf:
        out["pdf"] = os.path.join(p.outdir, stem + ".pdf"); pdf(out["pdf"], p, names, rules, perf, trade, inst, trows, figs)
    out.update(period="%s to %s" % (dt(dates[0]), dt(dates[-1])), bars=len(dates), warnings=warns,
               trades={k: v for k, v in trade})
    out["strategy"] = {r[0]: r[1] for r in perf}; out["buy_and_hold"] = {r[0]: r[2] for r in perf}
    out["by_instrument"] = [dict(zip(INST_HDR, r)) for r in inst]
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
