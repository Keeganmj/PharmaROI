# app.py
# PharmaROI Intelligence — V4 (Baseline vs Dario Comparison)
# Stabilized and cleaned version
# Run: streamlit run app.py

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import List, Optional
import io
import json

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

import streamlit as st
import altair as alt

try:
    import pandas as pd
except Exception:
    pd = None


# =============================================================================
# COLOR PALETTE
# =============================================================================
COLORS = {
    "primary": "#0F6CBD",
    "revenue": "#0F6CBD",
    "costs": "#9CA3AF",
    "profit": "#10B981",
    "warning": "#F59E0B",
    "danger": "#EF4444",
    "muted": "#6B7280",
    "baseline": "#6B7280",
    "dario": "#0F6CBD",
    "incremental": "#10B981",
}

TAB_PALETTE = [
    "#0F6CBD", "#10B981", "#F59E0B", "#EF4444",
    "#8B5CF6", "#EC4899", "#06B6D4", "#84CC16",
]


# =============================================================================
# FUNNEL STAGE DEFINITIONS
# =============================================================================
STAGE_NAMES: List[str] = [
    "Total Addressable Market for MASH",
    "F2 and F3",
    "MASH patients diagnosed",
    "Madrigal access to MASH patients",
    "Frequent users of online and social media resources",
    "Activation within 90 days onto Dario Connect for MASH",
    "Schedule telemedicine appointment",
    "Keep telemedicine appointment",
    "Obtain prescription for biopsy",
    "Get biopsy lab test",
    "Get positive lab results",
    "Complete post lab result consultation",
    "Get prescription for Rezdiffra",
]

NUM_STAGES = len(STAGE_NAMES)

# Stage 6 (index 5) is where CAC is applied - this creates the "CAC pool"
CAC_POOL_STAGE_INDEX = 5


# =============================================================================
# DEFAULT SCENARIO CONFIGURATIONS
# =============================================================================
def get_default_scenario(scenario_type: str = "dario") -> dict:
    """
    Returns default values for a scenario (baseline or dario).
    
    CAC LOGIC:
    - Only Stage 6 CAC matters - it creates the total CAC pool
    - Stages 1-5 have no CAC
    - Stages 7-13 inherit CAC from the pool (auto-calculated)
    """
    if scenario_type == "baseline":
        return {
            "base_population": 10_000_000,
            "ratios": [1.00, 0.30, 0.12, 0.18, 0.60, 0.25, 0.10, 0.65, 0.85, 0.60, 0.80, 0.35, 0.80],
            "stage_6_cac": 8.0,  # Only CAC input that matters
            "arpp": 47_400.0,
            "treatment_years": 1.0,
            "discount": 0.68,
            "stage_active": [True] * NUM_STAGES,
            "platform_costs": {
                "config_costs": 0.0,
                "subscription_costs": 0.0,
                "maintenance_costs": 0.0,
            },
            "cac_mode": "direct",
            "cac_sensitivity": {
                "min": 5.0,
                "max": 20.0,
                "step": 1.0,
                "base": 8.0,
            },
        }
    else:  # dario
        return {
            "base_population": 10_000_000,
            "ratios": [1.00, 0.35, 0.16, 0.22, 0.75, 0.40, 0.15, 0.80, 1.00, 0.75, 0.90, 0.50, 0.90],
            "stage_6_cac": 10.0,  # Only CAC input that matters
            "arpp": 47_400.0,
            "treatment_years": 1.0,
            "discount": 0.68,
            "stage_active": [True] * NUM_STAGES,
            "platform_costs": {
                "config_costs": 1_000_000.0,
                "subscription_costs": 1_250_000.0,
                "maintenance_costs": 250_000.0,
            },
            "cac_mode": "direct",
            "cac_sensitivity": {
                "min": 5.0,
                "max": 20.0,
                "step": 1.0,
                "base": 10.0,
            },
        }


def get_default_model() -> dict:
    """Returns the default structure for a model."""
    return {
        "shared": {
            "stage_names": STAGE_NAMES[:],
            "use_shared_base_population": True,
            "shared_base_population": 10_000_000,
        },
        "baseline": get_default_scenario("baseline"),
        "dario": get_default_scenario("dario"),
    }


def get_zero_model() -> dict:
    """Returns a zeroed-out model for fresh starts."""
    zero_scenario = {
        "base_population": 0,
        "ratios": [1.0] + [0.0] * (NUM_STAGES - 1),
        "stage_6_cac": 0.0,
        "arpp": 0.0,
        "treatment_years": 1.0,
        "discount": 0.0,
        "stage_active": [True] * NUM_STAGES,
        "platform_costs": {
            "config_costs": 0.0,
            "subscription_costs": 0.0,
            "maintenance_costs": 0.0,
        },
        "cac_mode": "direct",
        "cac_sensitivity": {"min": 0.0, "max": 10.0, "step": 1.0, "base": 0.0},
    }
    return {
        "shared": {
            "stage_names": STAGE_NAMES[:],
            "use_shared_base_population": True,
            "shared_base_population": 0,
        },
        "baseline": copy.deepcopy(zero_scenario),
        "dario": copy.deepcopy(zero_scenario),
    }


# =============================================================================
# MIGRATION HELPER — Upgrade old models to new structure
# =============================================================================
def migrate_model(old_model: dict) -> dict:
    """
    Ensures model is in the current format.
    Handles both old V3 format and old V4 format with cac[] arrays.
    """
    # Already in new format
    if "shared" in old_model and "baseline" in old_model and "dario" in old_model:
        # Check if using old cac[] array format
        if "cac" in old_model["baseline"] and "stage_6_cac" not in old_model["baseline"]:
            old_model["baseline"]["stage_6_cac"] = old_model["baseline"]["cac"][CAC_POOL_STAGE_INDEX]
            old_model["dario"]["stage_6_cac"] = old_model["dario"]["cac"][CAC_POOL_STAGE_INDEX]
        
        # Migrate old platform_costs format
        for scenario_key in ["baseline", "dario"]:
            scenario = old_model[scenario_key]
            if "platform_costs" in scenario:
                pc = scenario["platform_costs"]
                # Convert old format to new
                if "dario_connect_config" in pc:
                    new_pc = {
                        "config_costs": pc.get("dario_connect_config", 0) + pc.get("dario_care_config", 0),
                        "subscription_costs": pc.get("sub_dario_connect", 0) + pc.get("sub_dario_care", 0),
                        "maintenance_costs": pc.get("maintenance_support", 0),
                    }
                    scenario["platform_costs"] = new_pc
        
        return old_model
    
    # Old V3 single-scenario format - convert to baseline/dario
    new_model = get_default_model()
    
    new_model["shared"]["stage_names"] = old_model.get("stage_names", STAGE_NAMES[:])
    new_model["shared"]["shared_base_population"] = old_model.get("base_population", 10_000_000)
    
    # Old model becomes dario scenario
    new_model["dario"]["base_population"] = old_model.get("base_population", 10_000_000)
    new_model["dario"]["ratios"] = old_model.get("ratios", get_default_scenario("dario")["ratios"])
    new_model["dario"]["arpp"] = old_model.get("arpp", 47_400.0)
    new_model["dario"]["treatment_years"] = old_model.get("treatment_years", 1.0)
    new_model["dario"]["discount"] = old_model.get("discount", 0.68)
    new_model["dario"]["stage_active"] = old_model.get("stage_active", [True] * NUM_STAGES)
    
    # Extract Stage 6 CAC from old cac array
    if "cac" in old_model:
        new_model["dario"]["stage_6_cac"] = old_model["cac"][CAC_POOL_STAGE_INDEX]
    
    # Baseline gets lower ratios
    baseline_ratios = [r * 0.85 for r in new_model["dario"]["ratios"]]
    baseline_ratios[0] = 1.0
    new_model["baseline"]["ratios"] = baseline_ratios
    new_model["baseline"]["base_population"] = new_model["dario"]["base_population"]
    new_model["baseline"]["arpp"] = new_model["dario"]["arpp"]
    new_model["baseline"]["treatment_years"] = new_model["dario"]["treatment_years"]
    new_model["baseline"]["discount"] = new_model["dario"]["discount"]
    new_model["baseline"]["stage_6_cac"] = new_model["dario"]["stage_6_cac"] * 0.8
    
    return new_model


# =============================================================================
# FORMATTING HELPERS
# =============================================================================
def clamp(x, lo, hi):
    return max(lo, min(hi, float(x)))


def money(x) -> str:
    if x != x:  # NaN
        return "—"
    return f"${x:,.0f}"


def number(x) -> str:
    if x != x:
        return "—"
    return f"{x:,.0f}"


def pct(x) -> str:
    if x != x:
        return "—"
    return f"{x*100:,.1f}%"


def roix(x) -> str:
    if x != x:
        return "—"
    return f"{x:,.2f}x"


def delta_money(x) -> str:
    if x != x:
        return "—"
    sign = "+" if x >= 0 else ""
    return f"{sign}${x:,.0f}"


# =============================================================================
# CORE DATA STRUCTURES
# =============================================================================
@dataclass(frozen=True)
class StageResult:
    name: str
    active: bool
    ratio_used: float
    patients: float
    cac_per_patient: float
    stage_cac: float
    cumulative_cac: float


# =============================================================================
# CORE COMPUTATION FUNCTIONS
# =============================================================================
def compute_funnel(
    stage_names: List[str],
    ratios: List[float],
    stage_active: List[bool],
    stage_6_cac: float,
    base_population: float
) -> List[StageResult]:
    """
    Calculate funnel progression.
    
    CAC LOGIC:
    - Stages 1-5 (idx 0-4): No CAC applied
    - Stage 6 (idx 5): CAC per patient creates the total CAC pool
    - Stages 7-13 (idx 6-12): CAC per patient = pool / patients at that stage
    
    The cumulative CAC stays constant after Stage 6 - it's just redistributed
    across fewer patients as they progress through the funnel.
    """
    results = []
    prev_patients = max(0.0, float(base_population))
    cac_pool = 0.0

    for idx in range(NUM_STAGES):
        name = stage_names[idx]
        active = stage_active[idx]
        
        # Calculate patients
        if idx == 0:
            patients = prev_patients
            ratio_used = 1.0
        else:
            ratio_used = clamp(ratios[idx], 0.0, 1.0) if active else 1.0
            patients = prev_patients * ratio_used

        # Calculate CAC
        if idx < CAC_POOL_STAGE_INDEX:
            # Stages 1-5: No CAC
            cac_pp = 0.0
            stage_cac = 0.0
            cumulative = 0.0
        elif idx == CAC_POOL_STAGE_INDEX:
            # Stage 6: Creates the CAC pool
            cac_pp = max(0.0, float(stage_6_cac)) if active else 0.0
            stage_cac = patients * cac_pp
            cac_pool = stage_cac
            cumulative = cac_pool
        else:
            # Stages 7+: CAC distributed from pool
            cumulative = cac_pool
            cac_pp = (cac_pool / patients) if patients > 0 else 0.0
            stage_cac = cac_pool  # Total spend is the same, just per-patient changes

        results.append(StageResult(
            name=name,
            active=active,
            ratio_used=ratio_used,
            patients=patients,
            cac_per_patient=cac_pp,
            stage_cac=stage_cac,
            cumulative_cac=cumulative,
        ))
        prev_patients = patients

    return results


def compute_financials(
    treated_patients: float,
    arpp: float,
    treatment_years: float,
    discount: float,
    funnel_cac_total: float,
    platform_costs: float
) -> dict:
    """
    Calculate financial metrics.
    
    Formulas:
    - Gross Revenue = Treated Patients × ARPP × Treatment Years
    - Net Revenue = Gross Revenue × (1 - Discount)
    - Total Cost = Funnel CAC + Platform Costs
    - Net Profit = Net Revenue - Total Cost
    - Standalone ROI = Net Revenue / Total Cost (if cost > 0)
    """
    treated = max(0.0, float(treated_patients))
    arpp_val = max(0.0, float(arpp))
    years = max(0.0, float(treatment_years))
    disc = clamp(discount, 0.0, 1.0)
    funnel_cac = max(0.0, float(funnel_cac_total))
    platform = max(0.0, float(platform_costs))

    gross_revenue = treated * arpp_val * years
    net_revenue = gross_revenue * (1.0 - disc)
    total_cost = funnel_cac + platform
    net_profit = net_revenue - total_cost
    
    # Standalone ROI: Net Revenue / Total Cost
    standalone_roi = (net_revenue / total_cost) if total_cost > 0 else float("nan")
    
    # Cost per treated patient
    cost_per_patient = (total_cost / treated) if treated > 0 else float("nan")
    
    # Net revenue per patient (useful for break-even)
    net_rev_per_patient = (net_revenue / treated) if treated > 0 else 0.0

    return {
        "treated_patients": treated,
        "gross_revenue": gross_revenue,
        "net_revenue": net_revenue,
        "discount": disc,
        "funnel_cac_total": funnel_cac,
        "platform_costs_total": platform,
        "total_cost": total_cost,
        "net_profit": net_profit,
        "standalone_roi": standalone_roi,
        "cost_per_patient": cost_per_patient,
        "net_rev_per_patient": net_rev_per_patient,
    }


def run_scenario(scenario: dict, stage_names: List[str], base_population: Optional[float] = None):
    """Run a complete scenario calculation."""
    pop = base_population if base_population is not None else float(scenario["base_population"])
    
    funnel_results = compute_funnel(
        stage_names=stage_names,
        ratios=scenario["ratios"],
        stage_active=scenario["stage_active"],
        stage_6_cac=scenario["stage_6_cac"],
        base_population=pop,
    )
    
    platform_costs = sum(scenario.get("platform_costs", {}).values())
    
    financials = compute_financials(
        treated_patients=funnel_results[-1].patients,
        arpp=float(scenario["arpp"]),
        treatment_years=float(scenario["treatment_years"]),
        discount=float(scenario["discount"]),
        funnel_cac_total=funnel_results[-1].cumulative_cac,
        platform_costs=platform_costs,
    )
    
    return funnel_results, financials


def compute_incremental_metrics(baseline_fin: dict, dario_fin: dict) -> dict:
    """
    Calculate incremental metrics between baseline and Dario.
    
    Key metrics:
    - Incremental Patients = Dario Patients - Baseline Patients
    - Incremental Net Revenue = Dario Net Revenue - Baseline Net Revenue  
    - Incremental Cost = Dario Total Cost - Baseline Total Cost
    - Incremental Profit = Dario Net Profit - Baseline Net Profit
    - Incremental ROI (Profit-based) = Incremental Profit / Incremental Cost
    """
    incr_patients = dario_fin["treated_patients"] - baseline_fin["treated_patients"]
    incr_gross = dario_fin["gross_revenue"] - baseline_fin["gross_revenue"]
    incr_net_revenue = dario_fin["net_revenue"] - baseline_fin["net_revenue"]
    incr_cost = dario_fin["total_cost"] - baseline_fin["total_cost"]
    incr_profit = dario_fin["net_profit"] - baseline_fin["net_profit"]
    
    # Incremental ROI (Profit-based)
    # Only meaningful when incremental cost > 0
    if incr_cost > 0:
        incr_roi_profit = incr_profit / incr_cost
    elif incr_cost < 0 and incr_profit > 0:
        # Dario costs less AND generates more profit - infinite ROI conceptually
        incr_roi_profit = float("inf")
    else:
        incr_roi_profit = float("nan")
    
    # Cost per incremental patient
    if incr_patients > 0 and incr_cost > 0:
        cost_per_incr_patient = incr_cost / incr_patients
    else:
        cost_per_incr_patient = float("nan")
    
    return {
        "incremental_patients": incr_patients,
        "incremental_gross_revenue": incr_gross,
        "incremental_net_revenue": incr_net_revenue,
        "incremental_cost": incr_cost,
        "incremental_profit": incr_profit,
        "incremental_roi_profit": incr_roi_profit,
        "cost_per_incremental_patient": cost_per_incr_patient,
    }


def compute_breakeven(dario_fin: dict, incr: dict) -> dict:
    """
    Calculate break-even analysis.
    
    Break-even patients = Incremental Cost / Net Revenue per Patient (Dario)
    
    This tells you how many incremental patients you need to cover the
    incremental cost of the Dario investment.
    """
    net_rev_per_patient = dario_fin["net_rev_per_patient"]
    incr_cost = incr["incremental_cost"]
    incr_patients = incr["incremental_patients"]
    
    # Handle edge cases
    if incr_cost <= 0:
        # Dario costs the same or less - no break-even needed
        return {
            "breakeven_patients": 0.0,
            "patients_vs_breakeven": incr_patients,
            "is_above_breakeven": True,
            "breakeven_applicable": False,
            "message": "Dario costs ≤ baseline - no break-even threshold needed",
        }
    
    if net_rev_per_patient <= 0:
        return {
            "breakeven_patients": float("nan"),
            "patients_vs_breakeven": float("nan"),
            "is_above_breakeven": False,
            "breakeven_applicable": False,
            "message": "No revenue per patient - cannot calculate break-even",
        }
    
    breakeven_patients = incr_cost / net_rev_per_patient
    patients_vs_breakeven = incr_patients - breakeven_patients
    is_above = patients_vs_breakeven >= 0
    
    return {
        "breakeven_patients": breakeven_patients,
        "patients_vs_breakeven": patients_vs_breakeven,
        "is_above_breakeven": is_above,
        "breakeven_applicable": True,
        "message": None,
    }


def compute_cac_sensitivity(model: dict, cac_min: float, cac_max: float, cac_step: float) -> List[dict]:
    """
    Run sensitivity analysis varying baseline Stage 6 CAC.
    Shows how incremental metrics change as baseline CAC assumption varies.
    """
    results = []
    stage_names = model["shared"]["stage_names"]
    
    base_pop = model["shared"]["shared_base_population"] if model["shared"]["use_shared_base_population"] else None
    
    # Dario stays constant
    _, dario_fin = run_scenario(model["dario"], stage_names, base_pop)
    
    cac = cac_min
    while cac <= cac_max + 0.001:  # Small epsilon for float comparison
        baseline_mod = copy.deepcopy(model["baseline"])
        baseline_mod["stage_6_cac"] = cac
        
        _, baseline_fin = run_scenario(baseline_mod, stage_names, base_pop)
        incr = compute_incremental_metrics(baseline_fin, dario_fin)
        
        results.append({
            "baseline_cac": cac,
            "baseline_total_cost": baseline_fin["total_cost"],
            "incremental_cost": incr["incremental_cost"],
            "incremental_profit": incr["incremental_profit"],
            "incremental_roi_profit": incr["incremental_roi_profit"] if incr["incremental_roi_profit"] != float("inf") else 999,
        })
        
        cac += cac_step
    
    return results


def run_full_model(model: dict) -> dict:
    """Run complete model calculation."""
    stage_names = model["shared"]["stage_names"]
    base_pop = model["shared"]["shared_base_population"] if model["shared"]["use_shared_base_population"] else None
    
    baseline_funnel, baseline_fin = run_scenario(model["baseline"], stage_names, base_pop)
    dario_funnel, dario_fin = run_scenario(model["dario"], stage_names, base_pop)
    
    incr = compute_incremental_metrics(baseline_fin, dario_fin)
    breakeven = compute_breakeven(dario_fin, incr)
    
    sensitivity = None
    if model["baseline"].get("cac_mode") == "sensitivity":
        sens_cfg = model["baseline"]["cac_sensitivity"]
        sensitivity = compute_cac_sensitivity(model, sens_cfg["min"], sens_cfg["max"], sens_cfg["step"])
    
    return {
        "baseline_funnel": baseline_funnel,
        "baseline_fin": baseline_fin,
        "dario_funnel": dario_funnel,
        "dario_fin": dario_fin,
        "incremental": incr,
        "breakeven": breakeven,
        "sensitivity": sensitivity,
    }


# =============================================================================
# EXCEL EXPORT
# =============================================================================
def build_excel_report(model_name: str, results: dict, model: dict) -> bytes:
    """Build Excel report with multiple sheets."""
    wb = Workbook()
    header_fill = PatternFill("solid", fgColor="0F172A")
    header_font = Font(bold=True, color="FFFFFF")
    center = Alignment(horizontal="center", vertical="center")

    def style_header(ws, row=1):
        for cell in ws[row]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center

    def set_widths(ws, widths):
        for col, w in widths.items():
            ws.column_dimensions[get_column_letter(col)].width = w

    # Summary Sheet
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = f"PharmaROI — {model_name}"
    ws["A1"].font = Font(bold=True, size=14)
    
    ws["A3"], ws["B3"], ws["C3"], ws["D3"] = "Metric", "Baseline", "Dario", "Incremental"
    style_header(ws, 3)

    baseline = results["baseline_fin"]
    dario = results["dario_fin"]
    incr = results["incremental"]

    rows = [
        ("Treated Patients", baseline["treated_patients"], dario["treated_patients"], incr["incremental_patients"]),
        ("Gross Revenue", baseline["gross_revenue"], dario["gross_revenue"], incr["incremental_gross_revenue"]),
        ("Net Revenue", baseline["net_revenue"], dario["net_revenue"], incr["incremental_net_revenue"]),
        ("Total Cost", baseline["total_cost"], dario["total_cost"], incr["incremental_cost"]),
        ("Net Profit", baseline["net_profit"], dario["net_profit"], incr["incremental_profit"]),
        ("Standalone ROI", baseline["standalone_roi"], dario["standalone_roi"], incr["incremental_roi_profit"]),
    ]

    for i, (label, b, d, inc) in enumerate(rows):
        r = 4 + i
        ws[f"A{r}"] = label
        ws[f"B{r}"] = b if b == b else None
        ws[f"C{r}"] = d if d == d else None
        ws[f"D{r}"] = inc if inc == inc else None

    set_widths(ws, {1: 20, 2: 18, 3: 18, 4: 18})

    # Baseline Funnel
    ws_b = wb.create_sheet("Baseline Funnel")
    headers = ["#", "Stage", "Ratio", "Patients", "CAC/pt", "Cumulative CAC"]
    for c, h in enumerate(headers, 1):
        ws_b.cell(1, c, h)
    style_header(ws_b, 1)

    for i, r in enumerate(results["baseline_funnel"], 2):
        ws_b.cell(i, 1, i-1)
        ws_b.cell(i, 2, r.name)
        ws_b.cell(i, 3, r.ratio_used)
        ws_b.cell(i, 4, r.patients)
        ws_b.cell(i, 5, r.cac_per_patient)
        ws_b.cell(i, 6, r.cumulative_cac)

    set_widths(ws_b, {1: 5, 2: 45, 3: 10, 4: 15, 5: 12, 6: 18})

    # Dario Funnel
    ws_d = wb.create_sheet("Dario Funnel")
    for c, h in enumerate(headers, 1):
        ws_d.cell(1, c, h)
    style_header(ws_d, 1)

    for i, r in enumerate(results["dario_funnel"], 2):
        ws_d.cell(i, 1, i-1)
        ws_d.cell(i, 2, r.name)
        ws_d.cell(i, 3, r.ratio_used)
        ws_d.cell(i, 4, r.patients)
        ws_d.cell(i, 5, r.cac_per_patient)
        ws_d.cell(i, 6, r.cumulative_cac)

    set_widths(ws_d, {1: 5, 2: 45, 3: 10, 4: 15, 5: 12, 6: 18})

    # Sensitivity (if available)
    if results["sensitivity"]:
        ws_s = wb.create_sheet("Sensitivity")
        sens_headers = ["Baseline CAC", "Incr Cost", "Incr Profit", "Incr ROI"]
        for c, h in enumerate(sens_headers, 1):
            ws_s.cell(1, c, h)
        style_header(ws_s, 1)

        for i, row in enumerate(results["sensitivity"], 2):
            ws_s.cell(i, 1, row["baseline_cac"])
            ws_s.cell(i, 2, row["incremental_cost"])
            ws_s.cell(i, 3, row["incremental_profit"])
            ws_s.cell(i, 4, row["incremental_roi_profit"])

        set_widths(ws_s, {1: 15, 2: 15, 3: 15, 4: 15})

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


# =============================================================================
# SESSION STATE
# =============================================================================
def init_session():
    if "models" not in st.session_state:
        st.session_state["models"] = [get_default_model()]
        st.session_state["model_names"] = ["Model 1"]
        st.session_state["active_model_idx"] = 0
    else:
        # Migrate old models
        for i, model in enumerate(st.session_state["models"]):
            st.session_state["models"][i] = migrate_model(model)

init_session()


# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(page_title="PharmaROI V4", page_icon="📈", layout="wide")
st.title("PharmaROI Intelligence — V4")
st.caption("Compare Baseline vs Dario-Enabled scenarios and calculate incremental ROI")


# =============================================================================
# MODEL MANAGEMENT BAR
# =============================================================================
col1, col2, col3, col4 = st.columns([2, 2, 2, 4])

with col1:
    if st.button("Add New Model", use_container_width=True):
        n = len(st.session_state["models"]) + 1
        st.session_state["models"].append(get_default_model())
        st.session_state["model_names"].append(f"Model {n}")
        st.session_state["active_model_idx"] = len(st.session_state["models"]) - 1
        st.rerun()

with col2:
    copy_idx = st.selectbox(
        "Copy from:",
        range(len(st.session_state["model_names"])),
        format_func=lambda i: st.session_state["model_names"][i],
        index=st.session_state["active_model_idx"],
        key="copy_source",
        label_visibility="collapsed",
    )
    if st.button("Copy Model", use_container_width=True):
        new_model = copy.deepcopy(st.session_state["models"][copy_idx])
        new_name = st.session_state["model_names"][copy_idx] + " (copy)"
        st.session_state["models"].append(new_model)
        st.session_state["model_names"].append(new_name)
        st.session_state["active_model_idx"] = len(st.session_state["models"]) - 1
        st.rerun()

with col3:
    can_delete = len(st.session_state["models"]) > 1
    if "confirm_delete" not in st.session_state:
        st.session_state["confirm_delete"] = False

    if not st.session_state["confirm_delete"]:
        if st.button("Delete Model", use_container_width=True, disabled=not can_delete):
            st.session_state["confirm_delete"] = True
            st.rerun()
    else:
        st.warning(f"Delete '{st.session_state['model_names'][st.session_state['active_model_idx']]}'?")
        c1, c2 = st.columns(2)
        if c1.button("Yes", use_container_width=True):
            idx = st.session_state["active_model_idx"]
            st.session_state["models"].pop(idx)
            st.session_state["model_names"].pop(idx)
            st.session_state["active_model_idx"] = max(0, idx - 1)
            st.session_state["confirm_delete"] = False
            st.rerun()
        if c2.button("No", use_container_width=True):
            st.session_state["confirm_delete"] = False
            st.rerun()

with col4:
    idx = st.session_state["active_model_idx"]
    new_name = st.text_input(
        "Model name:",
        st.session_state["model_names"][idx],
        key=f"rename_{idx}",
        label_visibility="collapsed",
    )
    if new_name != st.session_state["model_names"][idx]:
        st.session_state["model_names"][idx] = new_name


# =============================================================================
# TABS
# =============================================================================
tab_labels = st.session_state["model_names"] + ["Comparison"]
tabs = st.tabs(tab_labels)


# =============================================================================
# MODEL TABS
# =============================================================================
for model_idx, model_tab in enumerate(tabs[:-1]):
    with model_tab:
        model = st.session_state["models"][model_idx]
        model_name = st.session_state["model_names"][model_idx]
        st.session_state["active_model_idx"] = model_idx

        # ----- SHARED SETTINGS -----
        with st.expander("Shared Settings", expanded=False):
            model["shared"]["use_shared_base_population"] = st.checkbox(
                "Use same base population for both scenarios",
                model["shared"]["use_shared_base_population"],
                key=f"shared_pop_toggle_{model_idx}",
            )

            if model["shared"]["use_shared_base_population"]:
                model["shared"]["shared_base_population"] = st.number_input(
                    "Base Population (TAM)",
                    min_value=0, step=100_000,
                    value=int(model["shared"]["shared_base_population"]),
                    key=f"shared_pop_{model_idx}",
                )

            with st.expander("Stage Names"):
                for sidx in range(NUM_STAGES):
                    model["shared"]["stage_names"][sidx] = st.text_input(
                        f"Stage {sidx+1}:",
                        model["shared"]["stage_names"][sidx],
                        key=f"sname_{model_idx}_{sidx}",
                    )

            c1, c2 = st.columns(2)
            if c1.button("Reset to Defaults", key=f"reset_def_{model_idx}"):
                st.session_state["models"][model_idx] = get_default_model()
                st.rerun()
            if c2.button("Reset to Zero", key=f"reset_zero_{model_idx}"):
                st.session_state["models"][model_idx] = get_zero_model()
                st.rerun()

        stage_names = model["shared"]["stage_names"]

        # ----- BASELINE SCENARIO -----
        st.markdown("---")
        st.subheader("Baseline Scenario (Without Dario)")
        
        baseline = model["baseline"]

        with st.expander("Baseline Configuration", expanded=True):
            if not model["shared"]["use_shared_base_population"]:
                baseline["base_population"] = st.number_input(
                    "Base Population",
                    min_value=0, step=100_000,
                    value=int(baseline["base_population"]),
                    key=f"b_pop_{model_idx}",
                )

            st.markdown("**Revenue Assumptions**")
            bc1, bc2, bc3 = st.columns(3)
            baseline["arpp"] = bc1.number_input("ARPP ($/year)", min_value=0.0, step=1000.0, value=float(baseline["arpp"]), key=f"b_arpp_{model_idx}")
            baseline["treatment_years"] = bc2.slider("Treatment Years", 0.1, 5.0, float(baseline["treatment_years"]), 0.1, key=f"b_years_{model_idx}")
            baseline["discount"] = bc3.slider("Discount (Gross→Net)", 0.0, 1.0, float(baseline["discount"]), 0.01, key=f"b_disc_{model_idx}")

            st.markdown("**Stage 6 CAC (CAC Pool Driver)**")
            st.caption("This is the only CAC input - it creates the total acquisition cost pool at Stage 6. Stages 7-13 inherit this cost distributed across remaining patients.")
            
            baseline["cac_mode"] = st.radio(
                "CAC Input Mode:",
                ["direct", "sensitivity"],
                format_func=lambda x: "Direct Input" if x == "direct" else "Sensitivity Range",
                index=0 if baseline["cac_mode"] == "direct" else 1,
                key=f"b_cac_mode_{model_idx}",
                horizontal=True,
            )

            if baseline["cac_mode"] == "direct":
                baseline["stage_6_cac"] = st.number_input(
                    "Stage 6 CAC ($ per patient at activation)",
                    min_value=0.0, step=1.0,
                    value=float(baseline["stage_6_cac"]),
                    key=f"b_cac6_{model_idx}",
                )
            else:
                sc1, sc2, sc3, sc4 = st.columns(4)
                baseline["cac_sensitivity"]["min"] = sc1.number_input("Min", 0.0, step=1.0, value=float(baseline["cac_sensitivity"]["min"]), key=f"b_sens_min_{model_idx}")
                baseline["cac_sensitivity"]["max"] = sc2.number_input("Max", 0.0, step=1.0, value=float(baseline["cac_sensitivity"]["max"]), key=f"b_sens_max_{model_idx}")
                baseline["cac_sensitivity"]["step"] = sc3.number_input("Step", 0.1, step=0.5, value=float(baseline["cac_sensitivity"]["step"]), key=f"b_sens_step_{model_idx}")
                baseline["cac_sensitivity"]["base"] = sc4.number_input("Base Case", 0.0, step=1.0, value=float(baseline["cac_sensitivity"]["base"]), key=f"b_sens_base_{model_idx}")
                baseline["stage_6_cac"] = baseline["cac_sensitivity"]["base"]

            st.markdown("**Funnel Conversion Rates**")
            with st.expander("Stage Ratios (Baseline)"):
                for sidx in range(1, NUM_STAGES):
                    baseline["ratios"][sidx] = st.slider(
                        f"Stage {sidx+1}: {stage_names[sidx][:50]}",
                        0.0, 1.0, float(baseline["ratios"][sidx]), 0.01,
                        key=f"b_ratio_{model_idx}_{sidx}",
                    )

            st.markdown("**Platform Costs (Baseline)**")
            st.caption("Typically $0 for baseline (no Dario platform)")
            pc_b = baseline["platform_costs"]
            pbc1, pbc2, pbc3 = st.columns(3)
            pc_b["config_costs"] = pbc1.number_input("Config Costs", 0.0, step=10000.0, value=float(pc_b["config_costs"]), key=f"b_pc1_{model_idx}")
            pc_b["subscription_costs"] = pbc2.number_input("Subscription", 0.0, step=10000.0, value=float(pc_b["subscription_costs"]), key=f"b_pc2_{model_idx}")
            pc_b["maintenance_costs"] = pbc3.number_input("Maintenance", 0.0, step=10000.0, value=float(pc_b["maintenance_costs"]), key=f"b_pc3_{model_idx}")

        # ----- DARIO SCENARIO -----
        st.markdown("---")
        st.subheader("Dario-Enabled Scenario")
        
        dario = model["dario"]

        with st.expander("Dario Configuration", expanded=True):
            if not model["shared"]["use_shared_base_population"]:
                dario["base_population"] = st.number_input(
                    "Base Population",
                    min_value=0, step=100_000,
                    value=int(dario["base_population"]),
                    key=f"d_pop_{model_idx}",
                )

            st.markdown("**Revenue Assumptions**")
            dc1, dc2, dc3 = st.columns(3)
            dario["arpp"] = dc1.number_input("ARPP ($/year)", min_value=0.0, step=1000.0, value=float(dario["arpp"]), key=f"d_arpp_{model_idx}")
            dario["treatment_years"] = dc2.slider("Treatment Years", 0.1, 5.0, float(dario["treatment_years"]), 0.1, key=f"d_years_{model_idx}")
            dario["discount"] = dc3.slider("Discount (Gross→Net)", 0.0, 1.0, float(dario["discount"]), 0.01, key=f"d_disc_{model_idx}")

            st.markdown("**Stage 6 CAC (CAC Pool Driver)**")
            dario["stage_6_cac"] = st.number_input(
                "Stage 6 CAC ($ per patient at activation)",
                min_value=0.0, step=1.0,
                value=float(dario["stage_6_cac"]),
                key=f"d_cac6_{model_idx}",
            )

            st.markdown("**Funnel Conversion Rates**")
            with st.expander("Stage Ratios (Dario)"):
                for sidx in range(1, NUM_STAGES):
                    dario["ratios"][sidx] = st.slider(
                        f"Stage {sidx+1}: {stage_names[sidx][:50]}",
                        0.0, 1.0, float(dario["ratios"][sidx]), 0.01,
                        key=f"d_ratio_{model_idx}_{sidx}",
                    )

            st.markdown("**Platform Costs (Dario)**")
            pc_d = dario["platform_costs"]
            pdc1, pdc2, pdc3 = st.columns(3)
            pc_d["config_costs"] = pdc1.number_input("Config Costs", 0.0, step=10000.0, value=float(pc_d["config_costs"]), key=f"d_pc1_{model_idx}")
            pc_d["subscription_costs"] = pdc2.number_input("Subscription", 0.0, step=10000.0, value=float(pc_d["subscription_costs"]), key=f"d_pc2_{model_idx}")
            pc_d["maintenance_costs"] = pdc3.number_input("Maintenance", 0.0, step=10000.0, value=float(pc_d["maintenance_costs"]), key=f"d_pc3_{model_idx}")
            st.caption(f"**Total Platform Costs:** {money(sum(pc_d.values()))}")

        # ----- RUN CALCULATIONS -----
        results = run_full_model(model)
        b_fin = results["baseline_fin"]
        d_fin = results["dario_fin"]
        incr = results["incremental"]
        be = results["breakeven"]

        # ----- RESULTS SUMMARY -----
        st.markdown("---")
        st.subheader("Results Summary")

        # KPIs in a cleaner grid
        st.markdown("##### Treated Patients")
        k1, k2, k3 = st.columns(3)
        k1.metric("Baseline", number(b_fin["treated_patients"]))
        k2.metric("Dario", number(d_fin["treated_patients"]))
        k3.metric("Incremental", number(incr["incremental_patients"]), 
                  delta=f"{incr['incremental_patients']:+,.0f}" if incr["incremental_patients"] != 0 else None)

        st.markdown("##### Net Revenue")
        k4, k5, k6 = st.columns(3)
        k4.metric("Baseline", money(b_fin["net_revenue"]))
        k5.metric("Dario", money(d_fin["net_revenue"]))
        k6.metric("Incremental", money(incr["incremental_net_revenue"]),
                  delta=delta_money(incr["incremental_net_revenue"]) if incr["incremental_net_revenue"] != 0 else None)

        st.markdown("##### Total Cost")
        k7, k8, k9 = st.columns(3)
        k7.metric("Baseline", money(b_fin["total_cost"]))
        k8.metric("Dario", money(d_fin["total_cost"]))
        k9.metric("Incremental", money(incr["incremental_cost"]),
                  delta=delta_money(incr["incremental_cost"]) if incr["incremental_cost"] != 0 else None)

        st.markdown("##### Profitability")
        k10, k11, k12 = st.columns(3)
        k10.metric("Baseline Net Profit", money(b_fin["net_profit"]))
        k11.metric("Dario Net Profit", money(d_fin["net_profit"]))
        k12.metric("Incremental Profit", money(incr["incremental_profit"]))

        st.markdown("##### ROI Metrics")
        k13, k14, k15 = st.columns(3)
        k13.metric("Baseline Standalone ROI", roix(b_fin["standalone_roi"]), help="Net Revenue / Total Cost")
        k14.metric("Dario Standalone ROI", roix(d_fin["standalone_roi"]), help="Net Revenue / Total Cost")
        roi_display = roix(incr["incremental_roi_profit"]) if incr["incremental_roi_profit"] != float("inf") else "∞ (cost savings)"
        k15.metric("Incremental ROI (Profit)", roi_display, help="Incremental Profit / Incremental Cost")

        st.markdown("##### Break-even Analysis")
        if be["breakeven_applicable"]:
            be1, be2, be3 = st.columns(3)
            be1.metric("Break-even Patients Needed", number(be["breakeven_patients"]))
            be2.metric("Actual Incremental Patients", number(incr["incremental_patients"]))
            if be["is_above_breakeven"]:
                be3.success(f"Above break-even by {number(be['patients_vs_breakeven'])} patients")
            else:
                be3.warning(f"Below break-even by {number(abs(be['patients_vs_breakeven']))} patients")
        else:
            st.info(be["message"])

        # ----- FUNNEL TABLES -----
        st.markdown("---")
        st.subheader("Funnel Details")

        if pd is not None:
            tab_b, tab_d = st.tabs(["Baseline Funnel", "Dario Funnel"])

            with tab_b:
                rows = [{
                    "#": i+1,
                    "Stage": r.name,
                    "Ratio": pct(r.ratio_used) if i > 0 else "—",
                    "Patients": number(r.patients),
                    "CAC/Patient": money(r.cac_per_patient),
                    "Cumulative CAC": money(r.cumulative_cac),
                } for i, r in enumerate(results["baseline_funnel"])]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            with tab_d:
                rows = [{
                    "#": i+1,
                    "Stage": r.name,
                    "Ratio": pct(r.ratio_used) if i > 0 else "—",
                    "Patients": number(r.patients),
                    "CAC/Patient": money(r.cac_per_patient),
                    "Cumulative CAC": money(r.cumulative_cac),
                } for i, r in enumerate(results["dario_funnel"])]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # ----- CHARTS -----
        st.markdown("---")
        st.subheader("Visualizations")

        if pd is not None:
            scenario_colors = alt.Scale(domain=["Baseline", "Dario"], range=[COLORS["baseline"], COLORS["dario"]])

            # Metrics comparison
            st.markdown("**Key Metrics: Baseline vs Dario**")
            chart_data = pd.DataFrame([
                {"Metric": "Net Revenue", "Scenario": "Baseline", "Value": b_fin["net_revenue"]},
                {"Metric": "Net Revenue", "Scenario": "Dario", "Value": d_fin["net_revenue"]},
                {"Metric": "Total Cost", "Scenario": "Baseline", "Value": b_fin["total_cost"]},
                {"Metric": "Total Cost", "Scenario": "Dario", "Value": d_fin["total_cost"]},
                {"Metric": "Net Profit", "Scenario": "Baseline", "Value": b_fin["net_profit"]},
                {"Metric": "Net Profit", "Scenario": "Dario", "Value": d_fin["net_profit"]},
            ])

            chart = alt.Chart(chart_data).mark_bar().encode(
                x=alt.X("Scenario:N", title=None),
                y=alt.Y("Value:Q", title="USD", axis=alt.Axis(format="$,.0f")),
                color=alt.Color("Scenario:N", scale=scenario_colors, legend=None),
                column=alt.Column("Metric:N", title=None),
                tooltip=["Scenario", alt.Tooltip("Value:Q", format="$,.0f")],
            ).properties(width=180, height=300)
            st.altair_chart(chart)

            # Funnel comparison
            st.markdown("**Funnel Progression: Patients by Stage**")
            funnel_data = []
            for i, (b, d) in enumerate(zip(results["baseline_funnel"], results["dario_funnel"])):
                funnel_data.append({"Stage": f"{i+1}. {b.name[:25]}", "Scenario": "Baseline", "Patients": b.patients})
                funnel_data.append({"Stage": f"{i+1}. {d.name[:25]}", "Scenario": "Dario", "Patients": d.patients})

            funnel_chart = alt.Chart(pd.DataFrame(funnel_data)).mark_line(point=True).encode(
                x=alt.X("Stage:N", sort=None, axis=alt.Axis(labelAngle=-45, labelLimit=150)),
                y=alt.Y("Patients:Q", axis=alt.Axis(format=",.0f")),
                color=alt.Color("Scenario:N", scale=scenario_colors),
                tooltip=["Stage", "Scenario", alt.Tooltip("Patients:Q", format=",.0f")],
            ).properties(height=400)
            st.altair_chart(funnel_chart, use_container_width=True)

            # Sensitivity
            if results["sensitivity"]:
                st.markdown("**Sensitivity: Incremental Profit vs Baseline CAC**")
                st.caption("Shows how incremental profit changes as you vary the baseline CAC assumption. Break-even is at $0 incremental profit.")
                
                sens_df = pd.DataFrame(results["sensitivity"])

                sens_chart = alt.Chart(sens_df).mark_line(point=True, color=COLORS["incremental"]).encode(
                    x=alt.X("baseline_cac:Q", title="Baseline Stage 6 CAC ($)"),
                    y=alt.Y("incremental_profit:Q", title="Incremental Profit ($)", axis=alt.Axis(format="$,.0f")),
                    tooltip=[
                        alt.Tooltip("baseline_cac:Q", title="Baseline CAC", format="$.0f"),
                        alt.Tooltip("incremental_profit:Q", title="Incr Profit", format="$,.0f"),
                    ],
                ).properties(height=350)

                # Break-even line at $0 profit
                zero_line = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(strokeDash=[5,5], color=COLORS["warning"]).encode(y="y:Q")

                st.altair_chart(sens_chart + zero_line, use_container_width=True)

                with st.expander("Sensitivity Table"):
                    disp = sens_df.copy()
                    disp["baseline_cac"] = disp["baseline_cac"].map(lambda x: f"${x:,.0f}")
                    disp["incremental_cost"] = disp["incremental_cost"].map(lambda x: f"${x:,.0f}")
                    disp["incremental_profit"] = disp["incremental_profit"].map(lambda x: f"${x:,.0f}")
                    disp["incremental_roi_profit"] = disp["incremental_roi_profit"].map(lambda x: f"{x:.2f}x")
                    st.dataframe(disp, use_container_width=True, hide_index=True)

        # ----- EXPORT -----
        st.markdown("---")
        st.subheader("Export")
        
        ec1, ec2 = st.columns(2)
        with ec1:
            xlsx = build_excel_report(model_name, results, model)
            st.download_button("Download Excel", xlsx, f"{model_name.replace(' ','_')}.xlsx", 
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"xlsx_{model_idx}")
        with ec2:
            json_data = json.dumps({"name": model_name, "model": model}, indent=2)
            st.download_button("Export JSON", json_data, f"{model_name.replace(' ','_')}.json", 
                             "application/json", key=f"json_{model_idx}")


# =============================================================================
# COMPARISON TAB
# =============================================================================
with tabs[-1]:
    st.subheader("Model Comparison")

    if len(st.session_state["models"]) < 1:
        st.info("Add a model to see comparisons.")
    else:
        selected = st.multiselect(
            "Select models:",
            st.session_state["model_names"],
            default=st.session_state["model_names"],
            key="comp_select",
        )

        if not selected:
            st.warning("Select at least one model.")
            st.stop()

        sel_idx = [i for i, n in enumerate(st.session_state["model_names"]) if n in selected]
        sel_models = [st.session_state["models"][i] for i in sel_idx]
        sel_names = [st.session_state["model_names"][i] for i in sel_idx]

        # Build comparison data
        comp_rows = []
        for m, n in zip(sel_models, sel_names):
            r = run_full_model(m)
            comp_rows.append({
                "Model": n,
                "Baseline Patients": r["baseline_fin"]["treated_patients"],
                "Dario Patients": r["dario_fin"]["treated_patients"],
                "Incr Patients": r["incremental"]["incremental_patients"],
                "Baseline Revenue": r["baseline_fin"]["net_revenue"],
                "Dario Revenue": r["dario_fin"]["net_revenue"],
                "Incr Revenue": r["incremental"]["incremental_net_revenue"],
                "Baseline Cost": r["baseline_fin"]["total_cost"],
                "Dario Cost": r["dario_fin"]["total_cost"],
                "Incr Cost": r["incremental"]["incremental_cost"],
                "Incr Profit": r["incremental"]["incremental_profit"],
                "Incr ROI": r["incremental"]["incremental_roi_profit"],
            })

        if pd is not None:
            comp_df = pd.DataFrame(comp_rows)

            st.markdown("### Summary Table")
            disp = comp_df.copy()
            for c in ["Baseline Patients", "Dario Patients", "Incr Patients"]:
                disp[c] = disp[c].map(lambda x: f"{x:,.0f}")
            for c in ["Baseline Revenue", "Dario Revenue", "Incr Revenue", "Baseline Cost", "Dario Cost", "Incr Cost", "Incr Profit"]:
                disp[c] = disp[c].map(lambda x: f"${x:,.0f}")
            disp["Incr ROI"] = disp["Incr ROI"].map(lambda x: f"{x:.2f}x" if x != float("inf") and x == x else "∞" if x == float("inf") else "—")
            st.dataframe(disp, use_container_width=True, hide_index=True)

            st.markdown("### Comparison Charts")
            
            model_colors = alt.Scale(domain=sel_names, range=TAB_PALETTE[:len(sel_names)])

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Incremental Profit**")
                ch = alt.Chart(comp_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                    x=alt.X("Model:N", axis=alt.Axis(labelAngle=-20)),
                    y=alt.Y("Incr Profit:Q", axis=alt.Axis(format="$,.0f")),
                    color=alt.Color("Model:N", scale=model_colors, legend=None),
                    tooltip=["Model", alt.Tooltip("Incr Profit:Q", format="$,.0f")],
                ).properties(height=300)
                st.altair_chart(ch, use_container_width=True)

            with c2:
                st.markdown("**Incremental Patients**")
                ch = alt.Chart(comp_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                    x=alt.X("Model:N", axis=alt.Axis(labelAngle=-20)),
                    y=alt.Y("Incr Patients:Q", axis=alt.Axis(format=",.0f")),
                    color=alt.Color("Model:N", scale=model_colors, legend=None),
                    tooltip=["Model", alt.Tooltip("Incr Patients:Q", format=",.0f")],
                ).properties(height=300)
                st.altair_chart(ch, use_container_width=True)

            # Model diff
            if len(sel_names) >= 2:
                st.markdown("### Parameter Diff")
                dc1, dc2 = st.columns(2)
                ma = dc1.selectbox("Model A:", sel_names, 0, key="diff_a")
                mb = dc2.selectbox("Model B:", [n for n in sel_names if n != ma], 0, key="diff_b")

                idx_a = st.session_state["model_names"].index(ma)
                idx_b = st.session_state["model_names"].index(mb)
                mod_a = st.session_state["models"][idx_a]
                mod_b = st.session_state["models"][idx_b]

                diffs = []
                # Compare key params
                params = [
                    ("Shared Base Pop", mod_a["shared"]["shared_base_population"], mod_b["shared"]["shared_base_population"], "{:,.0f}"),
                    ("Baseline Stage 6 CAC", mod_a["baseline"]["stage_6_cac"], mod_b["baseline"]["stage_6_cac"], "${:,.0f}"),
                    ("Dario Stage 6 CAC", mod_a["dario"]["stage_6_cac"], mod_b["dario"]["stage_6_cac"], "${:,.0f}"),
                    ("Baseline ARPP", mod_a["baseline"]["arpp"], mod_b["baseline"]["arpp"], "${:,.0f}"),
                    ("Dario ARPP", mod_a["dario"]["arpp"], mod_b["dario"]["arpp"], "${:,.0f}"),
                    ("Baseline Discount", mod_a["baseline"]["discount"], mod_b["baseline"]["discount"], "{:.1%}"),
                    ("Dario Discount", mod_a["dario"]["discount"], mod_b["dario"]["discount"], "{:.1%}"),
                ]
                for label, va, vb, fmt in params:
                    if va != vb:
                        diffs.append({"Parameter": label, ma: fmt.format(va), mb: fmt.format(vb)})

                if diffs:
                    st.dataframe(pd.DataFrame(diffs), use_container_width=True, hide_index=True)
                else:
                    st.success("Models have identical key parameters!")

            st.markdown("### Export")
            csv = comp_df.to_csv(index=False).encode()
            st.download_button("Download CSV", csv, "comparison.csv", "text/csv")


# =============================================================================
# FOOTER
# =============================================================================
st.divider()
st.subheader("Reference")
st.markdown("""
**CAC Logic:**
- Only **Stage 6 CAC** matters — it creates the total acquisition cost pool
- Stages 1-5 have no CAC; Stages 7-13 inherit from the Stage 6 pool

**Key Formulas:**
- **Gross Revenue** = Patients × ARPP × Treatment Years
- **Net Revenue** = Gross Revenue × (1 - Discount)
- **Total Cost** = Funnel CAC + Platform Costs
- **Net Profit** = Net Revenue - Total Cost
- **Standalone ROI** = Net Revenue / Total Cost
- **Incremental ROI (Profit)** = Incremental Profit / Incremental Cost

**Break-even:**
- Break-even Patients = Incremental Cost / Net Revenue per Patient
- If Dario costs ≤ baseline, no break-even threshold applies
""")
