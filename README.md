# qc-krx

Scrapes Korean equity (KOSPI / KOSDAQ / KONEX) daily price data from
[aikstockdata.com](https://aikstockdata.com/) and converts it to per-stock OHLCV CSVs
and QuantConnect LEAN daily zips.

The site publishes static JSON/CSV files (no login, no API key — catalog at
`https://aikstockdata.com/data/public/index.json`), so this downloads those files rather
than parsing HTML.

## Data sources used

| File | Contents | Depth |
|---|---|---|
| `search_index_rows.json` | code, name, market for ~2,800 stocks | current |
| `s/{code}_history.json` | date, **close, volume** per stock | since 2020-01-02 |
| `daily/quotes_YYYYMMDD.csv` | full-market **OHLCV**, change, value, shares, market cap | **last 30 trading days only** |

Prices are T+1 confirmed closes (published each trading day around 18:30 KST), raw KRW,
**not split-adjusted**. ETFs are not included (the upstream source doesn't provide them).

## Usage

```bash
pip install -r requirements.txt
python -m qc_krx all          # universe + history + daily archive + build (~5–10 min first run)
```

Individual steps:

```bash
python -m qc_krx universe                 # data/raw/universe.csv
python -m qc_krx history 005930 000660    # specific stocks (default: whole universe)
python -m qc_krx daily                    # new daily OHLCV files not yet on disk
python -m qc_krx build [--no-lean]        # data/ohlcv/*.csv and data/lean/...
```

Re-runs are incremental: unchanged histories are skipped via ETag, and daily files already on
disk aren't re-downloaded. **Run `daily` every trading day** (after ~18:30 KST) — the site only
keeps 30 days of OHLCV files, so this is the only way to build up real open/high/low history.

## Output

```
data/raw/universe.csv
data/raw/history/{code}.csv          date,close,volume
data/raw/history_meta.json           per-code etag, as_of and split/merge "breaks"
data/raw/daily/quotes_YYYYMMDD.csv   as published
data/ohlcv/{code}.csv                date,open,high,low,close,volume,source
data/lean/equity/krx/daily/{code}.zip
```

In `data/ohlcv`, `source=daily` rows have real OHLCV; `source=history` rows only have a close,
so open = high = low = close.

The LEAN zips use LEAN's equity daily format (`yyyyMMdd 00:00,o,h,l,c,v`, prices × 10,000).
Map and factor files are **not** generated, and `krx` is not a built-in LEAN market, so
register the market (`Market.add("krx", <id>)`) or load the CSVs as custom data.

## License of the data

The site permits non-commercial use with attribution and forbids commercial redistribution
(`https://aikstockdata.com/licenses/aiksd-public-1.1.txt`; prices also follow KOGL Type 4).
`data/` is git-ignored for this reason. Attribution:
자료: 한국주식데이터(aikstockdata.com) — 원천: 금융위원회 공공데이터포털.

## Tests

```bash
python -m unittest discover tests
```
