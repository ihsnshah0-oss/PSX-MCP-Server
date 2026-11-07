# Data provenance — KSE-100 YTD 2026

Generated: 2026-11-07 by `scripts/build_kse100_ytd.py`

## Why this is not a live PSX pull

`dps.psx.com.pk` is **unreachable from this environment**: TLS handshakes are dropped
(`SSLZeroReturnError: TLS/SSL connection has been closed (EOF)`) and port 80 accepts a
connection but returns 0 bytes. The repo's own scraper (`src/psx_mcp/client.py`) and all
its live tests fail for exactly this reason — see `logs/TEST_TRAIL.md`.

So the numbers below come from **public mirrors of PSX data**, cross-checked against each
other, not from a live scrape.

## Sources

| Component | Source | Mirrors |
|---|---|---|
| KSE-100 index levels (2026-01-01 → 2026-09-04) | `psxdata/psx-warehouse` → `dbt/seeds/seed_index_price_history.csv` (PSX-derived, 2010→2026-09-04) | `data/raw/alt/wh/` |
| KSE-100 index levels (2026-09-07 → 2026-11-03) | EastMoney global index history, series `KSE100` "巴基斯坦卡拉奇" | `data/raw/alt/zh/` |
| KSE-100 constituents (100 symbols + weights) | `Muhammad-Wasif/PSX-Stock-Market-Dataset` → `indices/KSE100_Constituents.csv` | `data/raw/ds/` |
| Component daily OHLCV (→ 2026-10-08) | same repo → `combined/PSX_KSE100_Full_Historical_Daily.csv` | `data/raw/ds/` |

Raw mirrors are **git-ignored** (`data/raw/` is ~514 MB of clones). To rebuild, re-clone
the four repos listed above into the same paths, then run
`python scripts/build_kse100_ytd.py --year 2026`.

## Checks performed

1. **Index series cross-validation.** 3,219 overlapping sessions between the PSX-derived
   seed and EastMoney. The two disagree on ~1,097 of 4 × 3,219 OHLC cells — small
   (sub-1%) differences that grow in 2026 (e.g. 2026-01-02 close 179,034.94 vs 178,504.34).
   The seed wins where both exist; EastMoney is used only to extend past 2026-09-04.
   **Treat index levels as ±0.5%: two providers disagree at that magnitude.**
2. **Constituent sanity.** Exactly 100 constituents; 14 are `...XD` (ex-dividend) prints of
   an existing line (e.g. `LUCKXD`↔`LUCK`) — mapped back to the base symbol. All 100 base
   symbols have 2026 rows.
3. **Coverage.** Index: 208 sessions, 2026-01-01 → 2026-11-03. Components: 190 sessions,
   2026-01-01 → 2026-10-08 (the component mirror lags the index mirror by ~4 weeks).
4. **Corporate actions.** The mirror is **unadjusted**. A jump detector (return > max(15%,
   mean + 7σ)) found 4 splits/bonus issues in 2026 and back-adjusts the YTD base:

   | Symbol | Detected | Raw YTD | Adjusted YTD |
   |---|---|---|---|
   | BAFL | 2026-04-20 ×0.5161 | −47.97% | **+0.81%** |
   | MTL  | 2026-06-22 ×0.5144 | −43.44% | **+9.95%** |
   | SRVI | 2026-08-24 ×0.0957 | −88.60% | **+19.13%** |
   | BML  | 2026-02-02 ×17.2654 | +905.33% | **−41.77%** |

   Detection is heuristic: a split that happens to look like an ordinary move will be
   missed, and a genuine >15% one-day move will be wrongly adjusted. Cash dividends are
   **not** reflected (price return only, no total-return series).
5. **Anomalies.** 44 component rows in 2026 carry `is_anomaly=True` from the source.

## YTD definition

Base = close on the last trading day before 2026-01-01 (**174,054.31 on 2025-12-31**).
KSE-100 YTD = **−3.53%** as of 2026-11-03 (167,910.44).

## Files

| File | Rows | Contents |
|---|---|---|
| `kse100_index_ytd_2026.csv` | 208 | Index daily OHLC, daily change, YTD change, per-row source |
| `kse100_components_ytd_2026.csv` | 18,996 | Long: date, symbol, name, weight, OHLCV, anomaly flag |
| `kse100_components_ytd_2026_wide.csv` | 190 | Wide: date × 100 symbols of closes |
| `kse100_ytd_summary_2026.csv` | 100 | Per-symbol YTD return (split-adjusted), excess vs index, high/low, CA log |

## 10-year OHLCV JSON (`kse100_ohlcv_10y.json`)

Built by `scripts/export_kse100_ohlcv_json.py`, validated by
`scripts/validate_kse100_ohlcv_json.py`.

| Field | Value |
|---|---|
| Window | 2016-10-10 → 2026-10-08 (exactly 10 years back from the last available session) |
| Symbols | 100 KSE-100 constituents (14 `...XD` ex-div prints mapped to base symbols) |
| Trading sessions | 2,477 |
| Candles | 227,829 |
| Size | 11.1 MB |
| Layout | `symbols.<SYM>.candles[i] = [date, open, high, low, close, volume, quality]` |

Per symbol the object also carries `name`, `sector`, `idx_weight_pct`, `listed_from`,
`listed_to`, `rows`, and repair counters.

### Quality flags on each candle (field 7)

| Code | Count | Meaning |
|---|---|---|
| `""` | 226,106 | clean |
| `p` | 989 | a non-positive open/high/low was substituted (close anchored) |
| `c` | 734 | high/low widened so the candle actually contains open & close |
| `a` | 0 in output | usable as-is but flagged `is_anomaly` by the source — superseded by `p`/`c` above; 1,658 flagged rows existed, of which 1,723 needed numeric repair |

Rows with `close <= 0` were dropped (0 such rows in this window).

Late listings naturally have fewer candles (TPLRF1 588, HALEON 906, AIRLINK 1,251) —
`listed_from` records the first real session.

### Prices are NOT adjusted

Splits/bonus issues appear as single-day cliffs (e.g. `LUCK` ×0.2049 on 2025-04-28).
`scripts/detect_kse100_corporate_actions.py` writes
`kse100_corporate_actions.json` — 76 candidate events across 45 symbols, detected as
|return| > max(15%, mean + 7σ). Events with ratio between 0.55 and 1.8 are labelled
"large move (possible dividend/split or data error)" and should be verified manually
before adjusting. Multiply all candles on/before an event date by its `ratio` to build a
continuity-adjusted series.

## Caveats to quote alongside the data

- Not live PSX; mirror data ending 2026-10-08 (stocks) / 2026-11-03 (index).
- Prices are split/bonus-adjusted by heuristic, **not** dividend-adjusted.
- Index level has ±0.5% provider disagreement.
- Constituents are a single point-in-time snapshot (weights as published in the mirror),
  so index membership changes during 2026 are not modelled.
