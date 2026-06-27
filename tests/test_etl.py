import pandas as pd

import etl


def test_load_raw_detects_header_and_drops_banner(raw_csv):
    df = etl.load_raw(raw_csv)
    assert "Facility name" in df.columns
    assert "Total Air" in df.columns
    # 3 data rows, banner rows removed.
    assert len(df) == 3


def test_clean_coerces_all_measures_and_missing_markers(raw_csv):
    df = etl.clean(etl.load_raw(raw_csv))
    # Numeric coercion across measure columns.
    assert pd.api.types.is_numeric_dtype(df["Total Air"])
    assert pd.api.types.is_numeric_dtype(df["Off-site release"])
    # '.' became NaN.
    assert df.loc[df["Chemical"] == "Ammonia", "Off-site release"].isna().all()
    # Whitespace value " 100 " parsed to 100.
    row = df[(df["Year"] == 1989) & (df["Chemical"] == "Ammonia")].iloc[0]
    assert row["Fugitive Air"] == 100
    # Quoted code apostrophe stripped.
    assert df["Zip Code"].iloc[0] == "15025"
    # Year is a nullable integer.
    assert str(df["Year"].dtype) == "Int64"


def test_clean_is_deduplicated_and_sorted(raw_csv):
    df = etl.clean(etl.load_raw(raw_csv))
    assert df.duplicated(subset=["Year", "Chemical"]).sum() == 0
    assert df["Year"].tolist() == sorted(df["Year"].tolist())


def test_process_data_writes_parquet_and_report(raw_csv, tmp_path):
    out = tmp_path / "out" / "clean.parquet"
    report_path = tmp_path / "out" / "report.json"
    report = etl.process_data(raw_csv, out, strict=True, report_path=report_path)
    assert out.exists()
    assert report_path.exists()
    assert report.ok
    reloaded = pd.read_parquet(out)
    assert len(reloaded) == 3


def test_atomic_write_leaves_no_temp_files(clean_df, tmp_path):
    out = tmp_path / "x.parquet"
    etl.write_parquet_atomic(clean_df, out)
    assert out.exists()
    assert not list(tmp_path.glob("*.tmp"))
