#!/usr/bin/env python3
"""
Detect split / bonus / ex-dividend style jumps in the exported 10-year OHLCV JSON and
write a companion corporate-actions file, so consumers can back-adjust prices if they
want a continuity-adjusted series (the OHLCV JSON itself is as-reported).

Method: for each symbol, compute daily close-to-close returns; flag any day whose
|return| exceeds max(15%, mean + 7*sigma) of that symbol's own return distribution.
Recorded ratio = close[t] / close[t-1] (a 1:10 split shows ~0.1, a 10:1 bonus ~10).

Output: data/processed/kse100_corporate_actions.json

Usage: python scripts/detect_kse100_corporate_actions.py [--json path] [--window 7]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_JSON = os.path.join(ROOT, "data", "processed", "kse100_ohlcv_10y.json")
OUT = os.path.join(ROOT, "data", "processed", "kse100_corporate_actions.json")


def detect(candles, window=7.0, floor=0.15):
    closes = [(c[0], c[4]) for c in candles]
    rets = []
    for i in range(1, len(closes)):
        prev = closes[i - 1][1]
        if prev > 0:
            rets.append(abs(closes[i][1] / prev - 1.0))
    if len(rets) < 5:
        return []
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    threshold = max(floor, mean + window * var**0.5)

    events = []
    for i in range(1, len(closes)):
        d0, p0 = closes[i - 1]
        d1, p1 = closes[i]
        if p0 <= 0:
            continue
        ratio = p1 / p0
        if abs(ratio - 1.0) > threshold:
            events.append(
                {
                    "date": d1,
                    "prev_date": d0,
                    "prev_close": round(p0, 2),
                    "close": round(p1, 2),
                    "ratio": round(ratio, 6),
                    "implied_action": (
                        f"~1-for-{1 / ratio:.2f} reverse split" if ratio > 1.8
                        else f"~{1 / ratio:.2f}-for-1 split/bonus" if ratio < 0.55
                        else "large move (possible dividend/split or data error)"
                    ),
                    "threshold_pct": round(threshold * 100, 1),
                }
            )
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=DEFAULT_JSON)
    ap.add_argument("--window", type=float, default=7.0)
    args = ap.parse_args()

    with open(args.json) as f:
        doc = json.load(f)

    out = {}
    total = 0
    for sym, obj in doc["symbols"].items():
        ev = detect(obj["candles"], window=args.window)
        if ev:
            out[sym] = ev
            total += len(ev)

    payload = {
        "meta": {
            "source_json": os.path.basename(args.json),
            "method": (
                f"flag |close-to-close return| > max(15%, mean + {args.window}*sigma) "
                "of that symbol's own daily returns"
            ),
            "price_adjustment_of_source": "none",
            "how_to_use": (
                "For a continuity-adjusted series, multiply every candle on or before "
                "each event date by event['ratio'] (cumulative across events)."
            ),
            "symbols_with_events": len(out),
            "events": total,
        },
        "actions": out,
    }
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"symbols with events : {len(out)}")
    print(f"events              : {total}")
    for sym, ev in sorted(out.items()):
        for e in ev:
            print(f"  {sym:8} {e['date']}  x{e['ratio']:<10} {e['implied_action']}")
    print(f"wrote               : {OUT}")


if __name__ == "__main__":
    sys.exit(main())
