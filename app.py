"""USS Clairton Plant – Environmental Impact Dashboard (Streamlit).

Run with:  streamlit run app.py

The UI is intentionally thin: all data logic lives in ``service.py`` and the
ETL in ``etl.py``. If the processed parquet is missing the app tries to build
it from the raw file once, then shows a clear, actionable error if that fails
— instead of crashing with a pyarrow stack trace.
"""
from __future__ import annotations

import json
import logging

import pandas as pd
import streamlit as st

from config import AIR_COLUMNS, MEASUREMENT_UNIT, settings
import etl
import service

logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="Clairton Plant – Environmental Impact",
    page_icon="🏭",
    layout="wide",
)


# --- Data loading (with one-shot ETL fallback) -----------------------------
@st.cache_data(show_spinner="Loading data…")
def get_data() -> pd.DataFrame:
    try:
        return service.load_data()
    except service.DataNotReadyError:
        # Processed file missing — try to build it once from the raw export.
        if settings.raw_path.exists():
            etl.process_data(strict=False)
            return service.load_data()
        raise


@st.cache_data(show_spinner=False)
def get_quality_report() -> dict | None:
    path = settings.report_path
    if path.exists():
        return json.loads(path.read_text())
    return None


try:
    df = get_data()
except FileNotFoundError as exc:
    st.title("USS Clairton Plant – Environmental Impact Dashboard")
    st.error(str(exc))
    st.info(
        "Place the raw TRI export at `data/raw/USS-CLAIRTON PLANT.csv` and run "
        "`python etl.py`, then reload."
    )
    st.stop()


# --- Header ----------------------------------------------------------------
st.title("🏭 USS Clairton Plant – Environmental Impact Dashboard")
st.caption(
    f"EPA Toxics Release Inventory · all quantities in **{MEASUREMENT_UNIT}** · "
    "use the sidebar to filter."
)

# --- Sidebar filters -------------------------------------------------------
st.sidebar.header("Filters")
all_years, all_chemicals = service.available_filters(df)

if not all_years:
    st.error("The dataset has no usable rows. Re-run the ETL.")
    st.stop()

year_range = st.sidebar.slider(
    "Year range",
    min_value=min(all_years),
    max_value=max(all_years),
    value=(min(all_years), max(all_years)),
)
selected_years = [y for y in all_years if year_range[0] <= y <= year_range[1]]

# Default to the 10 chemicals with the highest total air emissions so the
# initial view is meaningful rather than an unreadable 44-series chart.
default_chems = service.top_chemicals(df, "Total Air", n=10).index.tolist()
selected_chemicals = st.sidebar.multiselect(
    "Chemical", all_chemicals, default=default_chems or all_chemicals[:10]
)

emission_type = st.sidebar.selectbox("Emission type", AIR_COLUMNS, index=2)

# --- Apply filtering -------------------------------------------------------
filtered = service.filter_data(df, selected_years, selected_chemicals)

if filtered.empty:
    st.warning("No records match the current filters. Widen the year range or "
               "select more chemicals.")
    st.stop()

yearly = service.yearly_emissions(filtered, AIR_COLUMNS)
# Use a real temporal axis for the year. As a plain integer Streamlit adds a
# thousands separator ("2,024"); as a string it becomes categorical and rotates
# all 37 labels vertical. A datetime index gives clean, horizontal, auto-spaced
# year ticks (1990, 2000, ...).
yearly.index = pd.to_datetime(yearly.index.astype(str), format="%Y")
yearly.index.name = "Year"
kpis = service.summary_kpis(filtered, emission_type)

# --- KPI row ---------------------------------------------------------------
st.subheader("Key metrics")
c1, c2, c3, c4 = st.columns(4)
c1.metric(f"Total {emission_type}", f"{kpis['total']:,.0f} {MEASUREMENT_UNIT}")
c2.metric(
    "Peak year",
    "—" if kpis["peak_year"] is None else str(kpis["peak_year"]),
    help="Year with the highest total for the selected emission type.",
)
c3.metric("Peak-year amount", f"{kpis['peak_value']:,.0f}")
c4.metric("Chemicals selected", f"{kpis['n_chemicals']:,}")

# --- Charts ----------------------------------------------------------------
st.subheader(f"{emission_type} over time")
if emission_type in yearly.columns and not yearly.empty:
    st.line_chart(yearly[[emission_type]], y_label=MEASUREMENT_UNIT, x_label="Year")
else:
    st.info("No data for this emission type in the current selection.")

left, right = st.columns(2)

with left:
    st.subheader("Fugitive vs Stack air")
    fs_cols = [c for c in ("Fugitive Air", "Stack Air") if c in yearly.columns]
    if fs_cols:
        st.area_chart(yearly[fs_cols], y_label=MEASUREMENT_UNIT, x_label="Year")

with right:
    st.subheader("Top polluting chemicals")
    top = service.top_chemicals(filtered, emission_type, n=10)
    if not top.empty:
        st.bar_chart(top, horizontal=True, x_label=MEASUREMENT_UNIT)
    else:
        st.info("No chemical totals to show.")

st.subheader("Cumulative impact")
if emission_type in yearly.columns and not yearly.empty:
    cumulative = yearly[[emission_type]].cumsum()
    cumulative.columns = [f"Cumulative {emission_type}"]
    st.area_chart(cumulative, y_label=MEASUREMENT_UNIT, x_label="Year")

# --- Data quality + raw data -----------------------------------------------
report = get_quality_report()
if report:
    status = "✅ passed" if report.get("ok") else "⚠️ has errors"
    with st.expander(f"Data quality report — {status}"):
        m1, m2, m3 = st.columns(3)
        m1.metric("Rows", report.get("rows", "—"))
        m2.metric("Errors", report.get("n_errors", "—"))
        m3.metric("Warnings", report.get("n_warnings", "—"))
        failed = [c for c in report.get("checks", []) if not c["passed"]]
        if failed:
            st.dataframe(
                pd.DataFrame(failed)[["name", "severity", "detail"]],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.success("All quality checks passed.")

with st.expander("View / download filtered data"):
    st.dataframe(filtered, hide_index=True, use_container_width=True)
    st.download_button(
        "Download as CSV",
        filtered.to_csv(index=False).encode("utf-8"),
        file_name="clairton_filtered.csv",
        mime="text/csv",
    )
