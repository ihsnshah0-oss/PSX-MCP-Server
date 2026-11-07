#!/usr/bin/env python3
"""
Validate the exported KSE-100 10-year OHLCV JSON.

Checks (all must pass):
  1. meta.symbols == number of keys in symbols, and == 100
  2. meta.rows == sum of per-symbol rows
  3. every candle is [date, o, h, l, c, volume, quality] with correct types
  4. dates are strictly ascending inside each symbol
  5. 0 < low <= min(open, close) <= max(open, close) <= high
  6. volume >= 0, quality in {"", "a", "p", "c"}
  7. no date outside the declared window
  8. every KSE-100 constituent in indices/KSE100_Constituents.csv is present

Usage: python scripts/validate_kse100_ohlcv_json.py [path]
Exit code 0 = valid, 1 = problems found.
"""

from __future__ import annotations

import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(ROOT, "data", "processed", "kse100_ohlcv_10y.json")
CONSTITUENTS = os.path.join(ROOT, "data", "raw", "ds", "indices", "KSE100_Constituents.csv")

VALID_Q = {"", "a", "p", "c"}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    errors = []
    with open(path) as f:
        doc = json.load(f)

    meta = doc["meta"]
    syms = doc["symbols"]
    fmt = meta["candle_format"]

    if meta["symbols"] != len(syms):
        errors.append(f"meta.symbols={meta['symbols']} but {len(syms)} symbol objects")
    if meta["symbols"] != 100:
        errors.append(f"expected 100 symbols, got {meta['symbols']}")

    total = 0
    win_lo = meta["window"]["from"]
    win_hi = meta["window"]["to"]
    for sym, obj in syms.items():
        candles = obj["candles"]
        total += len(candles)
        if obj["rows"] != len(candles):
            errors.append(f"{sym}: rows={obj['rows']} but {len(candles)} candles")
        prev = None
        for i, k in enumerate(candles):
            if len(k) != 7:
                errors.append(f"{sym}[{i}]: expected 7 fields, got {len(k)}")
                break
            d, o, h, l, c, v, q = k
            if not isinstance(d, str) or len(d) != 10:
                errors.append(f"{sym}[{i}]: bad date {d!r}")
            if not all(isinstance(x, (int, float)) for x in (o, h, l, c)):
                errors.append(f"{sym}[{i}]: non-numeric OHLC")
                break
            if not isinstance(v, int) or isinstance(v, bool):
                errors.append(f"{sym}[{i}]: volume not int ({v!r})")
            if q not in VALID_Q:
                errors.append(f"{sym}[{i}]: bad quality {q!r}")
            if prev is not None and d <= prev:
                errors.append(f"{sym}[{i}]: date not ascending ({prev} -> {d})")
            prev = d
            if d < win_lo or d > win_hi:
                errors.append(f"{sym}[{i}]: date {d} outside window {win_lo}..{win_hi}")
            if not (0 < l <= min(o, c) and max(o, c) <= h):
                errors.append(f"{sym}[{i}]: OHLC invariant broken o={o} h={h} l={l} c={c}")
            if v < 0:
                errors.append(f"{sym}[{i}]: negative volume {v}")
            if len(errors) > 40:
                errors.append("... too many errors, stopping")
                break
        if len(errors) > 40:
            break

    if meta["rows"] != total:
        errors.append(f"meta.rows={meta['rows']} but counted {total}")

    if os.path.exists(CONSTITUENTS):
        needed = {
            (r["symbol"].strip().upper()[:-2]
             if r["symbol"].strip().upper().endswith("XD")
             else r["symbol"].strip().upper())
            for r in csv.DictReader(open(CONSTITUENTS, newline=""))
        }
        missing = needed - set(syms)
        if missing:
            errors.append(f"missing constituents: {sorted(missing)}")

    print(f"file      : {path}")
    print(f"format    : {fmt}")
    print(f"symbols   : {len(syms)}")
    print(f"window    : {meta['window']['from']} .. {meta['window']['to']}")
    print(f"candles   : {total:,}")
    if errors:
        print(f"\nFAILED — {len(errors)} problem(s):")
        for e in errors[:40]:
            print("  -", e)
        return 1
    print("\nPASSED — all integrity checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
