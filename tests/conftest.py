"""Shared pytest fixtures."""
import sys
from pathlib import Path

import pandas as pd
import pytest

# Make the project root importable (etl, service, config, validation).
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def raw_csv(tmp_path) -> Path:
    """A tiny raw export that mirrors the real file's quirks: two banner rows,
    a BOM, '.' missing markers, quoted codes and stray whitespace."""
    content = (
        "﻿Data Source: test dataset,,,\n"
        " ,,,\n"
        "Facility name,Year,Chemical,CAS,Zip Code,Fugitive Air,Stack Air,Total Air,Off-site release\n"
        "USS-CLAIRTON PLANT,1988,Ammonia,'0007664417','15025',2400000,0,2400000,.\n"
        "USS-CLAIRTON PLANT,1989,Ammonia,'0007664417','15025', 100 ,50,150,.\n"
        "USS-CLAIRTON PLANT,1988,Benzene,'0000071432','15025',10,5,15,3\n"
    )
    p = tmp_path / "raw.csv"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def clean_df() -> pd.DataFrame:
    """A small already-clean frame for service/validation tests."""
    return pd.DataFrame(
        {
            "Facility name": ["USS-CLAIRTON PLANT"] * 4,
            "Year": pd.array([1988, 1988, 1989, 1989], dtype="Int64"),
            "Chemical": ["Ammonia", "Benzene", "Ammonia", "Benzene"],
            "Fugitive Air": [100.0, 10.0, 200.0, 20.0],
            "Stack Air": [50.0, 5.0, 60.0, 6.0],
            "Total Air": [150.0, 15.0, 260.0, 26.0],
            "Off-site release": [float("nan"), 3.0, float("nan"), 4.0],
        }
    )
