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
    "platform_costs": {
        "dario_connect_config": 500_000.0,
        "dario_care_config": 500_000.0,
        "sub_dario_connect": 1_000_000.0,
        "sub_dario_care": 250_000.0,
        "maintenance_support": 250_000.0,
    },
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
    "platform_costs": {
        "dario_connect_config": 0.0,
        "dario_care_config": 0.0,
        "sub_dario_connect": 0.0,
        "sub_dario_care": 0.0,
        "maintenance_support": 0.0,
    },
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
    total_cac_pool = 0.0

    for idx, s in enumerate(stages):
        if idx == 0:
            patients = prev_patients
            ratio_used = 1.0
        else:
            ratio_used = 1.0 if not s.active else clamp(s.ratio, 0.0, 1.0)
            patients = prev_patients * ratio_used

        if idx < 5:
            cac_pp = 0.0
            stage_cac = 0.0
            cumulative = 0.0
        elif idx == 5:
            cac_pp = 0.0 if not s.active else max(0.0, float(s.cac))
            stage_cac = patients * cac_pp
            total_cac_pool = stage_cac
            cumulative = total_cac_pool
        else:
            cumulative = total_cac_pool
            cac_pp = (total_cac_pool / patients) if patients > 0 else 0.0
            stage_cac = cac_pp * patients

        results.append(StageResult(
            name=s.name, active=s.active, ratio_used=ratio_used,
            patients=patients, cac_per_patient=cac_pp,
            stage_cac=stage_cac, cumulative_cac=cumulative,
        ))
        prev_patients = patients

    return results


def compute_financials(treated_patients, arpp, treatment_years, discount, funnel_cac_total, platform_costs=0.0):
    treated = max(0.0, float(treated_patients))
    arpp = max(0.0, float(arpp))
    years = max(0.0, float(treatment_years))
    disc = clamp(discount, 0.0, 1.0)
    funnel_cac = max(0.0, float(funnel_cac_total))
    platform = max(0.0, float(platform_costs))

    gross = treated * arpp * years
    net = gross * (1.0 - disc)
    net_profit = net - funnel_cac - platform
    roi = (net / (funnel_cac + platform)) if (funnel_cac + platform) > 0 else float("nan")

    return {
        "treated_patients": treated,
        "gross_revenue": gross,
        "net_revenue": net,
        "discount": disc,
        "funnel_cac_total": funnel_cac,
        "platform_costs_total": platform,
        "net_profit": net_profit,
        "roi_net": roi,
    }


def run_model(state: dict):
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
    platform_costs = sum(state.get("platform_costs", {}).values())
    fin = compute_financials(
        treated_patients=funnel_results[-1].patients,
        arpp=float(state["arpp"]),
        treatment_years=float(state["treatment_years"]),
        discount=float(state["discount"]),
        funnel_cac_total=funnel_results[-1].cumulative_cac,
        platform_costs=platform_costs,
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
    
    # Initialize confirmation state
    if "confirm_delete" not in st.session_state:
        st.session_state["confirm_delete"] = False
    
    if not st.session_state["confirm_delete"]:
        if st.button("Delete Current", use_container_width=True, disabled=not can_delete):
            st.session_state["confirm_delete"] = True
            st.rerun()
    else:
        idx = st.session_state["active_model_idx"]
        st.warning(f"Delete '{st.session_state['model_names'][idx]}'?")
        confirm_cols = st.columns(2)
        with confirm_cols[0]:
            if st.button("Yes, Delete", use_container_width=True, type="primary"):
                st.session_state["models"].pop(idx)
                st.session_state["model_names"].pop(idx)
                st.session_state["active_model_idx"] = max(0, idx - 1)
                st.session_state["confirm_delete"] = False
                st.rerun()
        with confirm_cols[1]:
            if st.button("Cancel", use_container_width=True):
                st.session_state["confirm_delete"] = False
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

# =============================================================================
# MODEL TABS
# =============================================================================
for model_idx, model_tab in enumerate(tabs[:-1]):
    with model_tab:
        model = st.session_state["models"][model_idx]
        model_name = st.session_state["model_names"][model_idx]
        tab_color = TAB_PALETTE[model_idx % len(TAB_PALETTE)]

        # Update active model index when this tab is viewed
        st.session_state["active_model_idx"] = model_idx

        # =====================================================================
        # SHARED SETTINGS
        # =====================================================================
        with st.expander("Shared Model Settings", expanded=False):
            st.markdown("**Base Population**")
            model["shared"]["use_shared_base_population"] = st.checkbox(
                "Use same base population for both scenarios",
                value=model["shared"]["use_shared_base_population"],
                key=f"shared_pop_toggle_{model_idx}",
            )

            if model["shared"]["use_shared_base_population"]:
                model["shared"]["shared_base_population"] = st.number_input(
                    "Shared Base Population (TAM)",
                    min_value=0,
                    step=100_000,
                    value=int(model["shared"]["shared_base_population"]),
                    key=f"shared_pop_{model_idx}",
                )

            st.markdown("**Stage Names**")
            with st.expander("Customize Stage Names"):
                for sidx in range(NUM_STAGES):
                    model["shared"]["stage_names"][sidx] = st.text_input(
                        f"Stage {sidx+1}:",
                        value=model["shared"]["stage_names"][sidx],
                        key=f"stage_name_{model_idx}_{sidx}",
                    )

            # Reset buttons
            st.markdown("---")
            reset_col1, reset_col2 = st.columns(2)
            with reset_col1:
                if st.button("Reset to Defaults", key=f"reset_default_{model_idx}"):
                    st.session_state["models"][model_idx] = get_default_model()
                    st.rerun()
            with reset_col2:
                if st.button("Reset to Zero", key=f"reset_zero_{model_idx}"):
                    st.session_state["models"][model_idx] = get_zero_model()
                    st.rerun()

        # =====================================================================
        # BASELINE SCENARIO
        # =====================================================================
        st.markdown("---")
        st.subheader("Baseline Scenario (Without Dario)")
        st.caption("Configure the current state / status quo assumptions")

        baseline = model["baseline"]

        with st.expander("Baseline Settings", expanded=True):
            # Base population (if not shared)
            if not model["shared"]["use_shared_base_population"]:
                baseline["base_population"] = st.number_input(
                    "Baseline Base Population",
                    min_value=0,
                    step=100_000,
                    value=int(baseline["base_population"]),
                    key=f"baseline_pop_{model_idx}",
                )

            # Revenue settings
            st.markdown("**Revenue Assumptions**")
            b_col1, b_col2, b_col3 = st.columns(3)
            with b_col1:
                baseline["arpp"] = st.number_input(
                    "ARPP ($/year)",
                    min_value=0.0,
                    step=1000.0,
                    value=float(baseline["arpp"]),
                    key=f"baseline_arpp_{model_idx}",
                )
            with b_col2:
                baseline["treatment_years"] = st.slider(
                    "Treatment Years",
                    min_value=0.1,
                    max_value=5.0,
                    step=0.1,
                    value=float(baseline["treatment_years"]),
                    key=f"baseline_years_{model_idx}",
                )
            with b_col3:
                baseline["discount"] = st.slider(
                    "Discount (Gross→Net)",
                    min_value=0.0,
                    max_value=1.0,
                    step=0.01,
                    value=float(baseline["discount"]),
                    key=f"baseline_discount_{model_idx}",
                )

            # CAC Mode
            st.markdown("**CAC Configuration**")
            baseline["cac_mode"] = st.radio(
                "Baseline CAC Input Mode:",
                options=["direct", "sensitivity"],
                format_func=lambda x: "Direct Input" if x == "direct" else "Sensitivity Analysis",
                index=0 if baseline["cac_mode"] == "direct" else 1,
                key=f"baseline_cac_mode_{model_idx}",
                horizontal=True,
            )

            if baseline["cac_mode"] == "sensitivity":
                # Sensitivity range
                st.markdown("**Sensitivity Range (Stage 6 CAC)**")
                sens_col1, sens_col2, sens_col3, sens_col4 = st.columns(4)
                with sens_col1:
                    baseline["cac_sensitivity"]["min"] = st.number_input(
                        "Min CAC",
                        min_value=0.0,
                        step=1.0,
                        value=float(baseline["cac_sensitivity"]["min"]),
                        key=f"baseline_sens_min_{model_idx}",
                    )
                with sens_col2:
                    baseline["cac_sensitivity"]["max"] = st.number_input(
                        "Max CAC",
                        min_value=0.0,
                        step=1.0,
                        value=float(baseline["cac_sensitivity"]["max"]),
                        key=f"baseline_sens_max_{model_idx}",
                    )
                with sens_col3:
                    baseline["cac_sensitivity"]["step"] = st.number_input(
                        "Step",
                        min_value=0.1,
                        step=0.5,
                        value=float(baseline["cac_sensitivity"]["step"]),
                        key=f"baseline_sens_step_{model_idx}",
                    )
                with sens_col4:
                    baseline["cac_sensitivity"]["base"] = st.number_input(
                        "Base Case",
                        min_value=0.0,
                        step=1.0,
                        value=float(baseline["cac_sensitivity"]["base"]),
                        key=f"baseline_sens_base_{model_idx}",
                    )
                # Use base case for direct calculations
                baseline["cac"][5] = baseline["cac_sensitivity"]["base"]

            # Funnel Stages - Individual expanders like V3
            st.markdown("**Funnel Stages**")
            stage_names = model["shared"]["stage_names"]

            for sidx, sname in enumerate(stage_names):
                with st.expander(f"{sidx+1}. {sname}", expanded=False):
                    baseline["stage_active"][sidx] = st.checkbox(
                        "Use this stage",
                        value=bool(baseline["stage_active"][sidx]),
                        key=f"baseline_active_{model_idx}_{sidx}",
                    )
                    
                    if sidx == 0:
                        st.info("Stage 1 is the base population. No ratio applied.")
                    else:
                        disabled = not baseline["stage_active"][sidx]
                        baseline["ratios"][sidx] = st.slider(
                            "Funnel ratio",
                            min_value=0.0,
                            max_value=1.0,
                            step=0.01,
                            value=float(baseline["ratios"][sidx]),
                            disabled=disabled,
                            key=f"baseline_ratio_{model_idx}_{sidx}",
                        )
                    
                    # CAC input for stages 1-6 (stages 7+ auto-calculate)
                    if sidx <= 5:
                        disabled = not baseline["stage_active"][sidx]
                        # Skip if in sensitivity mode and this is stage 6
                        if baseline["cac_mode"] == "sensitivity" and sidx == 5:
                            st.caption(f"Stage 6 CAC controlled by sensitivity analysis (Base: ${baseline['cac_sensitivity']['base']:,.0f})")
                        else:
                            baseline["cac"][sidx] = st.number_input(
                                "CAC ($ per patient)",
                                min_value=0.0,
                                step=1.0,
                                value=float(baseline["cac"][sidx]),
                                disabled=disabled,
                                key=f"baseline_cac_{model_idx}_{sidx}",
                            )
                    else:
                        st.caption("CAC auto-calculated from Stage 6")

            # Baseline Platform Costs (typically 0 for baseline)
            st.markdown("**Platform Costs (Baseline)**")
            if "platform_costs" not in baseline:
                baseline["platform_costs"] = {
                    "dario_connect_config": 0.0,
                    "dario_care_config": 0.0,
                    "sub_dario_connect": 0.0,
                    "sub_dario_care": 0.0,
                    "maintenance_support": 0.0,
                }
            pc_base = baseline["platform_costs"]
            pc_base_col1, pc_base_col2 = st.columns(2)
            with pc_base_col1:
                pc_base["dario_connect_config"] = st.number_input(
                    "Platform Config Cost 1",
                    min_value=0.0,
                    step=10000.0,
                    value=float(pc_base["dario_connect_config"]),
                    key=f"baseline_pc1_{model_idx}",
                )
                pc_base["dario_care_config"] = st.number_input(
                    "Platform Config Cost 2",
                    min_value=0.0,
                    step=10000.0,
                    value=float(pc_base["dario_care_config"]),
                    key=f"baseline_pc2_{model_idx}",
                )
                pc_base["sub_dario_connect"] = st.number_input(
                    "Subscription Cost 1",
                    min_value=0.0,
                    step=10000.0,
                    value=float(pc_base["sub_dario_connect"]),
                    key=f"baseline_pc3_{model_idx}",
                )
            with pc_base_col2:
                pc_base["sub_dario_care"] = st.number_input(
                    "Subscription Cost 2",
                    min_value=0.0,
                    step=10000.0,
                    value=float(pc_base["sub_dario_care"]),
                    key=f"baseline_pc4_{model_idx}",
                )
                pc_base["maintenance_support"] = st.number_input(
                    "Maintenance & Support",
                    min_value=0.0,
                    step=10000.0,
                    value=float(pc_base["maintenance_support"]),
                    key=f"baseline_pc5_{model_idx}",
                )
            st.caption(f"**Total Baseline Platform Costs:** {money(sum(pc_base.values()))}")

        # =====================================================================
        # DARIO SCENARIO
        # =====================================================================
        st.markdown("---")
        st.subheader("Dario-Enabled Scenario")
        st.caption("Configure the Dario-enabled assumptions (expected improvements)")

        dario = model["dario"]

        with st.expander("Dario Settings", expanded=True):
            # Base population (if not shared)
            if not model["shared"]["use_shared_base_population"]:
                dario["base_population"] = st.number_input(
                    "Dario Base Population",
                    min_value=0,
                    step=100_000,
                    value=int(dario["base_population"]),
                    key=f"dario_pop_{model_idx}",
                )

            # Revenue settings
            st.markdown("**Revenue Assumptions**")
            d_col1, d_col2, d_col3 = st.columns(3)
            with d_col1:
                dario["arpp"] = st.number_input(
                    "ARPP ($/year)",
                    min_value=0.0,
                    step=1000.0,
                    value=float(dario["arpp"]),
                    key=f"dario_arpp_{model_idx}",
                )
            with d_col2:
                dario["treatment_years"] = st.slider(
                    "Treatment Years",
                    min_value=0.1,
                    max_value=5.0,
                    step=0.1,
                    value=float(dario["treatment_years"]),
                    key=f"dario_years_{model_idx}",
                )
            with d_col3:
                dario["discount"] = st.slider(
                    "Discount (Gross→Net)",
                    min_value=0.0,
                    max_value=1.0,
                    step=0.01,
                    value=float(dario["discount"]),
                    key=f"dario_discount_{model_idx}",
                )

            # Funnel Stages - Individual expanders like V3
            st.markdown("**Funnel Stages**")

            for sidx, sname in enumerate(stage_names):
                with st.expander(f"{sidx+1}. {sname}", expanded=False):
                    dario["stage_active"][sidx] = st.checkbox(
                        "Use this stage",
                        value=bool(dario["stage_active"][sidx]),
                        key=f"dario_active_{model_idx}_{sidx}",
                    )
                    
                    if sidx == 0:
                        st.info("Stage 1 is the base population. No ratio applied.")
                    else:
                        disabled = not dario["stage_active"][sidx]
                        dario["ratios"][sidx] = st.slider(
                            "Funnel ratio",
                            min_value=0.0,
                            max_value=1.0,
                            step=0.01,
                            value=float(dario["ratios"][sidx]),
                            disabled=disabled,
                            key=f"dario_ratio_{model_idx}_{sidx}",
                        )
                    
                    # CAC input for stages 1-6 (stages 7+ auto-calculate)
                    if sidx <= 5:
                        disabled = not dario["stage_active"][sidx]
                        dario["cac"][sidx] = st.number_input(
                            "CAC ($ per patient)",
                            min_value=0.0,
                            step=1.0,
                            value=float(dario["cac"][sidx]),
                            disabled=disabled,
                            key=f"dario_cac_{model_idx}_{sidx}",
                        )
                    else:
                        st.caption("CAC auto-calculated from Stage 6")

            # Platform costs
            st.markdown("**Platform Costs (Dario)**")
            pc = dario["platform_costs"]
            pc_col1, pc_col2 = st.columns(2)
            with pc_col1:
                pc["dario_connect_config"] = st.number_input(
                    "Dario Connect Configuration",
                    min_value=0.0,
                    step=10000.0,
                    value=float(pc["dario_connect_config"]),
                    key=f"dario_pc1_{model_idx}",
                )
                pc["dario_care_config"] = st.number_input(
                    "Dario Care Configuration",
                    min_value=0.0,
                    step=10000.0,
                    value=float(pc["dario_care_config"]),
                    key=f"dario_pc2_{model_idx}",
                )
                pc["sub_dario_connect"] = st.number_input(
                    "Subscription — Dario Connect",
                    min_value=0.0,
                    step=10000.0,
                    value=float(pc["sub_dario_connect"]),
                    key=f"dario_pc3_{model_idx}",
                )
            with pc_col2:
                pc["sub_dario_care"] = st.number_input(
                    "Subscription — Dario Care",
                    min_value=0.0,
                    step=10000.0,
                    value=float(pc["sub_dario_care"]),
                    key=f"dario_pc4_{model_idx}",
                )
                pc["maintenance_support"] = st.number_input(
                    "Maintenance & Support",
                    min_value=0.0,
                    step=10000.0,
                    value=float(pc["maintenance_support"]),
                    key=f"dario_pc5_{model_idx}",
                )
            st.caption(f"**Total Dario Platform Costs:** {money(sum(pc.values()))}")

        # =====================================================================
        # RUN CALCULATIONS
        # =====================================================================
        results = run_full_model(model)
        baseline_fin = results["baseline_fin"]
        dario_fin = results["dario_fin"]
        incr = results["incremental"]
        breakeven = results["breakeven"]

        # =====================================================================
        # KPI SUMMARY CARDS
        # =====================================================================
        st.markdown("---")
        st.subheader("Results Summary")

        # Row 1: Treated Patients
        st.markdown("**Treated Patients**")
        kpi_col1, kpi_col2, kpi_col3 = st.columns(3)
        with kpi_col1:
            st.metric("Baseline", number(baseline_fin["treated_patients"]))
        with kpi_col2:
            st.metric("Dario", number(dario_fin["treated_patients"]))
        with kpi_col3:
            st.metric(
                "Incremental",
                number(incr["incremental_patients"]),
                delta=f"{incr['incremental_patients']:+,.0f}" if incr["incremental_patients"] != 0 else None,
            )

        # Row 2: Net Revenue
        st.markdown("**Net Revenue**")
        kpi_col4, kpi_col5, kpi_col6 = st.columns(3)
        with kpi_col4:
            st.metric("Baseline", money(baseline_fin["net_revenue"]))
        with kpi_col5:
            st.metric("Dario", money(dario_fin["net_revenue"]))
        with kpi_col6:
            st.metric(
                "Incremental",
                money(incr["incremental_net_revenue"]),
                delta=delta_fmt(incr["incremental_net_revenue"], "money") if incr["incremental_net_revenue"] != 0 else None,
            )

        # Row 3: Total Cost
        st.markdown("**Total Cost**")
        kpi_col7, kpi_col8, kpi_col9 = st.columns(3)
        with kpi_col7:
            st.metric("Baseline", money(baseline_fin["total_cost"]))
        with kpi_col8:
            st.metric("Dario", money(dario_fin["total_cost"]))
        with kpi_col9:
            st.metric(
                "Incremental",
                money(incr["incremental_cost"]),
                delta=delta_fmt(incr["incremental_cost"], "money") if incr["incremental_cost"] != 0 else None,
            )

        # Row 4: Net Profit & ROI
        st.markdown("**Profitability**")
        kpi_col10, kpi_col11, kpi_col12, kpi_col13 = st.columns(4)
        with kpi_col10:
            st.metric("Baseline Net Profit", money(baseline_fin["net_profit"]))
        with kpi_col11:
            st.metric("Dario Net Profit", money(dario_fin["net_profit"]))
        with kpi_col12:
            st.metric("Incremental Profit", money(incr["incremental_profit"]))
        with kpi_col13:
            st.metric("Incremental ROI", roix(incr["incremental_roi_profit"]))

        # Row 5: Break-even
        st.markdown("**Break-even Analysis**")
        be_col1, be_col2, be_col3 = st.columns(3)
        with be_col1:
            st.metric("Break-even Patients Needed", number(breakeven["breakeven_incremental_patients"]))
        with be_col2:
            st.metric("Actual Incremental Patients", number(incr["incremental_patients"]))
        with be_col3:
            if breakeven["is_above_breakeven"]:
                st.success(f"Above break-even by {number(breakeven['patients_vs_breakeven'])} patients")
            else:
                st.warning(f"Below break-even by {number(abs(breakeven['patients_vs_breakeven']))} patients")

        # =====================================================================
        # FUNNEL TABLES
        # =====================================================================
        st.markdown("---")
        st.subheader("Funnel Comparison")

        if pd is not None:
            funnel_tab1, funnel_tab2 = st.tabs(["Baseline Funnel", "Dario Funnel"])

            with funnel_tab1:
                baseline_rows = []
                for ridx, r in enumerate(results["baseline_funnel"]):
                    baseline_rows.append({
                        "#": ridx + 1,
                        "Stage": r.name,
                        "Status": "Active" if r.active else "Inactive (pass-through)",
                        "Ratio": pct(r.ratio_used) if ridx > 0 else "—",
                        "Patients": number(r.patients),
                        "CAC/pt": money(r.cac_per_patient),
                        "Stage CAC": money(r.stage_cac),
                        "Cumulative CAC": money(r.cumulative_cac),
                    })
                st.dataframe(pd.DataFrame(baseline_rows), use_container_width=True, hide_index=True)

            with funnel_tab2:
                dario_rows = []
                for ridx, r in enumerate(results["dario_funnel"]):
                    dario_rows.append({
                        "#": ridx + 1,
                        "Stage": r.name,
                        "Status": "Active" if r.active else "Inactive (pass-through)",
                        "Ratio": pct(r.ratio_used) if ridx > 0 else "—",
                        "Patients": number(r.patients),
                        "CAC/pt": money(r.cac_per_patient),
                        "Stage CAC": money(r.stage_cac),
                        "Cumulative CAC": money(r.cumulative_cac),
                    })
                st.dataframe(pd.DataFrame(dario_rows), use_container_width=True, hide_index=True)

        # =====================================================================
        # CHARTS
        # =====================================================================
        st.markdown("---")
        st.subheader("Visual Comparisons")

        if pd is not None:
            # Side-by-side bar chart
            st.markdown("**Baseline vs Dario: Key Metrics**")
            comparison_data = pd.DataFrame([
                {"Metric": "Treated Patients", "Scenario": "Baseline", "Value": baseline_fin["treated_patients"]},
                {"Metric": "Treated Patients", "Scenario": "Dario", "Value": dario_fin["treated_patients"]},
                {"Metric": "Net Revenue", "Scenario": "Baseline", "Value": baseline_fin["net_revenue"]},
                {"Metric": "Net Revenue", "Scenario": "Dario", "Value": dario_fin["net_revenue"]},
                {"Metric": "Total Cost", "Scenario": "Baseline", "Value": baseline_fin["total_cost"]},
                {"Metric": "Total Cost", "Scenario": "Dario", "Value": dario_fin["total_cost"]},
                {"Metric": "Net Profit", "Scenario": "Baseline", "Value": baseline_fin["net_profit"]},
                {"Metric": "Net Profit", "Scenario": "Dario", "Value": dario_fin["net_profit"]},
            ])

            scenario_colors = alt.Scale(
                domain=["Baseline", "Dario"],
                range=[COLORS["baseline"], COLORS["dario"]]
            )

            bar_chart = alt.Chart(comparison_data).mark_bar().encode(
                x=alt.X("Scenario:N", title=None),
                y=alt.Y("Value:Q", title="Value"),
                color=alt.Color("Scenario:N", scale=scenario_colors, legend=None),
                column=alt.Column("Metric:N", title=None),
                tooltip=["Scenario", alt.Tooltip("Value:Q", format=",.0f")],
            ).properties(width=150, height=300)

            st.altair_chart(bar_chart)

            # Stage-by-stage patient comparison
            st.markdown("**Funnel Stage Comparison: Patients by Stage**")
            stage_comparison = []
            for ridx, (b_res, d_res) in enumerate(zip(results["baseline_funnel"], results["dario_funnel"])):
                stage_comparison.append({
                    "Stage": f"{ridx+1}. {b_res.name[:30]}",
                    "Scenario": "Baseline",
                    "Patients": b_res.patients,
                })
                stage_comparison.append({
                    "Stage": f"{ridx+1}. {d_res.name[:30]}",
                    "Scenario": "Dario",
                    "Patients": d_res.patients,
                })

            stage_df = pd.DataFrame(stage_comparison)
            stage_chart = alt.Chart(stage_df).mark_line(point=True).encode(
                x=alt.X("Stage:N", sort=None, title=None, axis=alt.Axis(labelAngle=-45, labelLimit=200)),
                y=alt.Y("Patients:Q", title="Patients", axis=alt.Axis(format=",.0f")),
                color=alt.Color("Scenario:N", scale=scenario_colors),
                tooltip=["Stage", "Scenario", alt.Tooltip("Patients:Q", format=",.0f")],
            ).properties(height=400)

            st.altair_chart(stage_chart, use_container_width=True)

            # Sensitivity chart (if available)
            if results["sensitivity"]:
                st.markdown("**Sensitivity Analysis: Incremental ROI vs Baseline CAC**")
                sens_df = pd.DataFrame(results["sensitivity"])

                sens_chart = alt.Chart(sens_df).mark_line(point=True, color=COLORS["incremental"]).encode(
                    x=alt.X("baseline_cac:Q", title="Baseline CAC ($/patient)"),
                    y=alt.Y("incremental_roi_profit:Q", title="Incremental ROI (Profit)"),
                    tooltip=[
                        alt.Tooltip("baseline_cac:Q", title="Baseline CAC", format="$.0f"),
                        alt.Tooltip("incremental_roi_profit:Q", title="Incr ROI", format=".2f"),
                        alt.Tooltip("incremental_profit:Q", title="Incr Profit", format="$,.0f"),
                    ],
                ).properties(height=350)

                # Add break-even line at ROI = 1.0
                rule = alt.Chart(pd.DataFrame({"y": [1.0]})).mark_rule(
                    strokeDash=[5, 5],
                    color=COLORS["warning"]
                ).encode(y="y:Q")

                st.altair_chart(sens_chart + rule, use_container_width=True)

                # Sensitivity table
                with st.expander("Sensitivity Data Table"):
                    sens_display = sens_df.copy()
                    sens_display["baseline_cac"] = sens_display["baseline_cac"].map(lambda x: f"${x:,.0f}")
                    sens_display["incremental_cost"] = sens_display["incremental_cost"].map(lambda x: f"${x:,.0f}")
                    sens_display["incremental_profit"] = sens_display["incremental_profit"].map(lambda x: f"${x:,.0f}")
                    sens_display["incremental_roi_profit"] = sens_display["incremental_roi_profit"].map(lambda x: f"{x:.2f}x")
                    st.dataframe(sens_display[["baseline_cac", "incremental_cost", "incremental_profit", "incremental_roi_profit"]], use_container_width=True, hide_index=True)

        # =====================================================================
        # EXPORT
        # =====================================================================
        st.markdown("---")
        st.subheader("Export")

        export_col1, export_col2 = st.columns(2)
        with export_col1:
            xlsx_bytes = build_excel_report(model_name, results, model)
            st.download_button(
                "Download Excel Report",
                data=xlsx_bytes,
                file_name=f"{model_name.replace(' ', '_')}_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dl_xlsx_{model_idx}",
            )

        with export_col2:
            # Export model config as JSON
            model_export = {
                "name": model_name,
                "model": model,
            }
            json_str = json.dumps(model_export, indent=2)
            st.download_button(
                "Export Model Config (JSON)",
                data=json_str,
                file_name=f"{model_name.replace(' ', '_')}_config.json",
                mime="application/json",
                key=f"dl_json_{model_idx}",
            )

        # ----- Compute -----
        funnel_results, fin = run_model(state)

        # ----- KPI strip -----
        st.markdown(f"<div style='border-left: 4px solid {tab_color}; padding-left: 12px; margin-bottom: 8px;'><strong style='font-size:1.1rem'>{model_name}</strong></div>", unsafe_allow_html=True)

        roi = fin["roi_net"]
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("ROI (Net)", roix(roi) if roi == roi else "—")
        k2.metric("Treated Patients", number(fin["treated_patients"]))
        k3.metric("Net Revenue", money(fin["net_revenue"]))
        k4.metric("Funnel CAC", money(fin["funnel_cac_total"]))
        k5.metric("Total CAC", money(fin["funnel_cac_total"] + fin["platform_costs_total"]))
        k6.metric("Net Profit", money(fin["net_revenue"] - fin["funnel_cac_total"] - fin["platform_costs_total"]))


        st.markdown(
            f"Gross: **\\${fin['gross_revenue']:,.0f}**  |  "
            f"Discount: **{fin['discount']*100:.1f}%**  |  "
            f"Discount Amount: **\\${fin['gross_revenue'] - fin['net_revenue']:,.0f}**  |  " 
            f"Net Revenue per Rx: **\\${(float(state['arpp']) * (1 - fin['discount'])):,.0f}**"           
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
        # Model selection filter
        st.markdown("**Select models to compare:**")
        selected_model_names = st.multiselect(
            "Choose models",
            options=st.session_state["model_names"],
            default=st.session_state["model_names"],
            key="comparison_model_select",
            label_visibility="collapsed",
        )
        
        if len(selected_model_names) < 2:
            st.warning("Please select at least 2 models to compare.")
            st.stop()
        
        # Filter to selected models only
        selected_indices = [i for i, name in enumerate(st.session_state["model_names"]) if name in selected_model_names]
        selected_models = [st.session_state["models"][i] for i in selected_indices]
        selected_names = [st.session_state["model_names"][i] for i in selected_indices]
        
        # Build comparison data
        comparison_rows = []
        for midx, (mstate, mname) in enumerate(zip(selected_models, selected_names)):

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
                domain=selected_names,
                range=TAB_PALETTE[:len(selected_names)],
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
            for midx, (mstate, mname) in enumerate(zip(selected_models, selected_names)):

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

                        # Diff View between two models
            st.markdown("### Model Diff View")
            if len(selected_names) >= 2:
                diff_col1, diff_col2 = st.columns(2)
                with diff_col1:
                    diff_model_a = st.selectbox(
                        "Model A:",
                        options=selected_names,
                        index=0,
                        key="diff_model_a",
                    )
                with diff_col2:
                    remaining = [n for n in selected_names if n != diff_model_a]
                    diff_model_b = st.selectbox(
                        "Model B:",
                        options=remaining,
                        index=0,
                        key="diff_model_b",
                    )
                
                idx_a = st.session_state["model_names"].index(diff_model_a)
                idx_b = st.session_state["model_names"].index(diff_model_b)
                state_a = st.session_state["models"][idx_a]
                state_b = st.session_state["models"][idx_b]
                
                diff_rows = []
                
                # Compare top-level params
                top_params = [
                    ("Base Population", "base_population", "{:,.0f}"),
                    ("ARPP", "arpp", "${:,.0f}"),
                    ("Treatment Years", "treatment_years", "{:.1f}"),
                    ("Discount", "discount", "{:.1%}"),
                ]
                for label, key, fmt in top_params:
                    val_a = state_a.get(key, 0)
                    val_b = state_b.get(key, 0)
                    if val_a != val_b:
                        diff_rows.append({
                            "Parameter": label,
                            f"{diff_model_a}": fmt.format(val_a),
                            f"{diff_model_b}": fmt.format(val_b),
                            "Difference": fmt.format(val_b - val_a) if "%" not in fmt else f"{(val_b - val_a)*100:+.1f}pp",
                        })
                
                # Compare stage ratios and CAC
                stage_names_a = state_a.get("stage_names", STAGE_NAMES)
                for sidx in range(len(STAGE_NAMES)):
                    stage_label = stage_names_a[sidx][:30] + ("..." if len(stage_names_a[sidx]) > 30 else "")
                    
                    ratio_a = state_a["ratios"][sidx]
                    ratio_b = state_b["ratios"][sidx]
                    if ratio_a != ratio_b and sidx > 0:
                        diff_rows.append({
                            "Parameter": f"Stage {sidx+1} Ratio",
                            f"{diff_model_a}": f"{ratio_a:.1%}",
                            f"{diff_model_b}": f"{ratio_b:.1%}",
                            "Difference": f"{(ratio_b - ratio_a)*100:+.1f}pp",
                        })
                    
                    cac_a = state_a["cac"][sidx]
                    cac_b = state_b["cac"][sidx]
                    if cac_a != cac_b:
                        diff_rows.append({
                            "Parameter": f"Stage {sidx+1} CAC",
                            f"{diff_model_a}": f"${cac_a:,.0f}",
                            f"{diff_model_b}": f"${cac_b:,.0f}",
                            "Difference": f"${cac_b - cac_a:+,.0f}",
                        })
                
                if diff_rows:
                    diff_df = pd.DataFrame(diff_rows)
                    st.dataframe(diff_df, use_container_width=True, hide_index=True)
                else:
                    st.success("These two models have identical parameters!")
            else:
                st.info("Select at least 2 models above to see a diff view.")


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
- **ROI (Net)** = Net Revenue / Total Funnel CAC + Platform Costs
- **Net Profit** = Net Revenue − Total Funnel CAC − Platform Costs
- **Net Revenue** = Gross Revenue × (1 − Discount)
""")