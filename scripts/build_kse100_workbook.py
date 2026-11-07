#!/usr/bin/env python3
"""
Build one Excel workbook containing the whole KSE-100 dataset.

Sheets
------
  README            what's inside, provenance, caveats, how to use
  Summary           headline stats + KSE-100 10-year performance
  Index History     10y KSE-100 daily OHLC (+ embedded line chart)
  Constituents      current 100 members w/ weights and 10y returns
  <SYM> x100        one sheet per constituent: date, open, high, low, close, volume,
                    chg%, quality  (2016-10-10 -> last available session)
  Corporate Actions detected split/bonus events (prices are unadjusted)

Inputs
------
  data/processed/kse100_ohlcv_10y.json          per-symbol candles
  data/processed/kse100_corporate_actions.json  detected events
  data/raw/alt/wh/... + data/raw/alt/zh/...     KSE-100 index levels (mirrors)

Output
------
  data/processed/KSE100_10Y_OHLCV.xlsx

Usage
-----
  python scripts/build_kse100_workbook.py [--out path] [--no-charts]

Kept in constant-memory mode so the ~1.8M cells do not blow up RAM.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime

import xlsxwriter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
OHLCV_JSON = os.path.join(PROC, "kse100_ohlcv_10y.json")
CA_JSON = os.path.join(PROC, "kse100_corporate_actions.json")
SEED_INDEX = os.path.join(ROOT, "data", "raw", "alt", "wh", "dbt", "seeds", "seed_index_price_history.csv")
EM_INDEX = os.path.join(
    ROOT, "data", "raw", "alt", "zh", "datas", "raw", "indexes",
    "ak_index_global_hist_em_巴基斯坦卡拉奇.csv",
)
WIDE_CSV = os.path.join(PROC, "kse100_components_ytd_2026_wide.csv")

# index history is trimmed to the same 10-year window as the stock candles
WINDOW = ("2016-10-10", "2026-11-03")


# --------------------------------------------------------------------------- index
def load_index_history():
    seed, em = {}, {}
    if os.path.exists(SEED_INDEX):
        with open(SEED_INDEX, newline="") as f:
            for r in csv.DictReader(f):
                if r["index_name"].upper() != "KSE100":
                    continue
                seed[r["date"]] = (
                    float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
                )
    if os.path.exists(EM_INDEX):
        with open(EM_INDEX, encoding="utf-8-sig", newline="") as f:
            rd = csv.reader(f)
            next(rd)
            for row in rd:
                if len(row) >= 7:
                    em[row[0]] = (float(row[3]), float(row[5]), float(row[6]), float(row[4]))
    merged = dict(em)
    merged.update(seed)  # PSX-derived seed wins where both exist
    lo, hi = WINDOW
    return {d: merged[d] for d in sorted(merged) if lo <= d <= hi}


# --------------------------------------------------------------------------- formats
def make_formats(wb):
    base = {"font_name": "Calibri", "font_size": 10}
    return {
        "title": wb.add_format({**base, "bold": True, "font_size": 16, "font_color": "#12284B"}),
        "subtitle": wb.add_format({**base, "font_size": 11, "font_color": "#555555"}),
        "h2": wb.add_format({**base, "bold": True, "font_size": 12, "font_color": "#12284B",
                             "bottom": 1, "bottom_color": "#B8C4D9"}),
        "header": wb.add_format({**base, "bold": True, "font_color": "#FFFFFF",
                                 "bg_color": "#12284B", "border": 1,
                                 "border_color": "#12284B", "align": "center",
                                 "valign": "vcenter", "text_wrap": True}),
        "date": wb.add_format({**base, "num_format": "yyyy-mm-dd", "align": "center"}),
        "price": wb.add_format({**base, "num_format": "#,##0.00"}),
        "money": wb.add_format({**base, "num_format": "#,##0"}),
        "int": wb.add_format({**base, "num_format": "#,##0"}),
        "pct": wb.add_format({**base, "num_format": "0.00%"}),
        "pct_c": wb.add_format({**base, "num_format": "+0.00%;-0.00%;0.00%"}),
        "text": wb.add_format(base),
        "text_c": wb.add_format({**base, "align": "center"}),
        "wrap": wb.add_format({**base, "text_wrap": True, "valign": "top"}),
        "flag": wb.add_format({**base, "align": "center", "font_color": "#B45309", "bold": True}),
        "label": wb.add_format({**base, "bold": True}),
        "kv": wb.add_format({**base, "num_format": "#,##0.00"}),
        "note": wb.add_format({**base, "italic": True, "font_color": "#666666"}),
    }


def write_table_header(ws, row, headers, widths, fmt):
    for c, (h, w) in enumerate(zip(headers, widths)):
        ws.write_string(row, c, h, fmt)
        ws.set_column(c, c, w)
    ws.freeze_panes(row + 1, 0)
    ws.autofilter(row, 0, row, len(headers) - 1)


# --------------------------------------------------------------------------- sheets
def build_readme(wb, F, meta, n_symbols, n_rows, index_rows, ca_meta):
    ws = wb.add_worksheet("README")
    ws.hide_gridlines(2)
    ws.set_column("A:A", 3)
    ws.set_column("B:B", 34)
    ws.set_column("C:C", 78)

    ws.write(1, 1, "KSE-100 — 10-Year Daily OHLCV", F["title"])
    ws.write(2, 1, "Pakistan Stock Exchange · 100 index constituents · one workbook", F["subtitle"])

    facts = [
        ("Workbook generated", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")),
        ("Data window (stocks)", f"{meta['window']['from']} → {meta['window']['to']}"),
        ("Data window (index)", index_rows),
        ("Constituents", f"{n_symbols} sheets, one per symbol"),
        ("Candles (stock-days)", f"{n_rows:,}"),
        ("Trading sessions", f"{meta['sessions']:,}"),
        ("Candle fields", ", ".join(["date", "open", "high", "low", "close", "volume",
                                     "chg%", "quality"])),
        ("Price adjustment", "none — as reported; see 'Corporate Actions' sheet"),
        ("Data source", "PSX-derived public mirror (dps.psx.com.pk unreachable from build env)"),
        ("Mirror repo", meta.get("source", "")),
        ("Corporate-action events", f"{ca_meta.get('events', 0)} across "
                                    f"{ca_meta.get('symbols_with_events', 0)} symbols"),
    ]
    r = 4
    ws.write(r, 1, "Contents", F["h2"])
    ws.write(r + 1, 1, "Sheet", F["header"])
    ws.write(r + 1, 2, "What it holds", F["header"])
    r += 2
    sheets = [
        ("Summary", "Headline stats and KSE-100 10-year performance numbers."),
        ("Index History", "Daily KSE-100 open/high/low/close with a 10-year line chart."),
        ("Constituents", "The 100 members with index weights, coverage and 10-year returns."),
        ("<SYMBOL> (×100)", "One sheet per stock: date, O, H, L, C, volume, chg%, quality flag."),
        ("Corporate Actions", "Detected split/bonus events and the ratio to back-adjust with."),
        ("README", "This sheet."),
    ]
    for name, desc in sheets:
        ws.write_string(r, 1, name, F["label"])
        ws.write_string(r, 2, desc, F["wrap"])
        r += 1

    r += 1
    ws.write(r, 1, "Key facts", F["h2"])
    r += 1
    for k, v in facts:
        ws.write_string(r, 1, k, F["label"])
        ws.write_string(r, 2, v, F["wrap"])
        r += 1

    r += 1
    ws.write(r, 1, "Reading the data", F["h2"])
    notes = [
        ("Quality flag", "blank = clean · p = a non-positive open/high/low was substituted "
                         "(close anchored) · c = high/low widened so the candle contains "
                         "open & close · a = usable but flagged by the source"),
        ("Late listings", "Some symbols have fewer candles because they listed inside the "
                          "window (e.g. TPLRF1, HALEON, AIRLINK). The first row is their real "
                          "first session, not a gap."),
        ("Splits & bonuses", "Prices are NOT adjusted: e.g. LUCK 1,751.45 → 358.88 on "
                             "2025-04-28 is a 5:1 split, not a crash. Use the Corporate "
                             "Actions sheet to build a continuous series."),
        ("chg% column", "Close-over-close change for that row, computed from the close column "
                        "as-shipped. On split dates it is large by design."),
        ("Index data", "KSE-100 levels come from two providers that agree within ~0.5%; the "
                       "PSX-derived series wins where both exist. Index history runs to "
                       "2026-11-03, stock history to 2026-10-08 (mirror lag)."),
        ("Membership", "Constituents are one point-in-time snapshot; index changes inside the "
                       "10-year window are not modelled."),
        ("Not investment advice", "Mirror data, provided for analysis/education. PSX licences "
                                  "live market data — see marketdatarequest@psx.com.pk."),
    ]
    for k, v in notes:
        ws.write_string(r, 1, k, F["label"])
        ws.write_string(r, 2, v, F["wrap"])
        ws.set_row(r, 30)
        r += 1
    return ws


def build_summary(wb, F, idx, meta, symbols, ca_actions):
    ws = wb.add_worksheet("Summary")
    ws.hide_gridlines(2)
    ws.set_column("A:A", 3)
    ws.set_column("B:B", 30)
    ws.set_column("C:C", 18)
    ws.set_column("D:D", 4)
    ws.set_column("E:E", 30)
    ws.set_column("F:F", 18)

    ws.write(1, 1, "KSE-100 — 10-Year Summary", F["title"])
    dates = list(idx)
    first_d, last_d = dates[0], dates[-1]
    c0, c1 = idx[first_d][3], idx[last_d][3]
    closes = [v[3] for v in idx.values()]
    ret = (c1 / c0 - 1) * 100
    years = len(dates) / 250.0
    cagr = ((c1 / c0) ** (1 / years) - 1) * 100 if years > 0 else 0.0
    peak, mdd = closes[0], 0.0
    for v in closes:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)

    r = 3
    ws.write(r, 1, "Index performance", F["h2"])
    r += 1
    rows = [
        ("Start date", first_d, F["text"]),
        ("Start close", c0, F["kv"]),
        ("End date", last_d, F["text"]),
        ("End close", c1, F["kv"]),
        ("Total return", ret / 100, F["pct"]),
        ("CAGR (≈250 sessions/yr)", cagr / 100, F["pct"]),
        ("10y high (close)", max(closes), F["kv"]),
        ("10y low (close)", min(closes), F["kv"]),
        ("Max drawdown", mdd, F["pct"]),
        ("Sessions in window", len(dates), F["int"]),
    ]
    for k, v, f in rows:
        ws.write_string(r, 1, k, F["label"])
        if isinstance(v, str):
            ws.write_string(r, 2, v, F["text"])
        else:
            ws.write_number(r, 2, v, f)
        r += 1

    r += 1
    ws.write(r, 1, "Dataset coverage", F["h2"])
    r += 1
    cov = [
        ("Constituent sheets", len(symbols), F["int"]),
        ("Candles (stock-days)", meta["rows"], F["int"]),
        ("Trading sessions (stocks)", meta["sessions"], F["int"]),
        ("Stock window", f"{meta['window']['from']} → {meta['window']['to']}", F["text"]),
        ("Symbols with corporate actions", len(ca_actions), F["int"]),
        ("Symbols present at window start",
         sum(1 for s in symbols.values() if s["listed_from"] <= meta["window"]["from"]), F["int"]),
        ("Symbols listed mid-window",
         sum(1 for s in symbols.values() if s["listed_from"] > meta["window"]["from"]), F["int"]),
    ]
    for k, v, f in cov:
        ws.write_string(r, 1, k, F["label"])
        if isinstance(v, str):
            ws.write_string(r, 2, v, F["text"])
        else:
            ws.write_number(r, 2, v, f)
        r += 1

    return ws, r + 1


def build_index_sheet(wb, F, idx, charts=True):
    ws = wb.add_worksheet("Index History")
    headers = ["Date", "Open", "High", "Low", "Close", "Chg %", "Cum. return"]
    widths = [12, 12, 12, 12, 12, 10, 12]
    write_table_header(ws, 0, headers, widths, F["header"])

    dates = list(idx)
    c0 = idx[dates[0]][3]
    prev = None
    for i, d in enumerate(dates):
        o, h, l, c = idx[d]
        row = i + 1
        ws.write_datetime(row, 0, datetime.strptime(d, "%Y-%m-%d"), F["date"])
        ws.write_number(row, 1, o, F["price"])
        ws.write_number(row, 2, h, F["price"])
        ws.write_number(row, 3, l, F["price"])
        ws.write_number(row, 4, c, F["price"])
        if prev:
            ws.write_number(row, 5, c / prev - 1, F["pct_c"])
        else:
            ws.write_blank(row, 5, None, F["pct_c"])
        ws.write_number(row, 6, c / c0 - 1, F["pct_c"])
        prev = c

    if charts and len(dates) > 10:
        ch = wb.add_chart({"type": "line"})
        ch.add_series({
            "name": "KSE-100 close",
            "categories": ["Index History", 1, 0, len(dates), 0],
            "values": ["Index History", 1, 4, len(dates), 4],
            "line": {"color": "#12284B", "width": 1.25},
        })
        ch.set_title({"name": "KSE-100 — 10 years"})
        ch.set_y_axis({"num_format": "#,##0", "major_gridlines": {"visible": True,
                                                                "line": {"color": "#E6E6E6"}}})
        ch.set_x_axis({"date_axis": True, "num_format": "yyyy"})
        ch.set_legend({"none": True})
        ch.set_size({"width": 900, "height": 380})
        ws.insert_chart("I2", ch)
    return ws


def build_constituents(wb, F, symbols, meta, ca_actions):
    ws = wb.add_worksheet("Constituents")
    headers = ["Symbol", "Company", "Sector", "Idx weight %", "First candle", "Last candle",
               "Candles", "First close", "Last close", "10y return (raw)",
               "10y return (split-adj)", "Corporate actions"]
    widths = [9, 46, 24, 11, 12, 12, 10, 12, 12, 15, 17, 20]
    write_table_header(ws, 0, headers, widths, F["header"])

    rows = []
    for sym, obj in sorted(symbols.items()):
        cs = obj["candles"]
        first_c = cs[0][4]
        last_c = cs[-1][4]
        raw = last_c / first_c - 1 if first_c else None
        ev = ca_actions.get(sym, [])
        # back-adjust the FIRST close by every event inside the window
        factor = 1.0
        for e in ev:
            if e["ratio"] > 0:
                factor *= e["ratio"]
        adj = (last_c / (first_c * factor) - 1) if first_c else None
        rows.append((sym, obj, raw, adj, ev))

    for i, (sym, obj, raw, adj, ev) in enumerate(rows):
        r = i + 1
        ws.write_string(r, 0, sym, F["text_c"])
        ws.write_string(r, 1, obj["name"], F["text"])
        ws.write_string(r, 2, obj["sector"], F["text"])
        ws.write_number(r, 3, obj["idx_weight_pct"], F["price"])
        ws.write_string(r, 4, obj["listed_from"], F["date"])
        ws.write_string(r, 5, obj["listed_to"], F["date"])
        ws.write_number(r, 6, obj["rows"], F["int"])
        ws.write_number(r, 7, obj["candles"][0][4], F["price"])
        ws.write_number(r, 8, obj["candles"][-1][4], F["price"])
        if raw is None:
            ws.write_blank(r, 9, None, F["pct"])
        else:
            ws.write_number(r, 9, raw, F["pct_c"])
        if adj is None:
            ws.write_blank(r, 10, None, F["pct"])
        else:
            ws.write_number(r, 10, adj, F["pct_c"])
        ws.write_string(r, 11, f"{len(ev)} event(s)" if ev else "", F["text"])
    return ws, rows


def build_symbol_sheet(wb, F, sym, obj):
    ws = wb.add_worksheet(sym)
    headers = ["Date", "Open", "High", "Low", "Close", "Volume", "Chg %", "Quality"]
    widths = [12, 11, 11, 11, 11, 14, 10, 9]
    write_table_header(ws, 0, headers, widths, F["header"])
    prev = None
    for i, (d, o, h, l, c, v, q) in enumerate(obj["candles"]):
        r = i + 1
        ws.write_datetime(r, 0, datetime.strptime(d, "%Y-%m-%d"), F["date"])
        ws.write_number(r, 1, o, F["price"])
        ws.write_number(r, 2, h, F["price"])
        ws.write_number(r, 3, l, F["price"])
        ws.write_number(r, 4, c, F["price"])
        ws.write_number(r, 5, v, F["int"])
        if prev:
            ws.write_number(r, 6, c / prev - 1, F["pct_c"])
        else:
            ws.write_blank(r, 6, None, F["pct_c"])
        if q:
            ws.write_string(r, 7, q, F["flag"])
        prev = c
    return ws


def build_ca_sheet(wb, F, ca_doc):
    ws = wb.add_worksheet("Corporate Actions")
    headers = ["Symbol", "Date", "Prev close", "Close", "Ratio", "Implied action"]
    widths = [9, 12, 12, 12, 10, 46]
    write_table_header(ws, 0, headers, widths, F["header"])
    r = 1
    for sym, events in sorted(ca_doc.get("actions", {}).items()):
        for e in events:
            ws.write_string(r, 0, sym, F["text_c"])
            ws.write_string(r, 1, e["date"], F["date"])
            ws.write_number(r, 2, e["prev_close"], F["price"])
            ws.write_number(r, 3, e["close"], F["price"])
            ws.write_number(r, 4, e["ratio"], F["price"])
            ws.write_string(r, 5, e["implied_action"], F["text"])
            r += 1
    ws.write_string(r + 1, 0,
                    "Back-adjust by multiplying every candle on/before the event date "
                    "by Ratio (cumulatively). Prices in this workbook are unadjusted.",
                    F["note"])
    return ws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(PROC, "KSE100_10Y_OHLCV.xlsx"))
    ap.add_argument("--no-charts", action="store_true")
    args = ap.parse_args()

    with open(OHLCV_JSON) as f:
        doc = json.load(f)
    ca_doc = json.load(open(CA_JSON)) if os.path.exists(CA_JSON) else {"actions": {}, "meta": {}}
    meta = doc["meta"]
    symbols = doc["symbols"]
    idx = load_index_history()
    if not idx:
        raise SystemExit("index history not found — clone the mirrors first (see README_OHLCV.md)")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    wb = xlsxwriter.Workbook(args.out, {"constant_memory": True, "default_date_format": "yyyy-mm-dd"})
    wb.set_properties({
        "title": "KSE-100 10-Year Daily OHLCV",
        "subject": "Pakistan Stock Exchange — 100 constituents, daily candles",
        "author": "Arena Agent",
        "company": "PSX-MCP-Server",
        "comments": "Mirror data; prices unadjusted. See README sheet.",
    })
    F = make_formats(wb)

    dates = list(idx)
    index_span = f"{dates[0]} → {dates[-1]} ({len(dates)} sessions)"
    build_readme(wb, F, meta, len(symbols), meta["rows"], index_span, ca_doc.get("meta", {}))
    ws_sum, top_row = build_summary(wb, F, idx, meta, symbols, ca_doc.get("actions", {}))
    build_index_sheet(wb, F, idx, charts=not args.no_charts)
    _, comp_rows = build_constituents(wb, F, symbols, meta, ca_doc.get("actions", {}))

    # Top-5 table on the Summary sheet (split-adjusted 10y return)
    ranked = sorted(
        [(s, o, a) for s, o, _, a, _ in comp_rows if a is not None],
        key=lambda t: t[2], reverse=True,
    )[:5]
    r = top_row + 1
    ws_sum.write_string(r, 1, "Top 5 by 10-year return (split-adjusted)", F["h2"])
    r += 1
    ws_sum.write_string(r, 1, "Symbol", F["header"])
    ws_sum.write_string(r, 2, "10y return (split-adj)", F["header"])
    for i, (s, o, a) in enumerate(ranked, start=1):
        ws_sum.write_string(r + i, 1, f"{s} — {o['name'][:28]}", F["text"])
        ws_sum.write_number(r + i, 2, a, F["pct_c"])

    for sym, obj in sorted(symbols.items()):
        build_symbol_sheet(wb, F, sym, obj)

    build_ca_sheet(wb, F, ca_doc)
    wb.close()

    size = os.path.getsize(args.out) / 1e6
    print(f"sheets      : {4 + len(symbols) + 1}")
    print(f"symbols     : {len(symbols)}")
    print(f"candles     : {meta['rows']:,}")
    print(f"index rows  : {len(idx):,}")
    print(f"wrote       : {args.out}  ({size:.1f} MB)")


if __name__ == "__main__":
    main()
