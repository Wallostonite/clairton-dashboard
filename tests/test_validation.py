import pandas as pd
import pytest

from validation import CriticalDataQualityError, validate, validate_or_raise


def test_clean_data_passes(clean_df):
    report = validate(clean_df)
    assert report.ok, report.summary()


def test_duplicate_key_is_an_error(clean_df):
    dupe = pd.concat([clean_df, clean_df.iloc[[0]]], ignore_index=True)
    report = validate(dupe)
    assert not report.ok
    assert any(c.name == "unique_key" for c in report.errors)


def test_negative_measure_is_an_error(clean_df):
    bad = clean_df.copy()
    bad.loc[0, "Total Air"] = -5
    report = validate(bad)
    assert any(c.name == "no_negative_measures" for c in report.errors)


def test_year_out_of_range_is_an_error(clean_df):
    bad = clean_df.copy()
    bad.loc[0, "Year"] = 1700
    report = validate(bad)
    assert any(c.name == "year_in_range" for c in report.errors)


def test_validate_or_raise_strict(clean_df):
    bad = clean_df.copy()
    bad.loc[0, "Total Air"] = -1
    with pytest.raises(CriticalDataQualityError):
        validate_or_raise(bad, strict=True)
    # Non-strict returns the report without raising.
    report = validate_or_raise(bad, strict=False)
    assert not report.ok


def test_report_roundtrips_to_json(clean_df, tmp_path):
    report = validate(clean_df)
    path = tmp_path / "r.json"
    report.save(path)
    assert path.exists()
    assert '"ok": true' in path.read_text()
