# app.py
# PharmaROI Intelligence — V3 (Multi-Model Comparison)
# Run: streamlit run app.py

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference

import io

import streamlit as st
import altair as alt

try:
    import pandas as pd
except Exception:
    pd = None

# -----------------------------
# Color palette
# -----------------------------
COLORS = {
    "primary": "#0F6CBD",
    "revenue": "#0F6CBD",
    "costs": "#9CA3AF",
    "profit": "#10B981",
    "warning": "#F59E0B",
    "danger": "#EF4444",
    "muted": "#6B7280",
}

TAB_PALETTE = [
    "#0F6CBD", "#10B981", "#F59E0B", "#EF4444",
    "#8B5CF6", "#EC4899", "#06B6D4", "#84CC16",
]

# -----------------------------
# Funnel definitions
# -----------------------------
STAGE_NAMES: List[str] = [
    "Total Addressable Market for MASH",
    "F2 and F3",
    "MASH patients diagnosed",
    "Madrigal access to MASH patients",
    "Frequent users of online and social media resources",
    "Activation within 90 days mo onto Dario Connect for MASH",
    "Schedule telemedicine appointment",
    "Keep telemedicine appointment",
    "Obtain prescription for biopsy",
    "Get biopsy lab test",
    "Get positive lab results",
    "Complete post lab result consultation",
    "Get prescription for Rezdiffra",
]

SPONSOR_DEFAULTS = {
    "base_population": 10_000_000,
    "ratios": [1.00, 0.35, 0.16, 0.22, 0.75, 0.40, 0.15, 0.80, 1.00, 0.75, 0.90, 0.50, 0.90],
    "cac": [0.0, 0.0, 0.0, 0.0, 0.0, 10.0, 67.0, 83.0, 83.0, 111.0, 123.0, 247.0, 274.0],
    "arpp": 47_400.0,
    "treatment_years": 1.0,
    "discount": 0.68,
    "stage_active": [True] * len(STAGE_NAMES),
    "stage_names": STAGE_NAMES[:],
}

ZERO_SAMPLE = {
    "base_population": 0,
    "ratios": [0.0] * len(STAGE_NAMES),
    "cac": [0.0] * len(STAGE_NAMES),
    "arpp": 0.0,
    "treatment_years": 1.0,
    "discount": 0.0,
    "stage_active": [True] * len(STAGE_NAMES),
    "stage_names": ["Insert Stage Name"] * len(STAGE_NAMES),
}


# -----------------------------
# Formatting helpers
# -----------------------------
def clamp(x, lo, hi):
    return max(lo, min(hi, float(x)))

def money(x):
    return f"${x:,.0f}"

def number(x):
    return f"{x:,.0f}"

def pct(x):
    return f"{x*100:,.1f}%"

def roix(x):
    return f"{x:,.2f}x"


# -----------------------------
# Core computations
# -----------------------------
@dataclass(frozen=True)
class StageInput:
    name: str
    active: bool
    ratio: float
    cac: float

@dataclass(frozen=True)
class StageResult:
    name: str
    active: bool
    ratio_used: float
    patients: float
    cac_per_patient: float
    stage_cac: float
    cumulative_cac: float


def compute_funnel(stages: List[StageInput], base_population: float) -> List[StageResult]:
    results = []
    prev_patients = max(0.0, float(base_population))
    cumulative = 0.0

    for idx, s in enumerate(stages):
        if idx == 0:
            patients = prev_patients
            ratio_used = 1.0
        else:
            ratio_used = 1.0 if not s.active else clamp(s.ratio, 0.0, 1.0)
            patients = prev_patients * ratio_used

        cac_pp = 0.0 if not s.active else max(0.0, float(s.cac))
        stage_cac = patients * cac_pp
        cumulative += stage_cac

        results.append(StageResult(
            name=s.name, active=s.active, ratio_used=ratio_used,
            patients=patients, cac_per_patient=cac_pp,
            stage_cac=stage_cac, cumulative_cac=cumulative,
        ))
        prev_patients = patients

    return results


def compute_financials(treated_patients, arpp, treatment_years, discount, funnel_cac_total):
    treated = max(0.0, float(treated_patients))
    arpp = max(0.0, float(arpp))
    years = max(0.0, float(treatment_years))
    disc = clamp(discount, 0.0, 0.80)
    funnel_cac = max(0.0, float(funnel_cac_total))

    gross = treated * arpp * years
    net = gross * (1.0 - disc)
    roi = (net / funnel_cac) if funnel_cac > 0 else float("nan")

    return {
        "treated_patients": treated,
        "gross_revenue": gross,
        "net_revenue": net,
        "discount": disc,
        "funnel_cac_total": funnel_cac,
        "net_profit": net,
        "roi_net": roi,
    }


def run_model(state: dict):
    """Given a model state dict, return (funnel_results, fin)."""
    stage_names = state.get("stage_names", STAGE_NAMES)
    stages = []
    for idx, name in enumerate(stage_names):
        stages.append(StageInput(
            name=name,
            active=bool(state["stage_active"][idx]),
            ratio=float(state["ratios"][idx]) if idx > 0 else 1.0,
            cac=float(state["cac"][idx]),
        ))
    base_pop = float(state["base_population"])
    funnel_results = compute_funnel(stages, base_pop)
    fin = compute_financials(
        treated_patients=funnel_results[-1].patients,
        arpp=float(state["arpp"]),
        treatment_years=float(state["treatment_years"]),
        discount=float(state["discount"]),
        funnel_cac_total=funnel_results[-1].cumulative_cac,
    )
    return funnel_results, fin


# -----------------------------
# Excel export
# -----------------------------
def build_polished_excel_report(df_funnel, fin, colors):
    wb = Workbook()
    header_fill = PatternFill("solid", fgColor="0F172A")
    header_font = Font(bold=True, color="FFFFFF")
    bold_font = Font(bold=True)
    muted_font = Font(color="6B7280")
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    def set_col_widths(ws, widths):
        for col_idx, w in widths.items():
            ws.column_dimensions[get_column_letter(col_idx)].width = w

    def style_header_row(ws, row=1):
        for cell in ws[row]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center

    ws_sum = wb.active
    ws_sum.title = "Summary"
    ws_sum["A1"] = "PharmaROI Intelligence — Sponsor Summary"
    ws_sum["A1"].font = Font(bold=True, size=14)
    ws_sum.merge_cells("A1:D1")

    summary_rows = [
        ("Treated Patients", fin["treated_patients"], "0"),
        ("Gross Revenue", fin["gross_revenue"], "$#,##0"),
        ("Discount", fin["discount"], "0.0%"),
        ("Net Revenue", fin["net_revenue"], "$#,##0"),
        ("Funnel CAC Total", fin["funnel_cac_total"], "$#,##0"),
        ("Net Profit", fin["net_profit"], "$#,##0"),
        ("ROI (Net)", fin["roi_net"], "0.00x"),
    ]

    ws_sum["A3"] = "Metric"; ws_sum["B3"] = "Value"; ws_sum["C3"] = "Format"; ws_sum["D3"] = "Notes"
    style_header_row(ws_sum, 3)

    start_row = 4
    for i, (label, value, fmt) in enumerate(summary_rows):
        r = start_row + i
        ws_sum[f"A{r}"] = label
        ws_sum[f"B{r}"] = float(value) if value == value else None
        ws_sum[f"C{r}"] = fmt
        ws_sum[f"D{r}"] = ""
        ws_sum[f"A{r}"].font = bold_font if label in ("Net Revenue", "ROI (Net)") else Font()
        ws_sum[f"A{r}"].alignment = left
        ws_sum[f"B{r}"].alignment = left
        ws_sum[f"C{r}"].font = muted_font
        ws_sum[f"B{r}"].number_format = fmt

    ws_sum.freeze_panes = "A4"
    set_col_widths(ws_sum, {1: 26, 2: 18, 3: 12, 4: 20})

    ws_fun = wb.create_sheet("Funnel")
    headers = list(df_funnel.columns)
    for c, h in enumerate(headers, start=1):
        ws_fun.cell(row=1, column=c, value=h)
    style_header_row(ws_fun, 1)

    for r_idx, row in enumerate(df_funnel.itertuples(index=False), start=2):
        for c_idx, val in enumerate(row, start=1):
            ws_fun.cell(row=r_idx, column=c_idx, value=val)

    ws_fun.freeze_panes = "A2"
    col_map = {name: i + 1 for i, name in enumerate(headers)}

    def fmt_col(col_name, number_format):
        if col_name not in col_map:
            return
        col = col_map[col_name]
        for rr in range(2, 2 + len(df_funnel)):
            ws_fun.cell(row=rr, column=col).number_format = number_format

    fmt_col("Patients", "0")
    fmt_col("CAC ($/pt)", "$#,##0")
    fmt_col("Stage CAC ($)", "$#,##0")
    fmt_col("Cumulative CAC ($)", "$#,##0")
    set_col_widths(ws_fun, {1: 5, 2: 52, 3: 22, 4: 12, 5: 14, 6: 12, 7: 15, 8: 18})

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


# -----------------------------
# Session state bootstrap
# -----------------------------
def init_session():
    if "models" not in st.session_state:
        st.session_state["models"] = [copy.deepcopy(SPONSOR_DEFAULTS)]
        st.session_state["model_names"] = ["Model 1"]
        st.session_state["active_model_idx"] = 0

init_session()


# -----------------------------
# Page config
# -----------------------------
st.set_page_config(page_title="PharmaROI V3 — Multi-Model", page_icon="📈", layout="wide")
st.title("PharmaROI Intelligence — V3 (Multi-Model Comparison)")
st.caption("Build multiple ROI models side-by-side and compare them in the Comparison tab.")


# -----------------------------
# Model management bar
# -----------------------------
mgmt_col1, mgmt_col2, mgmt_col3, mgmt_col4 = st.columns([2, 2, 2, 4])

with mgmt_col1:
    if st.button("➕ Add New Model", use_container_width=True):
        n = len(st.session_state["models"]) + 1
        st.session_state["models"].append(copy.deepcopy(SPONSOR_DEFAULTS))
        st.session_state["model_names"].append(f"Model {n}")
        st.session_state["active_model_idx"] = len(st.session_state["models"]) - 1
        st.rerun()

with mgmt_col2:
    copy_options = st.session_state["model_names"]
    copy_source = st.selectbox(
        "Copy from:",
        options=range(len(copy_options)),
        format_func=lambda i: copy_options[i],
        index=st.session_state["active_model_idx"],  # Defaults to current model
        key="copy_source_select",
        label_visibility="collapsed",
    )
    if st.button("📋 Copy This Model", use_container_width=True):
        source_idx = copy_source
        new_state = copy.deepcopy(st.session_state["models"][source_idx])
        new_name = st.session_state["model_names"][source_idx] + " (copy)"
        st.session_state["models"].append(new_state)
        st.session_state["model_names"].append(new_name)
        st.session_state["active_model_idx"] = len(st.session_state["models"]) - 1
        st.rerun()


with mgmt_col3:
    can_delete = len(st.session_state["models"]) > 1
    if st.button("Delete Current", use_container_width=True, disabled=not can_delete):
        idx = st.session_state["active_model_idx"]
        st.session_state["models"].pop(idx)
        st.session_state["model_names"].pop(idx)
        st.session_state["active_model_idx"] = max(0, idx - 1)
        st.rerun()

with mgmt_col4:
    # Rename current model
    idx = st.session_state["active_model_idx"]
    new_name = st.text_input(
        "Rename current model:",
        value=st.session_state["model_names"][idx],
        key=f"rename_model_{idx}",
        label_visibility="collapsed",
        placeholder="Rename current model…",
    )
    if new_name != st.session_state["model_names"][idx]:
        st.session_state["model_names"][idx] = new_name
        



# -----------------------------
# Tabs: one per model + Comparison
# -----------------------------
tab_labels = st.session_state["model_names"] + ["Comparison"]
tabs = st.tabs(tab_labels)

# Keep track of which tab is being viewed to set active_model_idx
# (Streamlit tabs don't expose which is active, so we use a workaround via buttons in sidebar)

for model_idx, model_tab in enumerate(tabs[:-1]):
    with model_tab:
        state = st.session_state["models"][model_idx]
        model_name = st.session_state["model_names"][model_idx]
        tab_color = TAB_PALETTE[model_idx % len(TAB_PALETTE)]

        # When user clicks into this tab render its sidebar controls
        # We render controls inline (above a divider) since each tab has its own scope
        with st.expander("Model Settings", expanded=(model_idx == st.session_state["active_model_idx"])):
            st.session_state["active_model_idx"] = model_idx

            col_r1, col_r2 = st.columns(2)
            with col_r1:
                if st.button("Reset: Sponsor Example", key=f"reset_sponsor_{model_idx}"):
                    st.session_state["models"][model_idx] = copy.deepcopy(SPONSOR_DEFAULTS)
                    st.rerun()
            with col_r2:
                if st.button("Reset: Zero", key=f"reset_zero_{model_idx}"):
                    st.session_state["models"][model_idx] = copy.deepcopy(ZERO_SAMPLE)
                    st.rerun()

            st.markdown("**Base Population**")
            state["base_population"] = st.number_input(
                "Stage 1 — Total Addressable Market",
                min_value=0, step=100_000,
                value=int(state["base_population"]),
                key=f"base_pop_{model_idx}",
            )

            st.markdown("**Revenue & Costs**")
            c1, c2, c3 = st.columns(3)
            with c1:
                state["arpp"] = st.number_input(
                    "ARPP ($/year)",
                    min_value=0.0, step=1_000.0,
                    value=float(state["arpp"]),
                    key=f"arpp_{model_idx}",
                )
            with c2:
                state["treatment_years"] = st.slider(
                    "Treatment years",
                    min_value=0.1, max_value=5.0, step=0.1,
                    value=float(state["treatment_years"]),
                    key=f"years_{model_idx}",
                )
            with c3:
                state["discount"] = st.slider(
                    "Discount (gross→net)",
                    min_value=0.0, max_value=1.0, step=0.01,
                    value=float(state["discount"]),
                    key=f"discount_{model_idx}",
                )

            st.markdown("**Funnel Stages**")
            stage_names = state.get("stage_names", STAGE_NAMES[:])

            with st.expander("Customize Stage Names"):
                for sidx in range(len(STAGE_NAMES)):
                    stage_names[sidx] = st.text_input(
                        f"Stage {sidx+1} name:",
                        value=stage_names[sidx],
                        key=f"sname_{model_idx}_{sidx}",
                    )
                state["stage_names"] = stage_names

            for sidx, sname in enumerate(stage_names):
                with st.expander(f"{sidx+1}. {sname}", expanded=False):
                    state["stage_active"][sidx] = st.checkbox(
                        "Use this stage",
                        value=bool(state["stage_active"][sidx]),
                        key=f"active_{model_idx}_{sidx}",
                    )
                    if sidx == 0:
                        st.info("Stage 1 is the base population. No ratio applied.")
                    else:
                        disabled = not state["stage_active"][sidx]
                        state["ratios"][sidx] = st.slider(
                            "Funnel ratio",
                            min_value=0.0, max_value=1.0, step=0.01,
                            value=float(state["ratios"][sidx]),
                            disabled=disabled,
                            key=f"ratio_{model_idx}_{sidx}",
                        )
                    disabled = not state["stage_active"][sidx]
                    state["cac"][sidx] = st.number_input(
                        "CAC ($ per patient)",
                        min_value=0.0, step=1.0,
                        value=float(state["cac"][sidx]),
                        disabled=disabled,
                        key=f"cac_{model_idx}_{sidx}",
                    )

        # ----- Compute -----
        funnel_results, fin = run_model(state)

        # ----- KPI strip -----
        st.markdown(f"<div style='border-left: 4px solid {tab_color}; padding-left: 12px; margin-bottom: 8px;'><strong style='font-size:1.1rem'>{model_name}</strong></div>", unsafe_allow_html=True)

        roi = fin["roi_net"]
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("ROI (Net)", roix(roi) if roi == roi else "—")
        k2.metric("Treated Patients", number(fin["treated_patients"]))
        k3.metric("Net Revenue", money(fin["net_revenue"]))
        k4.metric("Gross Revenue", money(fin["gross_revenue"]))
        k5.metric("Funnel CAC", money(fin["funnel_cac_total"]))

        st.markdown(
            f"Gross: **{money(fin['gross_revenue'])}**  |  "
            f"Discount: **{fin['discount']*100:.1f}%**  |  "
            f"Net: **{money(fin['net_revenue'])}**"
        )

        # ----- Funnel table -----
        st.subheader("Funnel Table")
        table_rows = []
        for ridx, r in enumerate(funnel_results):
            table_rows.append({
                "#": ridx + 1,
                "Stage": r.name,
                "Status": "Active" if r.active else "Inactive (pass-through)",
                "Ratio Used": "—" if ridx == 0 else pct(r.ratio_used),
                "Patients": float(r.patients),
                "CAC ($/pt)": float(r.cac_per_patient),
                "Stage CAC ($)": float(r.stage_cac),
                "Cumulative CAC ($)": float(r.cumulative_cac),
            })

        if pd is not None:
            df_funnel = pd.DataFrame(table_rows)
            df_display = df_funnel.copy()
            df_display["Patients"] = df_display["Patients"].map(lambda x: f"{x:,.0f}")
            df_display["CAC ($/pt)"] = df_display["CAC ($/pt)"].map(lambda x: f"${x:,.0f}")
            df_display["Stage CAC ($)"] = df_display["Stage CAC ($)"].map(lambda x: f"${x:,.0f}")
            df_display["Cumulative CAC ($)"] = df_display["Cumulative CAC ($)"].map(lambda x: f"${x:,.0f}")
            st.dataframe(df_display, use_container_width=True, hide_index=True)

            # Export
            st.markdown("### Export")
            ec1, ec2 = st.columns(2)
            with ec1:
                xlsx_bytes = build_polished_excel_report(df_funnel, fin, COLORS)
                st.download_button(
                    "⬇️ Download Excel Report",
                    data=xlsx_bytes,
                    file_name=f"{model_name.replace(' ', '_')}_report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_xlsx_{model_idx}",
                )
            with ec2:
                csv_data = df_funnel.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇️ Download CSV",
                    data=csv_data,
                    file_name=f"{model_name.replace(' ', '_')}_funnel.csv",
                    mime="text/csv",
                    key=f"dl_csv_{model_idx}",
                )
        else:
            st.write(table_rows)

        # ----- Waterfall chart -----
        st.subheader("Revenue Waterfall")
        waterfall_data = [
            {"Metric": "Gross Revenue", "Start": 0, "End": fin["gross_revenue"], "Type": "revenue", "Label": fin["gross_revenue"]},
            {"Metric": "Discount", "Start": fin["net_revenue"], "End": fin["gross_revenue"], "Type": "negative", "Label": -(fin["gross_revenue"] - fin["net_revenue"])},
            {"Metric": "Net Revenue", "Start": 0, "End": fin["net_revenue"], "Type": "subtotal", "Label": fin["net_revenue"]},
        ]
        color_scale = alt.Scale(
            domain=["revenue", "negative", "subtotal"],
            range=[COLORS["revenue"], COLORS["danger"], COLORS["primary"]],
        )
        if pd is not None:
            wdf = pd.DataFrame(waterfall_data)
            bars = alt.Chart(wdf).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=80).encode(
                x=alt.X("Metric:N", sort=None, title=None, axis=alt.Axis(labelAngle=0, labelFontSize=13)),
                y=alt.Y("Start:Q", title="USD", axis=alt.Axis(format="$,.0f")),
                y2=alt.Y2("End:Q"),
                color=alt.Color("Type:N", scale=color_scale, legend=None),
                tooltip=[alt.Tooltip("Metric:N"), alt.Tooltip("Label:Q", format="$,.0f", title="Value")],
            )
            text = alt.Chart(wdf).mark_text(dy=-10, fontSize=12, fontWeight="bold").encode(
                x=alt.X("Metric:N", sort=None),
                y=alt.Y("End:Q"),
                text=alt.Text("Label:Q", format="$,.0f"),
                color=alt.Color("Type:N", scale=color_scale, legend=None),
            )
            st.altair_chart((bars + text).properties(height=400), use_container_width=True)

        # ----- Funnel visualization -----
        with st.expander("Funnel Visualization"):
            if pd is not None:
                fdf = pd.DataFrame([{"Stage": r.name, "Patients": r.patients} for r in funnel_results])
                fchart = alt.Chart(fdf).mark_bar().encode(
                    y=alt.Y("Stage:N", sort="-x", title=None),
                    x=alt.X("Patients:Q", title="Patients"),
                    color=alt.value(tab_color),
                    tooltip=[alt.Tooltip("Patients:Q", format=",.0f"), "Stage:N"],
                )
                st.altair_chart(fchart, use_container_width=True)


# -----------------------------
# Comparison Tab
# -----------------------------
with tabs[-1]:
    st.subheader("Model Comparison")

    if len(st.session_state["models"]) < 2:
        st.info("Add at least 2 models to compare them here.")
    else:
        # Build comparison data
        comparison_rows = []
        for midx, (mstate, mname) in enumerate(zip(st.session_state["models"], st.session_state["model_names"])):
            funnel_results, fin = run_model(mstate)
            roi = fin["roi_net"]
            comparison_rows.append({
                "Model": mname,
                "Treated Patients": fin["treated_patients"],
                "Gross Revenue": fin["gross_revenue"],
                "Net Revenue": fin["net_revenue"],
                "Funnel CAC": fin["funnel_cac_total"],
                "Discount": fin["discount"],
                "ROI (Net)": roi if roi == roi else 0.0,
            })

        if pd is not None:
            comp_df = pd.DataFrame(comparison_rows)

            # Summary table
            st.markdown("### Key Metrics")
            disp = comp_df.copy()
            disp["Treated Patients"] = disp["Treated Patients"].map(lambda x: f"{x:,.0f}")
            disp["Gross Revenue"] = disp["Gross Revenue"].map(lambda x: f"${x:,.0f}")
            disp["Net Revenue"] = disp["Net Revenue"].map(lambda x: f"${x:,.0f}")
            disp["Funnel CAC"] = disp["Funnel CAC"].map(lambda x: f"${x:,.0f}")
            disp["Discount"] = disp["Discount"].map(lambda x: f"{x*100:.1f}%")
            disp["ROI (Net)"] = disp["ROI (Net)"].map(lambda x: f"{x:.2f}x")
            st.dataframe(disp, use_container_width=True, hide_index=True)

            st.markdown("### Charts")
            chart_col1, chart_col2 = st.columns(2)

            model_color_scale = alt.Scale(
                domain=st.session_state["model_names"],
                range=TAB_PALETTE[:len(st.session_state["model_names"])],
            )

            with chart_col1:
                st.markdown("**ROI (Net)**")
                roi_chart = alt.Chart(comp_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                    x=alt.X("Model:N", title=None, axis=alt.Axis(labelAngle=-20)),
                    y=alt.Y("ROI (Net):Q", title="ROI (x)"),
                    color=alt.Color("Model:N", scale=model_color_scale, legend=None),
                    tooltip=["Model:N", alt.Tooltip("ROI (Net):Q", format=".2f")],
                )
                st.altair_chart(roi_chart.properties(height=300), use_container_width=True)

            with chart_col2:
                st.markdown("**Net Revenue**")
                rev_chart = alt.Chart(comp_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                    x=alt.X("Model:N", title=None, axis=alt.Axis(labelAngle=-20)),
                    y=alt.Y("Net Revenue:Q", title="USD", axis=alt.Axis(format="$,.0f")),
                    color=alt.Color("Model:N", scale=model_color_scale, legend=None),
                    tooltip=["Model:N", alt.Tooltip("Net Revenue:Q", format="$,.0f")],
                )
                st.altair_chart(rev_chart.properties(height=300), use_container_width=True)

            chart_col3, chart_col4 = st.columns(2)

            with chart_col3:
                st.markdown("**Treated Patients**")
                pat_chart = alt.Chart(comp_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                    x=alt.X("Model:N", title=None, axis=alt.Axis(labelAngle=-20)),
                    y=alt.Y("Treated Patients:Q", title="Patients", axis=alt.Axis(format=",.0f")),
                    color=alt.Color("Model:N", scale=model_color_scale, legend=None),
                    tooltip=["Model:N", alt.Tooltip("Treated Patients:Q", format=",.0f")],
                )
                st.altair_chart(pat_chart.properties(height=300), use_container_width=True)

            with chart_col4:
                st.markdown("**Funnel CAC Total**")
                cac_chart = alt.Chart(comp_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                    x=alt.X("Model:N", title=None, axis=alt.Axis(labelAngle=-20)),
                    y=alt.Y("Funnel CAC:Q", title="USD", axis=alt.Axis(format="$,.0f")),
                    color=alt.Color("Model:N", scale=model_color_scale, legend=None),
                    tooltip=["Model:N", alt.Tooltip("Funnel CAC:Q", format="$,.0f")],
                )
                st.altair_chart(cac_chart.properties(height=300), use_container_width=True)

            # Stage-level patient comparison
            st.markdown("### Funnel Stage Comparison (Patients)")
            stage_rows = []
            for midx, (mstate, mname) in enumerate(zip(st.session_state["models"], st.session_state["model_names"])):
                fr, _ = run_model(mstate)
                for r in fr:
                    stage_rows.append({"Model": mname, "Stage": r.name[:40] + ("…" if len(r.name) > 40 else ""), "Patients": r.patients})

            stage_df = pd.DataFrame(stage_rows)
            stage_chart = alt.Chart(stage_df).mark_line(point=True).encode(
                x=alt.X("Stage:N", sort=None, title=None, axis=alt.Axis(labelAngle=-35, labelLimit=200)),
                y=alt.Y("Patients:Q", title="Patients", axis=alt.Axis(format=",.0f")),
                color=alt.Color("Model:N", scale=model_color_scale),
                tooltip=["Model:N", "Stage:N", alt.Tooltip("Patients:Q", format=",.0f")],
            ).properties(height=350)
            st.altair_chart(stage_chart, use_container_width=True)

            # Download comparison
            st.markdown("### Export Comparison")
            comp_csv = comp_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Download Comparison CSV",
                data=comp_csv,
                file_name="pharmaroi_comparison.csv",
                mime="text/csv",
            )

st.divider()
st.subheader("How to interpret")
st.write("""
- Each **model tab** is fully independent — tweak funnel stages, ratios, CAC, ARPP, and discount separately.
- Use **Add New Model** or **Duplicate Current** to create variants (e.g. optimistic vs. conservative).
- The **📊 Comparison** tab shows all models side-by-side with charts and a downloadable table.
- **ROI (Net)** = Net Revenue / Total Funnel CAC
- **Net Revenue** = Gross Revenue × (1 − Discount)
""")