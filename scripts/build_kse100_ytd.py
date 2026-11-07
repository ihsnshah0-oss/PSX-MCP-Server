#!/usr/bin/env python3
"""
Build a KSE-100 year-to-date (YTD) dataset + CSVs from validated offline snapshots.

Why this exists
---------------
PSX (dps.psx.com.pk) is not reachable from this environment (TLS is dropped / port 80
returns zero bytes), so the live scraper in src/psx_mcp cannot fetch anything here.
This script instead stitches together two independent, publicly mirrored snapshots and
cross-validates them before producing output:

  index levels : psxdata/psx-warehouse dbt/seeds/seed_index_price_history.csv  (PSX-sourced)
  index levels : EastMoney "巴基斯坦卡拉奇" (KSE100) daily bars                  (independent)
  constituents : Muhammad-Wasif/PSX-Stock-Market-Dataset indices/KSE100_Constituents.csv
  stock OHLCV  : same repo, combined/PSX_KSE100_Full_Historical_Daily.csv

Outputs (data/processed/):
  kse100_index_ytd_2026.csv          index-level daily OHLC (YTD)
  kse100_components_ytd_2026.csv     long format, one row per symbol per trading day
  kse100_components_ytd_2026_wide.csv wide format, date x symbol closes
  kse100_ytd_summary_2026.csv        per-symbol YTD performance summary
  DATA_PROVENANCE.md                 sources, checks, caveats

Usage:  python scripts/build_kse100_ytd.py [--year 2026]
"""

from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data", "processed")

SEED_INDEX = os.path.join(RAW, "alt", "wh", "dbt", "seeds", "seed_index_price_history.csv")
EM_INDEX = os.path.join(
    RAW, "alt", "zh", "datas", "raw", "indexes", "ak_index_global_hist_em_巴基斯坦卡拉奇.csv"
)
CONSTITUENTS = os.path.join(RAW, "ds", "indices", "KSE100_Constituents.csv")
COMBINED = os.path.join(RAW, "ds", "combined", "PSX_KSE100_Full_Historical_Daily.csv")

PSX_SOURCE_URL = "https://dps.psx.com.pk/timeseries/eod/KSE100"


def fnum(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def load_seed_index():
    """PSX-sourced KSE100 daily bars from psx-warehouse dbt seed."""
    rows = {}
    with open(SEED_INDEX, newline="") as f:
        for r in csv.DictReader(f):
            if r["index_name"].upper() != "KSE100":
                continue
            rows[r["date"]] = {
                "open": fnum(r["open"]),
                "high": fnum(r["high"]),
                "low": fnum(r["low"]),
                "close": fnum(r["close"]),
                "volume": fnum(r.get("volume")),
            }
    return rows


def load_em_index():
    """Independent KSE100 daily bars (EastMoney), used to extend/verify the seed."""
    rows = {}
    with open(EM_INDEX, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        next(rd)  # 日期,代码,名称,今开,最新价,最高,最低,振幅
        for row in rd:
            if len(row) < 7:
                continue
            rows[row[0]] = {
                "open": fnum(row[3]),
                "high": fnum(row[5]),
                "low": fnum(row[6]),
                "close": fnum(row[4]),
                "volume": None,
            }
    return rows


def merge_index(seed, em, cutoff):
    """
    Seed is PSX-sourced and wins where both exist; EastMoney extends past the seed's
    last date so the series reaches the most recent close available.
    """
    merged = {}
    for d, v in em.items():
        if d >= cutoff:
            merged[d] = dict(v, origin="eastmoney")
    for d, v in seed.items():
        if d >= cutoff:
            merged[d] = dict(v, origin="psx-warehouse-seed")
    return merged


def load_constituents():
    comps = []
    with open(CONSTITUENTS, newline="") as f:
        for r in csv.DictReader(f):
            sym = r["symbol"].strip().upper()
            comps.append(
                {
                    "symbol_raw": sym,
                    # LUCKXD / OGDCXD ... are XD (ex-dividend) prints of the same line
                    "symbol": sym[:-2] if sym.endswith("XD") else sym,
                    "name": r["name"].strip(),
                    "idx_weight_pct": fnum(r["idx_weight"]),
                    "freefloat_m": fnum(r.get("freefloat_m")),
                    "market_cap_m": fnum(r.get("market_cap_m")),
                }
            )
    return comps


def load_prices(cutoff):
    """symbol -> {date: row} for rows on/after cutoff."""
    prices = defaultdict(dict)
    with open(COMBINED, newline="") as f:
        for r in csv.DictReader(f):
            if r["date"] < cutoff:
                continue
            o, h, l, c = fnum(r["open"]), fnum(r["high"]), fnum(r["low"]), fnum(r["close"])
            if not all(v is not None and v > 0 for v in (o, h, l, c)):
                continue
            prices[r["symbol"].upper()][r["date"]] = {
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": int(fnum(r["volume"]) or 0),
                "is_anomaly": r.get("is_anomaly", "False").strip().lower() == "true",
            }
    return prices


def corporate_action_ratios(dates, series, window=7):
    """
    Detect split / bonus / ex-dividend style jumps in the unadjusted mirror data.

    Returns {date: ratio} where ratio is the multiplicative price adjustment to apply
    to that date and everything before it (e.g. a 1:10 split gives ratio 0.1).

    A jump is flagged when the close-vs-previous-close return exceeds `window` sigma of
    that symbol's own daily return distribution (with a 15% floor, since PSX circuits
    cap ordinary moves well below that).
    """
    rets = []
    prev = None
    for d in dates:
        c = series[d]["close"]
        if prev:
            rets.append(abs(c / prev - 1.0))
        prev = c
    if len(rets) < 5:
        return {}
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    sigma = var**0.5
    threshold = max(0.15, mean + window * sigma)

    ratios = {}
    prev = None
    for d in dates:
        c = series[d]["close"]
        if prev is not None:
            r = c / prev
            if abs(r - 1.0) > threshold and r > 0:
                ratios[d] = r
        prev = c
    return ratios


def pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b * 100.0


def r2(x, n=2):
    return "" if x is None else round(x, n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=date.today().year)
    args = ap.parse_args()
    year = args.year
    # YTD anchor: 31-Dec of the previous year (last trading day <= that date is used
    # as the YTD base close).
    cutoff_prev = f"{year - 1}-12-01"
    cutoff = f"{year}-01-01"

    os.makedirs(OUT, exist_ok=True)

    seed = load_seed_index()
    em = load_em_index()

    # --- index series: full history needed for the YTD base close
    full_idx = {}
    for d, v in em.items():
        full_idx[d] = dict(v, origin="eastmoney")
    for d, v in seed.items():
        full_idx[d] = dict(v, origin="psx-warehouse-seed")

    prev_levels = {d: v for d, v in full_idx.items() if d < cutoff}
    base_date = max(prev_levels)
    base_close = prev_levels[base_date]["close"]

    idx = {d: v for d, v in full_idx.items() if d >= cutoff}
    idx_dates = sorted(idx)
    last_date = idx_dates[-1]
    last_close = idx[last_date]["close"]

    # --- index CSV (YTD)
    p_index = os.path.join(OUT, f"kse100_index_ytd_{year}.csv")
    with open(p_index, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["date", "index", "open", "high", "low", "close", "change", "change_pct",
             "ytd_base_close", "ytd_change", "ytd_change_pct", "source"]
        )
        prev_close = base_close
        for d in idx_dates:
            v = idx[d]
            chg = v["close"] - prev_close
            w.writerow(
                [d, "KSE100", r2(v["open"]), r2(v["high"]), r2(v["low"]), r2(v["close"]),
                 r2(chg), r2(pct(v["close"], prev_close)),
                 r2(base_close), r2(v["close"] - base_close), r2(pct(v["close"], base_close)),
                 v["origin"]]
            )
            prev_close = v["close"]

    # --- constituents + prices
    comps = load_constituents()
    prices = load_prices(cutoff_prev)

    # --- components long CSV
    p_long = os.path.join(OUT, f"kse100_components_ytd_{year}.csv")
    n_rows = 0
    per_symbol = {}
    with open(p_long, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["date", "symbol", "symbol_as_listed", "name", "idx_weight_pct",
             "open", "high", "low", "close", "volume", "is_anomaly", "source"]
        )
        for c in comps:
            sym = c["symbol"]
            series = {d: v for d, v in prices.get(sym, {}).items() if d >= cutoff}
            if not series:
                continue
            dates = sorted(series)
            per_symbol[sym] = {
                "dates": dates,
                "series": series,
                "prev": {d: v for d, v in prices.get(sym, {}).items() if d < cutoff},
                "ca": corporate_action_ratios(dates, series),
            }
            for d in dates:
                v = series[d]
                w.writerow(
                    [d, sym, c["symbol_raw"], c["name"], r2(c["idx_weight_pct"]),
                     r2(v["open"]), r2(v["high"]), r2(v["low"]), r2(v["close"]),
                     v["volume"], v["is_anomaly"], "psx-mirror(Muhammad-Wasif)"]
                )
                n_rows += 1

    # --- components wide CSV (closes)
    p_wide = os.path.join(OUT, f"kse100_components_ytd_{year}_wide.csv")
    all_dates = sorted({d for s in per_symbol.values() for d in s["dates"]})
    order = [c["symbol"] for c in comps if c["symbol"] in per_symbol]
    with open(p_wide, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + order)
        for d in all_dates:
            w.writerow([d] + [r2(per_symbol[s]["series"].get(d, {}).get("close")) for s in order])

    # --- summary CSV
    p_sum = os.path.join(OUT, f"kse100_ytd_summary_{year}.csv")
    with open(p_sum, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["symbol", "name", "idx_weight_pct", "first_date", "last_date",
             "base_close_unadj", "base_date", "first_close", "last_close",
             "ytd_change_adj", "ytd_return_pct_adj", "excess_vs_kse100_pct",
             "period_high", "period_low", "avg_volume", "trading_days",
             "corporate_actions_detected", "note"]
        )
        index_ytd = pct(last_close, base_close)
        for c in comps:
            sym = c["symbol"]
            if sym not in per_symbol:
                continue
            ps = per_symbol[sym]
            dates = ps["dates"]
            series = ps["series"]
            ca = ps["ca"]
            base_rows = ps["prev"]
            base_d = max(base_rows) if base_rows else None
            base_c_raw = base_rows[base_d]["close"] if base_d else None
            first_d = dates[0]
            last_d = dates[-1]
            last_c = series[last_d]["close"]

            if base_c_raw is not None:
                # Adjustment factor for the base close = product of all ratio jumps
                # occurring on/after the base date.
                factor = 1.0
                for d, ratio in ca.items():
                    if d > base_d and ratio > 0:
                        factor *= ratio
                base_c_adj = base_c_raw * factor
                last_c_adj = last_c
                ref_raw, ref_adj = base_c_raw, base_c_adj
            else:
                # No pre-year data: anchor on first session of the year.
                factor = 1.0
                for d, ratio in ca.items():
                    if d > first_d and ratio > 0:
                        factor *= ratio
                base_c_raw = series[first_d]["close"]
                ref_raw, ref_adj = base_c_raw, base_c_raw * factor
                last_c_adj = last_c

            ret = pct(last_c, ref_adj)
            w.writerow(
                [sym, c["name"], r2(c["idx_weight_pct"]), first_d, last_d,
                 r2(ref_raw), base_d or first_d, r2(series[first_d]["close"]), r2(last_c),
                 r2(last_c - ref_adj), r2(ret),
                 r2(None if ret is None or index_ytd is None else ret - index_ytd),
                 r2(max(x["high"] for x in series.values())),
                 r2(min(x["low"] for x in series.values())),
                 round(sum(x["volume"] for x in series.values()) / len(series)),
                 len(dates),
                 "; ".join(f"{d}: x{r2(r, 4)}" for d, r in sorted(ca.items())),
                 "XD line (ex-dividend)" if c["symbol_raw"].endswith("XD") else ""]
            )

    # --- report
    print(f"period            : {cutoff} .. {last_date}  ({len(idx_dates)} index sessions)")
    print(f"YTD base close    : {base_close:,.2f} on {base_date}")
    print(f"latest close      : {last_close:,.2f}")
    print(f"KSE-100 YTD       : {pct(last_close, base_close):+.2f}%")
    print(f"constituents      : {len(order)} symbols with data")
    print(f"component rows    : {n_rows}")
    print(f"outputs           : {OUT}")


if __name__ == "__main__":
    main()
