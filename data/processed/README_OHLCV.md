# KSE-100 · 10-year daily OHLCV candles

`kse100_ohlcv_10y.json` — daily candle history for all 100 KSE-100 constituents.

```jsonc
{
  "meta": {
    "index": "KSE-100",
    "window": { "from": "2016-10-10", "to": "2026-10-08", "requested_years": 10 },
    "sessions": 2477,
    "symbols": 100,
    "rows": 227829,
    "candle_format": "[date, open, high, low, close, volume, quality]",
    "quality_codes": { "": "clean", "a": "...", "p": "...", "c": "..." },
    "price_adjustment": "none (as-reported; split/bonus gaps not adjusted)",
    "source": "https://github.com/Muhammad-Wasif/PSX-Stock-Market-Dataset"
  },
  "symbols": {
    "ABOT": {
      "name": "Abbott Laboratories (Pakistan) Limited",
      "sector": "PHARMACEUTICALS",
      "idx_weight_pct": 0.41,
      "listed_from": "2016-10-10",
      "listed_to": "2026-10-08",
      "rows": 2416,
      "candles": [["2016-10-10", 825.17, 825.17, 825.17, 825.17, 0, "p"], ...]
    }
  }
}
```

**Size** 11.1 MB · **Candles** 227,829 · **Sources & checks** see `DATA_PROVENANCE.md`.

## Load it

```python
import json

doc = json.load(open("data/processed/kse100_ohlcv_10y.json"))
luck = doc["symbols"]["LUCK"]["candles"]
for date, o, h, l, c, vol, q in luck[-5:]:
    print(date, o, h, l, c, vol)
```

```python
# pandas, one symbol
import pandas as pd
df = pd.DataFrame(luck, columns=["date","open","high","low","close","volume","quality"])
df["date"] = pd.to_datetime(df["date"]); df = df.set_index("date")
```

## Things to know before you use it

1. **Not live PSX.** `dps.psx.com.pk` is unreachable from the build environment, so this
   is a cross-checked public mirror of PSX EOD data (see provenance file).
2. **Prices are not split/bonus adjusted.** Gaps are real and visible, e.g. `LUCK`
   1,751.45 → 358.88 on 2025-04-28 (5:1 split). Use
   `kse100_corporate_actions.json` (76 candidate events, 45 symbols) to back-adjust:
   multiply all candles on/before an event by its `ratio`.
3. **Quality flag per candle** — `""` clean, `p` a non-positive open/high/low was
   substituted, `c` high/low widened to contain open/close. Filter with
   `[c for c in candles if c[6] in ("", "a")]` if you want only untouched rows.
4. **Late listings** have fewer candles (`TPLRF1` 588, `HALEON` 906, `AIRLINK` 1,251);
   the first candle is that symbol's genuine first session, not a data gap.
5. Constituents are a single point-in-time snapshot, so index membership changes inside
   the window are not modelled.

## Rebuild / validate

```bash
# clones the mirror into data/raw/ds (git-ignored, ~52 MB)
git clone --depth 1 https://github.com/Muhammad-Wasif/PSX-Stock-Market-Dataset data/raw/ds

python scripts/export_kse100_ohlcv_json.py --years 10 --end 2026-10-08
python scripts/detect_kse100_corporate_actions.py
python scripts/validate_kse100_ohlcv_json.py     # exit 0 = all checks green
```

---

## Excel workbook — `KSE100_10Y_OHLCV.xlsx` (11.5 MB, 105 sheets)

Everything in one workbook, built by `scripts/build_kse100_workbook.py`:

| Sheet | Rows | Contents |
|---|---|---|
| `README` | — | Contents, key facts, how to read the quality flags, caveats |
| `Summary` | — | Index start/end, 10y total return, CAGR, max drawdown, coverage, top-5 returns |
| `Index History` | 2,495 | KSE-100 daily OHLC + chg% + cumulative return, with a line chart |
| `Constituents` | 100 | Symbol, company, sector, index weight, coverage, 10y return (raw and split-adjusted) |
| `<SYMBOL>` × 100 | up to 2,477 each | Date, Open, High, Low, Close, Volume, Chg %, Quality |
| `Corporate Actions` | 76 | Detected split/bonus events with the adjustment ratio |

Filters and frozen header rows are on every data sheet; dates are real Excel dates and
prices are numeric (not text), so you can chart and pivot directly.

```bash
python scripts/build_kse100_workbook.py          # rebuild
python scripts/build_kse100_workbook.py --no-charts
```
