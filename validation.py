"""Data-quality validation for the cleaned TRI dataset.

Produces a structured report rather than printing ad-hoc messages, so the
result can be persisted to JSON, asserted on in tests, and surfaced in the
dashboard. Checks are split by severity:

* ``error``   -> the dataset is unfit for use; raised in strict mode.
* ``warning`` -> suspicious but tolerable (e.g. some missing values).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import (
    AIR_COLUMNS,
    KEY_COLUMNS,
    MEASURE_COLUMNS,
    QualitySettings,
    settings,
)


class CriticalDataQualityError(RuntimeError):
    """Raised when a dataset fails validation in strict mode."""


@dataclass
class Check:
    name: str
    passed: bool
    severity: str  # "error" | "warning"
    detail: str = ""


@dataclass
class QualityReport:
    rows: int
    columns: int
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> list[Check]:
        return [c for c in self.checks if not c.passed and c.severity == "error"]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.passed and c.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "columns": self.columns,
            "ok": self.ok,
            "n_errors": len(self.errors),
            "n_warnings": len(self.warnings),
            "checks": [asdict(c) for c in self.checks],
            "metrics": self.metrics,
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))

    def summary(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        return (
            f"[{status}] rows={self.rows} cols={self.columns} "
            f"errors={len(self.errors)} warnings={len(self.warnings)}"
        )


def validate(df: pd.DataFrame, cfg: QualitySettings | None = None) -> QualityReport:
    """Run all quality checks against a *cleaned* dataframe."""
    cfg = cfg or settings.quality
    report = QualityReport(rows=len(df), columns=df.shape[1])
    add = report.checks.append

    # 1. Non-empty
    add(Check("non_empty", len(df) > 0, "error", f"{len(df)} rows"))
    if df.empty:
        return report

    # 2. Required columns present
    required = set(KEY_COLUMNS) | set(AIR_COLUMNS)
    missing = sorted(required - set(df.columns))
    add(
        Check(
            "required_columns_present",
            not missing,
            "error",
            f"missing: {missing}" if missing else "all present",
        )
    )

    # 3. Unique natural key (Year, Chemical)
    if set(KEY_COLUMNS).issubset(df.columns):
        dupes = int(df.duplicated(subset=KEY_COLUMNS).sum())
        add(
            Check(
                "unique_key",
                dupes == 0,
                "error",
                f"{dupes} duplicate (Year, Chemical) rows",
            )
        )
        report.metrics["duplicate_keys"] = dupes

    # 4. Year within a sane range
    if "Year" in df.columns:
        years = pd.to_numeric(df["Year"], errors="coerce")
        bad = int(((years < cfg.min_year) | (years > cfg.max_year)).sum())
        add(
            Check(
                "year_in_range",
                bad == 0,
                "error",
                f"{bad} rows outside [{cfg.min_year}, {cfg.max_year}]",
            )
        )
        report.metrics["year_min"] = None if years.dropna().empty else int(years.min())
        report.metrics["year_max"] = None if years.dropna().empty else int(years.max())

    # 5. Measure columns are numeric
    present_measures = [c for c in MEASURE_COLUMNS if c in df.columns]
    non_numeric = [
        c for c in present_measures if not pd.api.types.is_numeric_dtype(df[c])
    ]
    add(
        Check(
            "measures_numeric",
            not non_numeric,
            "error",
            f"non-numeric: {non_numeric}" if non_numeric else "all numeric",
        )
    )

    # 6. No negative quantities (releases cannot be negative)
    negatives = {
        c: int((df[c] < 0).sum())
        for c in present_measures
        if pd.api.types.is_numeric_dtype(df[c]) and (df[c] < 0).any()
    }
    add(
        Check(
            "no_negative_measures",
            not negatives,
            "error",
            f"negative values: {negatives}" if negatives else "none",
        )
    )

    # 7. Missingness per measure (informational warning if any column is
    #    entirely missing, which usually signals a parsing problem).
    missing_frac = {
        c: round(float(df[c].isna().mean()), 4) for c in present_measures
    }
    report.metrics["missing_fraction"] = missing_frac
    all_missing = [c for c, f in missing_frac.items() if f >= 1.0]
    add(
        Check(
            "no_fully_missing_measures",
            not all_missing,
            "warning",
            f"fully missing: {all_missing}" if all_missing else "ok",
        )
    )

    # 8. Internal consistency: Total Air ~= Fugitive + Stack.
    if set(AIR_COLUMNS).issubset(df.columns):
        sub = df[AIR_COLUMNS].dropna()
        if not sub.empty:
            expected = sub["Fugitive Air"] + sub["Stack Air"]
            denom = expected.replace(0, np.nan)
            rel_err = (sub["Total Air"] - expected).abs() / denom
            violations = int((rel_err > cfg.air_sum_rel_tolerance).sum())
            frac = violations / len(sub)
            add(
                Check(
                    "air_sum_consistency",
                    frac <= cfg.air_sum_max_violation_frac,
                    "warning",
                    f"{violations}/{len(sub)} rows where "
                    f"Total Air != Fugitive + Stack (>{cfg.air_sum_rel_tolerance:.0%})",
                )
            )
            report.metrics["air_sum_violation_frac"] = round(frac, 4)

    # 9. Expected facility present
    if "Facility name" in df.columns:
        has_facility = (df["Facility name"] == cfg.expected_facility).any()
        add(
            Check(
                "expected_facility_present",
                bool(has_facility),
                "warning",
                f"'{cfg.expected_facility}' not found" if not has_facility else "ok",
            )
        )

    return report


def validate_or_raise(
    df: pd.DataFrame, strict: bool = True, cfg: QualitySettings | None = None
) -> QualityReport:
    """Validate and, when ``strict``, raise on any error-severity failure."""
    report = validate(df, cfg)
    if strict and not report.ok:
        details = "; ".join(f"{c.name}: {c.detail}" for c in report.errors)
        raise CriticalDataQualityError(
            f"Data failed validation ({len(report.errors)} errors): {details}"
        )
    return report
