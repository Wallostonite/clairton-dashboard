"""Central configuration for the Clairton TRI dashboard.

Everything that the ETL, service layer and Streamlit app need to agree on
(paths, column groups, quality thresholds) lives here so there is a single
source of truth. Paths can be overridden with environment variables, which
keeps the code portable across machines and CI without editing source.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --- Paths -----------------------------------------------------------------
# Resolve everything relative to this file so the app works regardless of the
# directory it is launched from.
BASE_DIR = Path(__file__).resolve().parent


def _path_from_env(var: str, default: Path) -> Path:
    value = os.environ.get(var)
    return Path(value).expanduser().resolve() if value else default


RAW_DATA_PATH = _path_from_env(
    "CLAIRTON_RAW_PATH", BASE_DIR / "data" / "raw" / "USS-CLAIRTON PLANT.csv"
)
PROCESSED_DATA_PATH = _path_from_env(
    "CLAIRTON_PROCESSED_PATH", BASE_DIR / "data" / "processed" / "clean_data.parquet"
)
QUALITY_REPORT_PATH = _path_from_env(
    "CLAIRTON_REPORT_PATH", BASE_DIR / "data" / "processed" / "data_quality.json"
)

# --- Schema ----------------------------------------------------------------
# Columns that identify a record. These are kept as-is (cleaned but not
# coerced to numbers).
ID_COLUMNS = [
    "Facility name",
    "TRI ID",
    "Address",
    "City",
    "County",
    "State",
    "Zip Code",
    "Year",
    "Chemical",
    "CAS",
    "Federal (F) or Commercial (C)",
    "Form Type (Form R or A)",
    "Industry",
]

# Every quantitative column in the TRI export. All are reported in pounds and
# must be coerced to numeric during ETL. The original pipeline only handled
# the three "air" columns; the rest were left as unusable strings.
MEASURE_COLUMNS = [
    "Fugitive Air",
    "Stack Air",
    "Total Air",
    "Surface Water Discharge",
    "Underground Injection",
    "Land Disposal",
    "Total on-site release",
    "Off-site release",
    "Total on- and off-site releases",
    "Transfer to recycling",
    "Transfer to energy recovery",
    "Transfer to treatment",
    "Transfer to POTWs",
    "Other off-site transfer",
    "Total transfers off-site for waste management",
    "Recycled on-site",
    "Recycled off-site",
    "Energy recovery on-site",
    "Energy recovery off-site",
    "Treated on-site",
    "Treated off-site",
    "Quantity released on- and off-site",
    "Total production-related waste managed",
    "Non production-related waste managed",
]

# The columns surfaced as "air emissions" in the dashboard.
AIR_COLUMNS = ["Fugitive Air", "Stack Air", "Total Air"]

# Natural key: one row per chemical per reporting year.
KEY_COLUMNS = ["Year", "Chemical"]

# Tokens that the source uses to mean "no data". Coerced to NaN in ETL.
NA_TOKENS = {".", "", "na", "n/a", "nan", "none", "null", "--"}

MEASUREMENT_UNIT = "pounds"


@dataclass(frozen=True)
class QualitySettings:
    """Thresholds used by the data-quality checks."""

    min_year: int = 1987  # TRI program began in 1987
    max_year: int = 2100
    # Tolerance (relative) when checking Total Air ~= Fugitive + Stack.
    air_sum_rel_tolerance: float = 0.02
    # Fraction of rows allowed to fail the air-sum consistency check.
    air_sum_max_violation_frac: float = 0.05
    expected_facility: str = "USS-CLAIRTON PLANT"


@dataclass(frozen=True)
class Settings:
    raw_path: Path = RAW_DATA_PATH
    processed_path: Path = PROCESSED_DATA_PATH
    report_path: Path = QUALITY_REPORT_PATH
    quality: QualitySettings = field(default_factory=QualitySettings)


settings = Settings()
