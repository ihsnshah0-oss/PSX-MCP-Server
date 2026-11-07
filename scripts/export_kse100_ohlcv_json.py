#!/usr/bin/env python3
"""
Export 10-year daily OHLCV candle data for all KSE-100 constituents to JSON.

Source
------
prices : Muhammad-Wasif/PSX-Stock-Market-Dataset -> combined/PSX_KSE100_Full_Historical_Daily.csv
         (PSX-derived daily OHLCV, 2016-10-10 -> 2026-10-08)
members  : same repo -> indices/KSE100_Constituents.csv (100 lines, incl. ...XD ex-div prints)
metadata : same repo -> metadata/PSX_All_Listed_Companies.csv (company name + sector)

PSX itself (dps.psx.com.pk) is unreachable from this environment, so this is mirror
data — see data/processed/DATA_PROVENANCE.md.

Cleaning applied to raw rows
----------------------------
1. Non-positive prices. Rows with open/high/low/close <= 0 are either "no trade" fills
   (all four zero) or bound-fills where open=0 but close is real. Both are repaired in a
   documented way rather than silently kept as 0 candles:
     - open <= 0  -> open = close
     - high <= 0  -> high = max(open, close)
     - low  <= 0  -> low  = min(open, close)
     - close<= 0  -> row dropped (nothing trustworthy to anchor on)
   Every repaired row is flagged `"q":"p"` (patched).
2. OHLC consistency enforced: high = max(h,o,c), low = min(l,o,c).
3. Rows the source already marks `is_anomaly=True` keep `"q":"a"`.

Note: prices are as-reported and NOT split/bonus adjusted (same as PSX's raw timeseries
endpoint). Splits therefore appear as large single-day gaps; `scripts/kse100_corporate_actions.json`
is written alongside this file so consumers can adjust if needed.

Output (default): data/processed/kse100_ohlcv_10y.json  (~14 MB, no indent)
Layout:
{
  "meta": {
    "generated": "...", "source": "...", "index": "KSE100",
    "window": {"from": "...", "to": "...", "years": 10},
    "sessions": 2477, "symbols": 100, "rows": N,
    "format": "symbols.<SYM>.candles[i] = [date, open, high, low, close, volume, quality]"
  },
  "symbols": {
    "ABOT": {
      "name": "Abbott Laboratories (Pakistan) Limited",
      "sector": "PHARMACEUTICALS",
      "listed_from": "2016-10-10", "rows": 2477,
      "candles": [["2016-10-10", 825.17, 825.17, 825.17, 825.17, 0, "a"], ...]
    }, ...
  }
}

Usage:
    python scripts/export_kse100_ohlcv_json.py [--end 2026-10-08] [--years 10] [--indent 0]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT_DIR = os.path.join(ROOT, "data", "processed")

COMBINED = os.path.join(RAW, "ds", "combined", "PSX_KSE100_Full_Historical_Daily.csv")
CONSTITUENTS = os.path.join(RAW, "ds", "indices", "KSE100_Constituents.csv")
LISTED = os.path.join(RAW, "ds", "metadata", "PSX_All_Listed_Companies.csv")

SOURCE_REPO = "https://github.com/Muhammad-Wasif/PSX-Stock-Market-Dataset"


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def parse_date(s):
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def load_meta():
    """symbol -> (company name, sector)"""
    meta = {}
    if not os.path.exists(LISTED):
        return meta
    with open(LISTED, newline="") as f:
        for r in csv.DictReader(f):
            meta[r["symbol"].strip().upper()] = (
                r.get("name", "").strip(),
                r.get("sector_name", "").strip(),
            )
    return meta


def load_constituents():
    out = []
    with open(CONSTITUENTS, newline="") as f:
        for r in csv.DictReader(f):
            raw = r["symbol"].strip().upper()
            out.append(
                {
                    "symbol": raw[:-2] if raw.endswith("XD") else raw,
                    "symbol_as_listed": raw,
                    "name": r["name"].strip(),
                    "idx_weight_pct": fnum(r["idx_weight"]),
                }
            )
    return out


def clean_row(o, h, l, c):
    """
    Repair bad bounds. Returns (o, h, l, c, code) or None to drop.

    code: "p" non-positive value substituted, "c" bounds corrected so the candle
    contains open/close, "" untouched.
    """
    if c <= 0:
        return None
    code = ""
    if o <= 0:
        o = c
        code = "p"
    if h <= 0:
        h = max(o, c)
        code = "p"
    if l <= 0:
        l = min(o, c)
        code = "p"
    if h < max(o, c):
        h = max(o, c)
        code = code or "c"
    if l > min(o, c):
        l = min(o, c)
        code = code or "c"
    return o, h, l, c, code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", default="2026-10-08", help="last session (inclusive)")
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--indent", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    end = parse_date(args.end)
    start = end - timedelta(days=365 * args.years + args.years // 4)
    start_s, end_s = start.isoformat(), end.isoformat()

    comps = load_constituents()
    wanted = {}
    for c in comps:
        wanted.setdefault(c["symbol"], c)
    extra_meta = load_meta()

    candles = {s: [] for s in wanted}
    dropped = {}
    patched = {}
    fixed_counts = {}
    with open(COMBINED, newline="") as f:
        for r in csv.DictReader(f):
            sym = r["symbol"].strip().upper()
            if sym not in wanted or not (start_s <= r["date"] <= end_s):
                continue
            o, h, l, c = (fnum(r[k]) for k in ("open", "high", "low", "close"))
            vol = int(fnum(r["volume"]))
            res = clean_row(o, h, l, c)
            if res is None:
                dropped[sym] = dropped.get(sym, 0) + 1
                continue
            o, h, l, c, fixed = res
            q = fixed
            if fixed:
                fixed_counts[fixed] = fixed_counts.get(fixed, 0) + 1
                patched[sym] = patched.get(sym, 0) + 1
            elif r.get("is_anomaly", "").strip().lower() == "true":
                q = "a"
            candles[sym].append([r["date"], o, h, l, c, vol, q])

    symbols_out = {}
    total_rows = 0
    sessions = set()
    for sym, c in sorted(wanted.items()):
        rows = sorted(candles.get(sym, []), key=lambda x: x[0])
        if not rows:
            continue
        for row in rows:
            sessions.add(row[0])
        name, sector = extra_meta.get(sym, (c["name"], ""))
        symbols_out[sym] = {
            "name": name or c["name"],
            "sector": sector,
            "symbol_as_listed": c["symbol_as_listed"],
            "idx_weight_pct": c["idx_weight_pct"],
            "listed_from": rows[0][0],
            "listed_to": rows[-1][0],
            "rows": len(rows),
            "dropped_rows": dropped.get(sym, 0),
            "patched_rows": patched.get(sym, 0),
            "candles": rows,
        }
        total_rows += len(rows)

    payload = {
        "meta": {
            "generated": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "index": "KSE-100",
            "window": {
                "from": min(sessions) if sessions else None,
                "to": max(sessions) if sessions else None,
                "requested_years": args.years,
                "requested_start": start_s,
            },
            "sessions": len(sessions),
            "symbols": len(symbols_out),
            "rows": total_rows,
            "candle_format": "[date, open, high, low, close, volume, quality]",
            "quality_codes": {
                "": "clean",
                "a": "usable as-is; source flagged is_anomaly",
                "p": "patched: a non-positive open/high/low was substituted (close anchored)",
                "c": "corrected: high/low widened so the candle contains open & close",
            },
            "quality_counts": fixed_counts,
            "price_adjustment": "none (as-reported; split/bonus gaps not adjusted)",
            "source": SOURCE_REPO,
            "note": "Mirror of PSX EOD data; PSX itself is unreachable from the build environment.",
        },
        "symbols": symbols_out,
    }

    out_path = args.out or os.path.join(OUT_DIR, "kse100_ohlcv_10y.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=(args.indent or None), separators=None if args.indent else (",", ":"))

    size_mb = os.path.getsize(out_path) / 1e6
    print(f"window      : {payload['meta']['window']['from']} .. {payload['meta']['window']['to']}")
    print(f"symbols     : {len(symbols_out)}")
    print(f"sessions    : {len(sessions)}")
    print(f"candles     : {total_rows:,}")
    print(f"dropped     : {sum(dropped.values())} (close <= 0)")
    print(f"quality fix : {fixed_counts}")
    print(f"wrote       : {out_path}  ({size_mb:.1f} MB)")
    return payload


if __name__ == "__main__":
    main()
