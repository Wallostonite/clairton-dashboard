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

import altair as alt
import pandas as pd
import streamlit as st

from config import AIR_COLUMNS, MEASUREMENT_UNIT, settings
import analysis
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

# --- Emissions impact analysis (research) ----------------------------------
# This section is analyte-focused (lead / mercury / PAHs) and uses the full
# dataset rather than the sidebar filters, since the research targets fixed
# groups via the atmospheric-deposition pathway.
st.divider()
st.header("🔬 Emissions impact analysis")
st.caption(
    "Atmospheric-deposition view for the analytes measured in sediment cores. "
    "Air pathway = fugitive + stack emissions."
)

ic1, ic2 = st.columns([2, 3])
group_name = ic1.selectbox(
    "Analyte group", [*analysis.CHEMICAL_GROUPS.keys(), "All core analytes"]
)
air_only = ic2.toggle(
    "Air pathway only (fugitive + stack)",
    value=True,
    help="Off = include the total on-/off-site release for context.",
)

group_chems = (
    analysis.CORE_ANALYTES
    if group_name == "All core analytes"
    else analysis.CHEMICAL_GROUPS[group_name]
)
present = [c for c in group_chems if c in df["Chemical"].unique()]

if not present:
    st.info(f"None of the {group_name} analytes are present in this dataset.")
else:
    pathway = (
        analysis.AIR_PATHWAY if air_only else ["Total on- and off-site releases"]
    )
    annual = analysis.annual_air_emissions(df, present, pathway)

    if annual.dropna().empty:
        st.info("No emissions recorded for this group/pathway.")
    else:
        cum = analysis.cumulative_burden(annual)
        mk = analysis.mann_kendall(annual.index.astype(int), annual.values)
        pct = analysis.pct_change_since_peak(annual)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Cumulative burden", f"{cum.iloc[-1]:,.0f} {MEASUREMENT_UNIT}")
        k2.metric("Peak year", str(int(annual.idxmax())))
        trend_arrow = {"increasing": "↑", "decreasing": "↓"}.get(mk["trend"], "→")
        k3.metric(
            "Trend (Mann-Kendall)",
            f"{trend_arrow} {mk['trend']}",
            help=(
                f"Sen's slope {mk['sen_slope']:,.1f} {MEASUREMENT_UNIT}/yr, "
                f"p={mk['p']:.3f}, n={mk['n']}"
                if mk["sen_slope"] is not None
                else "Not enough data points"
            ),
        )
        k4.metric(
            "Change since peak",
            "—" if pct is None else f"{pct:+.0f}%",
        )

        # Time series with regulatory-event markers (Altair ships with Streamlit).
        plot_df = annual.rename("Emissions").reset_index()
        plot_df["Year"] = plot_df["Year"].astype(int)
        line = (
            alt.Chart(plot_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("Year:Q", axis=alt.Axis(format="d", title="Year")),
                y=alt.Y("Emissions:Q", title=f"Emissions ({MEASUREMENT_UNIT})"),
                tooltip=["Year", alt.Tooltip("Emissions:Q", format=",.0f")],
            )
        )
        ymin, ymax = int(plot_df["Year"].min()), int(plot_df["Year"].max())
        events = [(y, lbl) for y, lbl in analysis.REGULATORY_EVENTS if ymin <= y <= ymax]
        layers = [line]
        if events:
            ev_df = pd.DataFrame(events, columns=["Year", "label"])
            rules = (
                alt.Chart(ev_df)
                .mark_rule(color="#d62728", strokeDash=[4, 4])
                .encode(x="Year:Q", tooltip=["label"])
            )
            text = (
                alt.Chart(ev_df)
                .mark_text(align="left", angle=270, dx=4, dy=-4, color="#d62728")
                .encode(x="Year:Q", text="label")
            )
            layers += [rules, text]
        st.altair_chart(alt.layer(*layers).interactive(), use_container_width=True)

        st.area_chart(
            cum.rename("Cumulative burden"),
            y_label=MEASUREMENT_UNIT,
            x_label="Year",
        )

        # PAH source fingerprint: low Phenanthrene/Anthracene => pyrogenic
        # (combustion) source such as a coke oven.
        if group_name in ("PAHs", "All core analytes"):
            ratio = analysis.pah_diagnostic_ratio(df, pathway=pathway)
            if not ratio.empty:
                st.subheader("PAH source fingerprint")
                st.caption(
                    "Phenanthrene/Anthracene ratio — low, stable values indicate "
                    "a pyrogenic (combustion) source consistent with coke ovens."
                )
                rk1, rk2 = st.columns([1, 3])
                rk1.metric("Latest Phe/Ant", f"{ratio.iloc[-1]:.2f}")
                ratio_df = ratio.reset_index()
                ratio_df["Year"] = ratio_df["Year"].astype(int)
                rk2.altair_chart(
                    alt.Chart(ratio_df)
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("Year:Q", axis=alt.Axis(format="d", title="Year")),
                        y=alt.Y(f"{ratio.name}:Q", title="Phe/Ant ratio"),
                    ),
                    use_container_width=True,
                )

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
