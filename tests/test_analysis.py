import numpy as np
import pandas as pd

import analysis


def test_chemical_groups_have_no_overlap_and_cover_core():
    flat = analysis.CORE_ANALYTES
    assert len(flat) == len(set(flat))  # no duplicates across groups
    assert "Lead" in analysis.CHEMICAL_GROUPS["Lead"]


def test_mann_kendall_detects_increasing_trend():
    years = list(range(2000, 2012))
    values = [float(v) for v in range(12)]  # strictly increasing
    res = analysis.mann_kendall(years, values)
    assert res["trend"] == "increasing"
    assert res["sen_slope"] == 1.0  # +1 unit/year
    assert res["p"] < 0.05


def test_mann_kendall_detects_no_trend_on_flat():
    years = list(range(2000, 2012))
    values = [5.0] * 12
    res = analysis.mann_kendall(years, values)
    assert res["trend"] == "no trend"


def test_mann_kendall_insufficient_data():
    res = analysis.mann_kendall([2000, 2001], [1.0, 2.0])
    assert res["trend"] == "insufficient data"
    assert res["sen_slope"] is None


def test_annual_air_emissions_sums_pathway():
    df = pd.DataFrame(
        {
            "Year": pd.array([2000, 2000, 2001], dtype="Int64"),
            "Chemical": ["Lead", "Lead compounds", "Lead"],
            "Fugitive Air": [10.0, 5.0, 20.0],
            "Stack Air": [1.0, 0.0, 2.0],
        }
    )
    s = analysis.annual_air_emissions(df, ["Lead", "Lead compounds"])
    assert s.loc[2000] == 16.0  # 10+5+1+0
    assert s.loc[2001] == 22.0


def test_cumulative_burden_is_monotonic():
    s = pd.Series([3.0, np.nan, 2.0], index=[2000, 2001, 2002])
    cum = analysis.cumulative_burden(s)
    assert cum.tolist() == [3.0, 3.0, 5.0]


def test_pct_change_since_peak():
    s = pd.Series([10.0, 100.0, 50.0], index=[2000, 2001, 2002])
    assert analysis.pct_change_since_peak(s) == -50.0  # 50 vs peak 100


def test_pah_ratio_computes_per_year():
    df = pd.DataFrame(
        {
            "Year": pd.array([2000, 2000], dtype="Int64"),
            "Chemical": ["Phenanthrene", "Anthracene"],
            "Fugitive Air": [80.0, 20.0],
            "Stack Air": [0.0, 0.0],
        }
    )
    r = analysis.pah_diagnostic_ratio(df)
    assert r.loc[2000] == 4.0  # 80 / 20
