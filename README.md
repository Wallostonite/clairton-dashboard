# USS Clairton Plant – Environmental Impact Dashboard

An interactive dashboard over the EPA **Toxics Release Inventory (TRI)** data
for the U.S. Steel Clairton Coke Works (Allegheny County, PA), covering
**1988–2024** across **44 chemicals**. It tracks air emissions (fugitive,
stack, total), other on/off-site releases, and waste-management transfers —
all reported in **pounds**.

## Architecture

The project is split so that every piece can be tested without a browser:

| File | Responsibility |
|------|----------------|
| `config.py` | Single source of truth: paths, column groups, quality thresholds. Paths overridable via env vars. |
| `etl.py` | Raw CSV/Excel → validated, analysis-ready parquet. Header auto-detection, full numeric coercion, dedup, **atomic writes**, JSON quality report, CLI. |
| `validation.py` | Structured data-quality checks (errors vs. warnings) with a saveable report. |
| `service.py` | Pure query/aggregation layer used by the UI (filtering, yearly rollups, KPIs). |
| `app.py` | Thin Streamlit UI. Auto-runs the ETL if processed data is missing. |
| `tests/` | `pytest` suite for ETL, validation, and service. |

```
raw CSV/xlsx ──etl.py──▶ data/processed/clean_data.parquet ──service.py──▶ app.py
                  │                                            ▲
                  └──validation.py──▶ data_quality.json ───────┘
```

## Quick start

```bash
pip install -r requirements-dev.txt   # or: make setup
python etl.py                         # build data/processed/clean_data.parquet
streamlit run app.py                  # launch dashboard   (or: make run)
pytest -q                             # run tests          (or: make test)
```

Place the raw export at `data/raw/USS-CLAIRTON PLANT.csv` (CSV or `.xlsx`).

## ETL CLI

```bash
python etl.py                                   # default paths from config.py
python etl.py -i some/other.csv -o out.parquet  # custom paths
python etl.py --no-strict                        # publish even with quality errors
python etl.py -v                                  # debug logging
```

Exit codes: `0` success, `1` pipeline error, `2` published but quality errors.

## Robustness highlights

- **Schema-resilient loader** — finds the header row beneath the export's
  banner rows, handles a BOM, ragged trailing commas, and quoted codes; reads
  CSV *or* Excel.
- **Complete cleaning** — all 24 measure columns are coerced to numeric and the
  source's `.` / whitespace missing-markers become `NaN` (the original cleaned
  only 3 columns).
- **Validation gate** — duplicate keys, out-of-range years, negative releases,
  non-numeric measures and air-sum inconsistencies are checked; strict mode
  refuses to publish bad data.
- **Atomic publish** — parquet is written to a temp file and renamed, so a
  crashed run never leaves a half-written file for the dashboard.
- **Graceful UI** — empty filter selections, missing processed data, and
  missing columns are handled with clear messages instead of stack traces.

## Configuration

Override paths without touching code (see `.env.example`):

```bash
export CLAIRTON_RAW_PATH="/data/clairton.csv"
export CLAIRTON_PROCESSED_PATH="/data/clean.parquet"
```

## Recovering the source data

The raw files are cloud-synced (OneDrive "Files On-Demand"). If they ever show
as empty/zero-byte locally, they have been *evicted*, not deleted — re-download
from OneDrive online to re-hydrate them before running the ETL.
```
