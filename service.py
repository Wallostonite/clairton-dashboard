"""Data-access / query layer for the dashboard.

Keeps all dataframe logic out of the Streamlit UI so it can be unit-tested
without a browser. Functions are pure (no global state) and defensive: they
validate inputs, tolerate missing columns, and never raise on empty results.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from config import AIR_COLUMNS, KEY_COLUMNS, settings

logger = logging.getLogger("clairton.service")


class DataNotReadyError(FileNotFoundError):
    """Raised when the processed dataset does not exist yet."""


def load_data(path: str | Path | None = None) -> pd.DataFrame:
    """Load the cleaned parquet produced by the ETL.

    Raises ``DataNotReadyError`` (a ``FileNotFoundError``) with an actionable
    message instead of a bare pyarrow error if the file is missing.
    """
    path = Path(path or settings.processed_path)
    if not path.exists():
        raise DataNotReadyError(
            f"Processed data not found at {path}. Run the ETL first: `python etl.py`."
        )
    df = pd.read_parquet(path)
    logger.info("Loaded %d rows from %s", len(df), path)
    return df


def _as_list(values: Iterable | None) -> list | None:
    if values is None:
        return None
    return list(values)


def filter_data(
    df: pd.DataFrame,
    years: Sequence | None = None,
    chemicals: Sequence | None = None,
) -> pd.DataFrame:
    """Filter by year and/or chemical. ``None`` means 'no filter on this field'.

    Unlike the original, missing columns or empty selections degrade
    gracefully instead of raising ``KeyError``.
    """
    mask = pd.Series(True, index=df.index)
    years = _as_list(years)
    chemicals = _as_list(chemicals)

    if years is not None and "Year" in df.columns:
        mask &= df["Year"].isin(years)
    if chemicals is not None and "Chemical" in df.columns:
        mask &= df["Chemical"].isin(chemicals)
    return df[mask]


def yearly_emissions(
    df: pd.DataFrame, measures: Sequence[str] | None = None
) -> pd.DataFrame:
    """Sum the given measure columns per year. Returns an empty frame if no data."""
    measures = list(measures) if measures is not None else list(AIR_COLUMNS)
    measures = [m for m in measures if m in df.columns]
    if df.empty or "Year" not in df.columns or not measures:
        return pd.DataFrame(columns=measures)
    out = df.groupby("Year")[measures].sum(min_count=1)
    return out.sort_index()


def top_chemicals(
    df: pd.DataFrame, measure: str = "Total Air", n: int = 10
) -> pd.Series:
    """Top-``n`` chemicals by total of ``measure``."""
    if df.empty or measure not in df.columns or "Chemical" not in df.columns:
        return pd.Series(dtype="float64", name=measure)
    return (
        df.groupby("Chemical")[measure]
        .sum(min_count=1)
        .sort_values(ascending=False)
        .head(n)
    )


def summary_kpis(df: pd.DataFrame, measure: str = "Total Air") -> dict:
    """Headline metrics for the KPI row.

    Returns the cumulative total, plus the *peak year* and its value — fixing
    the original bug where "Max Year" actually showed a quantity, not a year.
    """
    empty = {
        "total": 0.0,
        "peak_year": None,
        "peak_value": 0.0,
        "n_years": 0,
        "n_chemicals": 0,
    }
    if df.empty or measure not in df.columns or "Year" not in df.columns:
        return empty

    by_year = df.groupby("Year")[measure].sum(min_count=1).dropna()
    if by_year.empty:
        return empty

    peak_year = int(by_year.idxmax())
    return {
        "total": float(by_year.sum()),
        "peak_year": peak_year,
        "peak_value": float(by_year.max()),
        "n_years": int(df["Year"].nunique()),
        "n_chemicals": int(df["Chemical"].nunique()) if "Chemical" in df else 0,
    }


def available_filters(df: pd.DataFrame) -> tuple[list[int], list[str]]:
    """Sorted distinct years and chemicals available for the filter widgets."""
    years = (
        sorted(int(y) for y in df["Year"].dropna().unique())
        if "Year" in df.columns
        else []
    )
    chemicals = (
        sorted(df["Chemical"].dropna().unique().tolist())
        if "Chemical" in df.columns
        else []
    )
    return years, chemicals
