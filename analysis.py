"""Emissions-impact analytics for the Clairton dashboard (Tier 1).

Pure numpy/pandas so it adds no heavy dependencies and is unit-testable
without Streamlit. Supports the research framing: focus on the analytes that
appear in the sediment cores (lead, mercury, PAHs), treat fugitive + stack air
as the atmospheric-deposition pathway, and quantify trend and burden.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd

# Analyte groups that match what a sediment-core study measures. Names are the
# exact TRI ``Chemical`` strings present in this dataset.
CHEMICAL_GROUPS: dict[str, list[str]] = {
    "Lead": ["Lead", "Lead compounds"],
    "Mercury": ["Mercury", "Mercury compounds"],
    "PAHs": [
        "Naphthalene",
        "Anthracene",
        "Phenanthrene",
        "Benzo[g,h,i]perylene",
        "Polycyclic aromatic compounds",
    ],
}
CORE_ANALYTES = [c for group in CHEMICAL_GROUPS.values() for c in group]

# The atmospheric pathway: only these reach the pond as deposition.
AIR_PATHWAY = ["Fugitive Air", "Stack Air"]

# Well-documented events to annotate on the time series. Editable; both are
# factual and fall inside the 1988–2024 reporting window.
REGULATORY_EVENTS: list[tuple[int, str]] = [
    (1990, "Clean Air Act Amendments"),
    (2018, "Clairton Coke Works fire"),
]


def annual_air_emissions(
    df: pd.DataFrame,
    chemicals: Sequence[str],
    pathway: Sequence[str] = AIR_PATHWAY,
) -> pd.Series:
    """Total air emissions per year (lb) for the given chemicals.

    ``pathway`` defaults to fugitive + stack air (the deposition proxy); pass
    a single-element list or other measure columns to change it.
    """
    cols = [c for c in pathway if c in df.columns]
    if df.empty or "Year" not in df.columns or not cols:
        return pd.Series(dtype="float64", name="Air emissions")
    sub = df[df["Chemical"].isin(list(chemicals))]
    if sub.empty:
        return pd.Series(dtype="float64", name="Air emissions")
    series = sub.groupby("Year")[cols].sum(min_count=1).sum(axis=1)
    series.name = "Air emissions"
    return series.sort_index()


def cumulative_burden(series: pd.Series) -> pd.Series:
    """Running cumulative total (lb) of an annual series."""
    return series.fillna(0).cumsum()


def pct_change_since_peak(series: pd.Series) -> float | None:
    """Percent change from the series' peak year to its final year."""
    s = series.dropna()
    if s.empty:
        return None
    peak = s.max()
    if peak == 0:
        return None
    return (s.iloc[-1] - peak) / peak * 100.0


def _normal_sf(z: float) -> float:
    """Upper-tail probability of the standard normal (no scipy needed)."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def mann_kendall(
    years: Sequence[int], values: Sequence[float], alpha: float = 0.05
) -> dict:
    """Mann-Kendall trend test with Sen's slope estimator.

    Returns trend direction, the two-sided p-value, the S statistic, and
    Sen's slope in lb/year. Handles ties in the variance term.
    """
    t = np.asarray(years, dtype=float)
    y = np.asarray(values, dtype=float)
    mask = ~np.isnan(y)
    t, y = t[mask], y[mask]
    n = len(y)
    empty = {"n": n, "trend": "insufficient data", "p": None, "S": 0, "sen_slope": None}
    if n < 4:
        return empty

    # Mann-Kendall S statistic.
    s = 0.0
    for k in range(n - 1):
        s += np.sum(np.sign(y[k + 1 :] - y[k]))

    # Variance with a tie correction.
    _, counts = np.unique(y, return_counts=True)
    tie_term = np.sum(counts * (counts - 1) * (2 * counts + 5))
    var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
    if var_s <= 0:
        return {**empty, "trend": "no trend", "p": 1.0}

    if s > 0:
        z = (s - 1) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / math.sqrt(var_s)
    else:
        z = 0.0
    p = 2.0 * _normal_sf(abs(z))

    # Sen's slope: median of pairwise slopes over time.
    slopes = [
        (y[j] - y[i]) / (t[j] - t[i])
        for i in range(n - 1)
        for j in range(i + 1, n)
        if t[j] != t[i]
    ]
    sen = float(np.median(slopes)) if slopes else None

    if p < alpha and s > 0:
        trend = "increasing"
    elif p < alpha and s < 0:
        trend = "decreasing"
    else:
        trend = "no trend"

    return {"n": n, "trend": trend, "p": float(p), "S": float(s), "sen_slope": sen}


def pah_diagnostic_ratio(
    df: pd.DataFrame,
    numerator: str = "Phenanthrene",
    denominator: str = "Anthracene",
    pathway: Sequence[str] = AIR_PATHWAY,
) -> pd.Series:
    """Per-year emission-side PAH ratio (e.g. Phenanthrene/Anthracene).

    Low Phe/Ant values indicate a pyrogenic (combustion) source such as a coke
    oven — a fingerprint for attributing sediment PAHs to the plant.
    """
    num = annual_air_emissions(df, [numerator], pathway)
    den = annual_air_emissions(df, [denominator], pathway)
    ratio = num / den.replace(0, np.nan)
    ratio.name = f"{numerator}/{denominator}"
    return ratio.dropna()
