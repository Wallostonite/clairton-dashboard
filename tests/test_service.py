import pandas as pd
import pytest

import service


def test_filter_data_none_means_all(clean_df):
    assert len(service.filter_data(clean_df)) == len(clean_df)


def test_filter_data_by_year_and_chemical(clean_df):
    out = service.filter_data(clean_df, years=[1988], chemicals=["Ammonia"])
    assert len(out) == 1
    assert out.iloc[0]["Chemical"] == "Ammonia"


def test_filter_empty_selection_returns_empty(clean_df):
    assert service.filter_data(clean_df, chemicals=[]).empty


def test_yearly_emissions_sums_per_year(clean_df):
    y = service.yearly_emissions(clean_df, ["Total Air"])
    assert y.loc[1988, "Total Air"] == 165  # 150 + 15
    assert y.loc[1989, "Total Air"] == 286  # 260 + 26


def test_top_chemicals_orders_descending(clean_df):
    top = service.top_chemicals(clean_df, "Total Air", n=10)
    assert top.index[0] == "Ammonia"  # 150 + 260 > benzene


def test_summary_kpis_reports_peak_year_not_value(clean_df):
    k = service.summary_kpis(clean_df, "Total Air")
    assert k["peak_year"] == 1989  # higher totals in 1989
    assert k["total"] == 165 + 286
    assert k["n_chemicals"] == 2


def test_summary_kpis_handles_empty():
    k = service.summary_kpis(pd.DataFrame(), "Total Air")
    assert k["peak_year"] is None and k["total"] == 0.0


def test_load_data_missing_raises_actionable(tmp_path):
    with pytest.raises(service.DataNotReadyError):
        service.load_data(tmp_path / "nope.parquet")
