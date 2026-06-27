"""ETL pipeline: raw TRI export -> validated, analysis-ready parquet.

Robustness features over the original one-function script:

* Auto-detects the header row (the raw file has banner rows above it) and
  reads CSV *or* Excel, with BOM handling.
* Cleans **all** 24 numeric columns, not just the three air columns.
* Normalises the source's "." missing markers and stray whitespace to NaN.
* Deduplicates on the natural key and sorts deterministically.
* Validates the result and (in strict mode) refuses to publish bad data.
* Writes parquet **atomically** (temp file + rename) so a crashed run never
  leaves a half-written file that the dashboard would load.
* Emits a JSON data-quality report next to the parquet.
* Exposes a CLI: ``python etl.py --input <path> --output <path> [--no-strict]``.
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import tempfile
from pathlib import Path

import pandas as pd

from config import (
    ID_COLUMNS,
    KEY_COLUMNS,
    MEASURE_COLUMNS,
    NA_TOKENS,
    settings,
)
from validation import QualityReport, validate_or_raise

logger = logging.getLogger("clairton.etl")


# --- Loading ---------------------------------------------------------------
def _find_header_row(rows: list[list[str]], marker: str = "Facility name") -> int:
    """Locate the header row by scanning the first cell of each row."""
    for i, row in enumerate(rows):
        first = (row[0] if row else "").strip().lstrip('﻿"')
        if first.startswith(marker):
            return i
    logger.warning("Header marker %r not found; assuming row index 2", marker)
    return 2


def _read_rows(path: Path) -> list[list[str]]:
    """Return the file as a list of string rows, tolerating ragged widths.

    The ``csv`` module handles quoted fields with embedded commas correctly and
    never errors on inconsistent column counts (unlike ``pd.read_csv``, which
    infers a fixed width from the first line — fatal here, since the banner
    rows above the header are narrower than the data).
    """
    if path.suffix.lower() in {".xlsx", ".xls"}:
        raw = pd.read_excel(path, header=None, dtype=str)
        return raw.astype(object).where(raw.notna(), "").values.tolist()
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return [row for row in csv.reader(fh)]


def load_raw(input_path: str | Path) -> pd.DataFrame:
    """Read the raw CSV/Excel export and return a frame with proper headers."""
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Raw input not found: {path}")

    rows = _read_rows(path)
    if not rows:
        raise ValueError(f"Input file is empty: {path}")

    header_idx = _find_header_row(rows)
    header = [str(c).strip() for c in rows[header_idx]]
    ncols = len(header)

    # Normalise every data row to the header width (pad short, truncate long).
    data = []
    for row in rows[header_idx + 1 :]:
        if not any(str(c).strip() for c in row):
            continue  # skip fully-blank rows
        row = list(row)[:ncols] + [None] * (ncols - len(row))
        data.append(row)

    df = pd.DataFrame(data, columns=header)
    # Drop unnamed/empty trailing columns produced by ragged commas.
    df = df.loc[:, [c for c in df.columns if c and not c.lower().startswith("unnamed")]]
    logger.info("Loaded raw data: %d rows x %d cols from %s", *df.shape, path.name)
    return df


# --- Cleaning --------------------------------------------------------------
def _coerce_numeric(series: pd.Series) -> pd.Series:
    """Strip whitespace, map NA tokens to NaN, then coerce to float."""
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace(r"\s+", "", regex=True)
        .str.replace(",", "", regex=False)
    )
    cleaned = cleaned.where(~cleaned.str.lower().isin(NA_TOKENS))
    return pd.to_numeric(cleaned, errors="coerce")


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and type the raw frame into an analysis-ready dataframe."""
    df = df.copy()
    df.columns = df.columns.str.strip()

    # Trim text in identifier columns; strip the leading apostrophe the export
    # uses to force-text Zip/CAS codes (e.g. "'15025" -> "15025").
    for col in ID_COLUMNS:
        if col in df.columns and df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip().str.strip("'")
            df[col] = df[col].replace({tok: pd.NA for tok in ("", "nan", "None")})

    # Year as nullable integer.
    if "Year" in df.columns:
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")

    # Coerce every measure column that is present.
    for col in MEASURE_COLUMNS:
        if col in df.columns:
            df[col] = _coerce_numeric(df[col])
        else:
            logger.warning("Expected measure column missing from source: %r", col)

    before = len(df)
    # Drop rows with no usable key, then deduplicate on (Year, Chemical).
    df = df.dropna(subset=[c for c in KEY_COLUMNS if c in df.columns], how="any")
    if set(KEY_COLUMNS).issubset(df.columns):
        df = df.drop_duplicates(subset=KEY_COLUMNS, keep="last")
        df = df.sort_values(KEY_COLUMNS).reset_index(drop=True)
    removed = before - len(df)
    if removed:
        logger.info("Removed %d empty/duplicate rows during cleaning", removed)

    return df


# --- Writing ---------------------------------------------------------------
def write_parquet_atomic(df: pd.DataFrame, output_path: str | Path) -> None:
    """Write parquet to a temp file in the same dir, then atomically replace."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=output_path.parent, suffix=".parquet.tmp")
    os.close(fd)
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, output_path)  # atomic on POSIX/Windows
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# --- Orchestration ---------------------------------------------------------
def process_data(
    input_path: str | Path | None = None,
    output_path: str | Path | None = None,
    *,
    strict: bool = True,
    report_path: str | Path | None = None,
) -> QualityReport:
    """Run the full ETL and return the data-quality report."""
    input_path = input_path or settings.raw_path
    output_path = output_path or settings.processed_path
    report_path = report_path or settings.report_path

    raw = load_raw(input_path)
    clean_df = clean(raw)

    report = validate_or_raise(clean_df, strict=strict)
    logger.info("Validation: %s", report.summary())
    for w in report.warnings:
        logger.warning("Quality warning - %s: %s", w.name, w.detail)

    write_parquet_atomic(clean_df, output_path)
    report.save(report_path)
    logger.info(
        "Saved %d rows -> %s (report: %s)", len(clean_df), output_path, report_path
    )
    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Clairton TRI ETL pipeline")
    p.add_argument("-i", "--input", default=None, help="Raw CSV/Excel path")
    p.add_argument("-o", "--output", default=None, help="Output parquet path")
    p.add_argument("--report", default=None, help="Quality report JSON path")
    p.add_argument(
        "--no-strict",
        dest="strict",
        action="store_false",
        help="Publish data even if validation finds errors",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    p.set_defaults(strict=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    try:
        report = process_data(
            args.input, args.output, strict=args.strict, report_path=args.report
        )
    except Exception as exc:  # noqa: BLE001 - top-level CLI guard
        logger.error("ETL failed: %s", exc)
        return 1
    print(f"✅ {report.summary()}")
    return 0 if report.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
