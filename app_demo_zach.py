"""
PharmaROI Intelligence Platform - V5 Production
================================================
Multi-model ROI analysis with:
- Baseline vs Dario scenario comparison
- Optimization Timeline Mode (Launch → Optimization 1 → Optimization 2 → Steady State)
- Ad-Agency baseline comparison
- CAC sensitivity analysis
- Comprehensive exports (Excel, JSON, CSV)

Author: PharmaROI Team
Version: 5.0 Production
"""

import copy
import json
import io
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import math

import streamlit as st
import pandas as pd
import altair as alt

# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

APP_VERSION = "5.0"

# Color palette
COLORS = {
    "primary": "#1E3A5F",
    "secondary": "#3498DB",
    "success": "#27AE60",
    "warning": "#F39C12",
    "danger": "#E74C3C",
    "baseline": "#7F8C8D",
    "dario": "#2ECC71",
    "ad_agency": "#9B59B6",
    "timeline_launch": "#E74C3C",
    "timeline_opt1": "#F39C12",
    "timeline_opt2": "#3498DB",
    "timeline_steady": "#27AE60",
}

TAB_PALETTE = [
    "#1E3A5F", "#3498DB", "#27AE60", "#F39C12", "#E74C3C",
    "#9B59B6", "#1ABC9C", "#E67E22", "#2C3E50", "#16A085",
]

# Funnel stage definitions
STAGE_NAMES = [
    "Total Addressable Market",
    "Aware of Disease State",
    "Diagnosed (Total Prevalence)",
    "Active Help Seekers",
    "Active Digital Help Seekers",
    "Aware of Dario",
    "Consideration / First Visit",
    "Lead / Engaged Contact",
    "Marketing Qualified Lead",
    "App Download / Sign-up",
    "Activation within 90 days onto Dario Connect for MASH",
    "Engaged on Dario Connect for MASH (60+ days)",
    "Referred / Prescribed Treatment",
]
NUM_STAGES = len(STAGE_NAMES)

# Timeline period definitions
TIMELINE_PERIODS = [
    {"name": "Launch", "months": 6, "color": COLORS["timeline_launch"]},
    {"name": "Optimization 1", "months": 6, "color": COLORS["timeline_opt1"]},
    {"name": "Optimization 2", "months": 6, "color": COLORS["timeline_opt2"]},
    {"name": "Steady State", "months": 12, "color": COLORS["timeline_steady"]},
]

# =============================================================================
# PRESET SCENARIOS
# =============================================================================

def create_default_ratios(multipliers: List[float] = None) -> List[float]:
    """Create funnel ratios with optional stage multipliers."""
    base = [
        1.0,    # Stage 1: TAM (always 1.0)
        0.50,   # Stage 2: Aware of Disease
        0.25,   # Stage 3: Diagnosed
        0.15,   # Stage 4: Active Help Seekers
        0.08,   # Stage 5: Digital Help Seekers
        0.04,   # Stage 6: Aware of Dario
        0.50,   # Stage 7: Consideration
        0.40,   # Stage 8: Lead
        0.60,   # Stage 9: MQL
        0.50,   # Stage 10: App Download
        0.30,   # Stage 11: Activation
        0.70,   # Stage 12: Engaged
        0.50,   # Stage 13: Referred
    ]
    if multipliers:
        return [b * m for b, m in zip(base, multipliers + [1.0] * (NUM_STAGES - len(multipliers)))]
    return base

def create_default_cac() -> List[float]:
    """CAC: Only Stage 6 has direct CAC input; others are derived."""
    return [0.0] * 6 + [0.0] * 7  # Stage 6 CAC set separately

# Preset: Ad-Agency Baseline
AD_AGENCY_BASELINE = {
    "name": "Ad-Agency Baseline",
    "description": "Traditional digital advertising with typical pharma ROAS",
    "shared": {
        "base_population": 30_000_000,
        "stage_names": STAGE_NAMES.copy(),
        "use_timeline_mode": False,
    },
    "baseline": {
        "arpp": 85_000,
        "treatment_years": 2.5,
        "discount": 0.70,
        "cac_mode": "direct",
        "stage_6_cac": 1_200,
        "cac_sensitivity": {"min": 800, "max": 2000, "step": 100, "base": 1200},
        "ratios": create_default_ratios([1.0, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.25, 0.4, 0.35, 0.2, 0.5, 0.3]),
        "stage_active": [True] * NUM_STAGES,
        "platform_costs": {
            "ad_spend": 500_000,
            "agency_fees": 150_000,
            "creative": 50_000,
            "analytics": 25_000,
            "other": 25_000,
        },
    },
    "dario": {
        "arpp": 85_000,
        "treatment_years": 3.0,
        "discount": 0.70,
        "cac_mode": "direct",
        "stage_6_cac": 800,
        "cac_sensitivity": {"min": 500, "max": 1500, "step": 100, "base": 800},
        "ratios": create_default_ratios(),
        "stage_active": [True] * NUM_STAGES,
        "platform_costs": {
            "dario_connect_config": 180_000,
            "dario_care_config": 120_000,
            "sub_dario_connect": 96_000,
            "sub_dario_care": 72_000,
            "maintenance_support": 50_000,
        },
    },
    "ad_agency_comparison": {
        "enabled": True,
        "roas": 1.35,
        "budget": 750_000,
    },
}

# Preset: Dario Launch Phase
DARIO_LAUNCH = {
    "name": "Dario Launch",
    "description": "Initial launch with conservative assumptions",
    "shared": {
        "base_population": 30_000_000,
        "stage_names": STAGE_NAMES.copy(),
        "use_timeline_mode": False,
    },
    "baseline": {
        "arpp": 85_000,
        "treatment_years": 2.5,
        "discount": 0.70,
        "cac_mode": "direct",
        "stage_6_cac": 1_000,
        "cac_sensitivity": {"min": 600, "max": 1500, "step": 100, "base": 1000},
        "ratios": create_default_ratios([1.0, 0.6, 0.5, 0.4, 0.35, 0.3, 0.25, 0.2, 0.35, 0.3, 0.15, 0.4, 0.3]),
        "stage_active": [True] * NUM_STAGES,
        "platform_costs": {
            "dario_connect_config": 0,
            "dario_care_config": 0,
            "sub_dario_connect": 0,
            "sub_dario_care": 0,
            "maintenance_support": 0,
        },
    },
    "dario": {
        "arpp": 85_000,
        "treatment_years": 3.0,
        "discount": 0.70,
        "cac_mode": "direct",
        "stage_6_cac": 650,
        "cac_sensitivity": {"min": 400, "max": 1200, "step": 100, "base": 650},
        "ratios": create_default_ratios([1.0, 0.7, 0.6, 0.5, 0.45, 0.4, 0.35, 0.3, 0.45, 0.4, 0.2, 0.55, 0.4]),
        "stage_active": [True] * NUM_STAGES,
        "platform_costs": {
            "dario_connect_config": 180_000,
            "dario_care_config": 120_000,
            "sub_dario_connect": 96_000,
            "sub_dario_care": 72_000,
            "maintenance_support": 50_000,
        },
    },
    "ad_agency_comparison": {
        "enabled": False,
        "roas": 1.35,
        "budget": 500_000,
    },
}

# Preset: Dario Optimization 1
DARIO_OPT1 = {
    "name": "Dario Optimization 1",
    "description": "First optimization phase with improved conversions",
    "shared": {
        "base_population": 30_000_000,
        "stage_names": STAGE_NAMES.copy(),
        "use_timeline_mode": False,
    },
    "baseline": {
        "arpp": 85_000,
        "treatment_years": 2.5,
        "discount": 0.70,
        "cac_mode": "direct",
        "stage_6_cac": 900,
        "cac_sensitivity": {"min": 500, "max": 1400, "step": 100, "base": 900},
        "ratios": create_default_ratios([1.0, 0.65, 0.55, 0.45, 0.4, 0.35, 0.3, 0.25, 0.4, 0.35, 0.18, 0.5, 0.35]),
        "stage_active": [True] * NUM_STAGES,
        "platform_costs": {
            "dario_connect_config": 0,
            "dario_care_config": 0,
            "sub_dario_connect": 0,
            "sub_dario_care": 0,
            "maintenance_support": 0,
        },
    },
    "dario": {
        "arpp": 85_000,
        "treatment_years": 3.2,
        "discount": 0.70,
        "cac_mode": "direct",
        "stage_6_cac": 550,
        "cac_sensitivity": {"min": 350, "max": 1000, "step": 50, "base": 550},
        "ratios": create_default_ratios([1.0, 0.75, 0.65, 0.55, 0.5, 0.45, 0.4, 0.35, 0.5, 0.45, 0.25, 0.6, 0.45]),
        "stage_active": [True] * NUM_STAGES,
        "platform_costs": {
            "dario_connect_config": 180_000,
            "dario_care_config": 120_000,
            "sub_dario_connect": 96_000,
            "sub_dario_care": 72_000,
            "maintenance_support": 50_000,
        },
    },
    "ad_agency_comparison": {
        "enabled": False,
        "roas": 1.35,
        "budget": 500_000,
    },
}

# Preset: Dario Optimization 2
DARIO_OPT2 = {
    "name": "Dario Optimization 2",
    "description": "Second optimization phase with refined targeting",
    "shared": {
        "base_population": 30_000_000,
        "stage_names": STAGE_NAMES.copy(),
        "use_timeline_mode": False,
    },
    "baseline": {
        "arpp": 85_000,
        "treatment_years": 2.5,
        "discount": 0.70,
        "cac_mode": "direct",
        "stage_6_cac": 800,
        "cac_sensitivity": {"min": 450, "max": 1200, "step": 100, "base": 800},
        "ratios": create_default_ratios([1.0, 0.7, 0.6, 0.5, 0.45, 0.4, 0.35, 0.3, 0.45, 0.4, 0.2, 0.55, 0.4]),
        "stage_active": [True] * NUM_STAGES,
        "platform_costs": {
            "dario_connect_config": 0,
            "dario_care_config": 0,
            "sub_dario_connect": 0,
            "sub_dario_care": 0,
            "maintenance_support": 0,
        },
    },
    "dario": {
        "arpp": 85_000,
        "treatment_years": 3.5,
        "discount": 0.70,
        "cac_mode": "direct",
        "stage_6_cac": 450,
        "cac_sensitivity": {"min": 300, "max": 800, "step": 50, "base": 450},
        "ratios": create_default_ratios([1.0, 0.8, 0.7, 0.6, 0.55, 0.5, 0.45, 0.4, 0.55, 0.5, 0.3, 0.65, 0.5]),
        "stage_active": [True] * NUM_STAGES,
        "platform_costs": {
            "dario_connect_config": 180_000,
            "dario_care_config": 120_000,
            "sub_dario_connect": 96_000,
            "sub_dario_care": 72_000,
            "maintenance_support": 50_000,
        },
    },
    "ad_agency_comparison": {
        "enabled": False,
        "roas": 1.35,
        "budget": 500_000,
    },
}

# Preset: Dario Steady State
DARIO_STEADY = {
    "name": "Dario Steady State",
    "description": "Mature operation with optimized performance",
    "shared": {
        "base_population": 30_000_000,
        "stage_names": STAGE_NAMES.copy(),
        "use_timeline_mode": False,
    },
    "baseline": {
        "arpp": 85_000,
        "treatment_years": 2.5,
        "discount": 0.70,
        "cac_mode": "direct",
        "stage_6_cac": 700,
        "cac_sensitivity": {"min": 400, "max": 1000, "step": 50, "base": 700},
        "ratios": create_default_ratios([1.0, 0.75, 0.65, 0.55, 0.5, 0.45, 0.4, 0.35, 0.5, 0.45, 0.25, 0.6, 0.45]),
        "stage_active": [True] * NUM_STAGES,
        "platform_costs": {
            "dario_connect_config": 0,
            "dario_care_config": 0,
            "sub_dario_connect": 0,
            "sub_dario_care": 0,
            "maintenance_support": 0,
        },
    },
    "dario": {
        "arpp": 85_000,
        "treatment_years": 4.0,
        "discount": 0.70,
        "cac_mode": "direct",
        "stage_6_cac": 400,
        "cac_sensitivity": {"min": 250, "max": 700, "step": 50, "base": 400},
        "ratios": create_default_ratios([1.0, 0.85, 0.75, 0.65, 0.6, 0.55, 0.5, 0.45, 0.6, 0.55, 0.35, 0.7, 0.55]),
        "stage_active": [True] * NUM_STAGES,
        "platform_costs": {
            "dario_connect_config": 180_000,
            "dario_care_config": 120_000,
            "sub_dario_connect": 96_000,
            "sub_dario_care": 72_000,
            "maintenance_support": 50_000,
        },
    },
    "ad_agency_comparison": {
        "enabled": False,
        "roas": 1.35,
        "budget": 500_000,
    },
}

# Zero/blank model
ZERO_MODEL = {
    "name": "Blank Model",
    "description": "Empty model for manual input",
    "shared": {
        "base_population": 0,
        "stage_names": STAGE_NAMES.copy(),
        "use_timeline_mode": False,
    },
    "baseline": {
        "arpp": 0,
        "treatment_years": 0,
        "discount": 0,
        "cac_mode": "direct",
        "stage_6_cac": 0,
        "cac_sensitivity": {"min": 0, "max": 0, "step": 100, "base": 0},
        "ratios": [1.0] + [0.0] * (NUM_STAGES - 1),
        "stage_active": [True] + [False] * (NUM_STAGES - 1),
        "platform_costs": {
            "dario_connect_config": 0,
            "dario_care_config": 0,
            "sub_dario_connect": 0,
            "sub_dario_care": 0,
            "maintenance_support": 0,
        },
    },
    "dario": {
        "arpp": 0,
        "treatment_years": 0,
        "discount": 0,
        "cac_mode": "direct",
        "stage_6_cac": 0,
        "cac_sensitivity": {"min": 0, "max": 0, "step": 100, "base": 0},
        "ratios": [1.0] + [0.0] * (NUM_STAGES - 1),
        "stage_active": [True] + [False] * (NUM_STAGES - 1),
        "platform_costs": {
            "dario_connect_config": 0,
            "dario_care_config": 0,
            "sub_dario_connect": 0,
            "sub_dario_care": 0,
            "maintenance_support": 0,
        },
    },
    "ad_agency_comparison": {
        "enabled": False,
        "roas": 1.35,
        "budget": 0,
    },
}

MODEL_PRESETS = {
    "Dario Launch": DARIO_LAUNCH,
    "Dario Optimization 1": DARIO_OPT1,
    "Dario Optimization 2": DARIO_OPT2,
    "Dario Steady State": DARIO_STEADY,
    "Ad-Agency Baseline": AD_AGENCY_BASELINE,
    "Blank / Zero": ZERO_MODEL,
}

# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class StageResult:
    """Results for a single funnel stage."""
    stage_num: int
    name: str
    active: bool
    ratio: float
    patients: float
    cac_per_patient: float
    stage_cac: float
    cumulative_cac: float

@dataclass
class ScenarioResult:
    """Complete results for a scenario (baseline or dario)."""
    stages: List[StageResult]
    treated_patients: float
    gross_revenue: float
    net_revenue: float
    total_cac: float
    platform_costs: float
    total_cost: float
    net_profit: float
    roi: float

@dataclass
class IncrementalResult:
    """Incremental comparison between scenarios."""
    incremental_patients: float
    incremental_revenue: float
    incremental_cost: float
    incremental_profit: float
    incremental_roi: float
    cost_per_incremental_patient: float

@dataclass
class AdAgencyResult:
    """Results for ad-agency comparison."""
    budget: float
    roas: float
    revenue: float
    net_profit: float
    treated_patients: float  # Estimated

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def clamp(val: float, min_val: float, max_val: float) -> float:
    """Clamp value between min and max."""
    return max(min_val, min(val, max_val))

def fmt_money(val: float, decimals: int = 0) -> str:
    """Format as currency."""
    if abs(val) >= 1_000_000_000:
        return f"${val / 1_000_000_000:,.{decimals}f}B"
    elif abs(val) >= 1_000_000:
        return f"${val / 1_000_000:,.{decimals}f}M"
    elif abs(val) >= 1_000:
        return f"${val / 1_000:,.{decimals}f}K"
    return f"${val:,.{decimals}f}"

def fmt_number(val: float, decimals: int = 0) -> str:
    """Format as number with thousands separator."""
    if abs(val) >= 1_000_000:
        return f"{val / 1_000_000:,.{decimals}f}M"
    elif abs(val) >= 1_000:
        return f"{val / 1_000:,.{decimals}f}K"
    return f"{val:,.{decimals}f}"

def fmt_pct(val: float, decimals: int = 1) -> str:
    """Format as percentage."""
    return f"{val * 100:,.{decimals}f}%"

def fmt_roi(val: float) -> str:
    """Format ROI with appropriate suffix."""
    if val == float('inf') or val == float('-inf') or math.isnan(val):
        return "N/A"
    return f"{val:,.1f}x"

def fmt_delta(val: float) -> str:
    """Format with +/- prefix."""
    prefix = "+" if val >= 0 else ""
    return f"{prefix}{fmt_money(val)}"

def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safe division with default for zero denominator."""
    if denominator == 0:
        return default
    return numerator / denominator

def safe_log(val: float) -> float:
    """Safe log for chart scaling."""
    if val <= 0:
        return 0
    return math.log10(val + 1)

# =============================================================================
# COMPUTATION FUNCTIONS
# =============================================================================

def compute_funnel(
    base_population: float,
    ratios: List[float],
    stage_active: List[bool],
    stage_6_cac: float,
) -> Tuple[List[StageResult], float, float]:
    """
    Compute funnel metrics.
    
    CAC Logic:
    - Stages 1-5: No CAC (awareness/discovery stages)
    - Stage 6 (Aware of Dario): CAC pool is created here
    - Stages 7-13: CAC is distributed proportionally from the pool
    
    Returns: (stage_results, total_patients, total_cac)
    """
    stages = []
    patients = base_population
    cumulative_cac = 0.0
    cac_pool = 0.0
    stage_6_patients = 0.0
    
    for i in range(NUM_STAGES):
        ratio = ratios[i] if stage_active[i] else 0.0
        
        if i == 0:
            stage_patients = patients
        else:
            stage_patients = patients * ratio
        
        patients = stage_patients
        
        # CAC logic
        if i < 5:
            # Stages 1-5: No CAC
            cac_per_patient = 0.0
            stage_cac = 0.0
        elif i == 5:
            # Stage 6: CAC pool created
            stage_6_patients = stage_patients
            cac_pool = stage_6_cac * stage_patients if stage_patients > 0 else 0
            cac_per_patient = stage_6_cac
            stage_cac = cac_pool
            cumulative_cac = cac_pool
        else:
            # Stages 7+: No additional CAC, but track per-patient from pool
            if stage_patients > 0 and stage_6_patients > 0:
                cac_per_patient = cac_pool / stage_patients
            else:
                cac_per_patient = 0.0
            stage_cac = 0.0
        
        stages.append(StageResult(
            stage_num=i + 1,
            name=STAGE_NAMES[i],
            active=stage_active[i],
            ratio=ratio,
            patients=stage_patients,
            cac_per_patient=cac_per_patient,
            stage_cac=stage_cac,
            cumulative_cac=cumulative_cac,
        ))
    
    final_patients = stages[-1].patients if stages else 0
    return stages, final_patients, cumulative_cac

def compute_financials(
    treated_patients: float,
    arpp: float,
    treatment_years: float,
    discount: float,
    total_cac: float,
    platform_costs: Dict[str, float],
) -> Tuple[float, float, float, float, float]:
    """
    Compute financial metrics.
    
    Returns: (gross_revenue, net_revenue, platform_cost_total, total_cost, net_profit)
    """
    gross_revenue = treated_patients * arpp * treatment_years
    net_revenue = gross_revenue * (1 - discount)
    platform_cost_total = sum(platform_costs.values())
    total_cost = total_cac + platform_cost_total
    net_profit = net_revenue - total_cost
    
    return gross_revenue, net_revenue, platform_cost_total, total_cost, net_profit

def run_scenario(
    model: Dict[str, Any],
    scenario_key: str,  # "baseline" or "dario"
) -> ScenarioResult:
    """Run a complete scenario calculation."""
    shared = model.get("shared", {})
    scenario = model.get(scenario_key, {})
    
    base_pop = shared.get("base_population", 0)
    ratios = scenario.get("ratios", [1.0] + [0.0] * (NUM_STAGES - 1))
    stage_active = scenario.get("stage_active", [True] * NUM_STAGES)
    stage_6_cac = scenario.get("stage_6_cac", 0)
    
    # Compute funnel
    stages, treated_patients, total_cac = compute_funnel(
        base_pop, ratios, stage_active, stage_6_cac
    )
    
    # Compute financials
    arpp = scenario.get("arpp", 0)
    treatment_years = scenario.get("treatment_years", 0)
    discount = scenario.get("discount", 0)
    platform_costs = scenario.get("platform_costs", {})
    
    gross_rev, net_rev, plat_cost, total_cost, net_profit = compute_financials(
        treated_patients, arpp, treatment_years, discount, total_cac, platform_costs
    )
    
    roi = safe_divide(net_profit, total_cost, 0.0)
    
    return ScenarioResult(
        stages=stages,
        treated_patients=treated_patients,
        gross_revenue=gross_rev,
        net_revenue=net_rev,
        total_cac=total_cac,
        platform_costs=plat_cost,
        total_cost=total_cost,
        net_profit=net_profit,
        roi=roi,
    )

def compute_incremental(
    baseline: ScenarioResult,
    dario: ScenarioResult,
) -> IncrementalResult:
    """Compute incremental metrics between baseline and Dario."""
    incr_patients = dario.treated_patients - baseline.treated_patients
    incr_revenue = dario.net_revenue - baseline.net_revenue
    incr_cost = dario.total_cost - baseline.total_cost
    incr_profit = dario.net_profit - baseline.net_profit
    
    # Incremental ROI: profit gained per dollar of additional cost
    incr_roi = safe_divide(incr_profit, incr_cost, 0.0) if incr_cost > 0 else float('inf') if incr_profit > 0 else 0.0
    
    cost_per_patient = safe_divide(incr_cost, incr_patients, 0.0)
    
    return IncrementalResult(
        incremental_patients=incr_patients,
        incremental_revenue=incr_revenue,
        incremental_cost=incr_cost,
        incremental_profit=incr_profit,
        incremental_roi=incr_roi,
        cost_per_incremental_patient=cost_per_patient,
    )

def compute_ad_agency(
    model: Dict[str, Any],
    arpp: float,
    treatment_years: float,
    discount: float,
) -> Optional[AdAgencyResult]:
    """Compute ad-agency comparison metrics."""
    ad_config = model.get("ad_agency_comparison", {})
    if not ad_config.get("enabled", False):
        return None
    
    budget = ad_config.get("budget", 0)
    roas = ad_config.get("roas", 1.35)
    
    revenue = budget * roas
    net_profit = revenue - budget
    
    # Estimate treated patients based on revenue
    patient_ltv = arpp * treatment_years * (1 - discount)
    treated_patients = safe_divide(revenue, patient_ltv, 0)
    
    return AdAgencyResult(
        budget=budget,
        roas=roas,
        revenue=revenue,
        net_profit=net_profit,
        treated_patients=treated_patients,
    )

def compute_cac_sensitivity(
    model: Dict[str, Any],
    scenario_key: str,
) -> List[Dict[str, float]]:
    """Compute sensitivity analysis for Stage 6 CAC."""
    scenario = model.get(scenario_key, {})
    sensitivity = scenario.get("cac_sensitivity", {})
    
    cac_min = sensitivity.get("min", 0)
    cac_max = sensitivity.get("max", 0)
    cac_step = sensitivity.get("step", 100)
    
    if cac_step <= 0 or cac_max <= cac_min:
        return []
    
    results = []
    current_cac = cac_min
    
    while current_cac <= cac_max:
        # Create a modified model with the test CAC
        test_model = copy.deepcopy(model)
        test_model[scenario_key]["stage_6_cac"] = current_cac
        
        # Run both scenarios
        baseline = run_scenario(test_model, "baseline")
        dario = run_scenario(test_model, "dario")
        incr = compute_incremental(baseline, dario)
        
        results.append({
            "stage_6_cac": current_cac,
            "baseline_roi": baseline.roi,
            "dario_roi": dario.roi,
            "incremental_roi": incr.incremental_roi,
            "incremental_profit": incr.incremental_profit,
            "dario_profit": dario.net_profit,
        })
        
        current_cac += cac_step
    
    return results

def compute_breakeven_cac(
    model: Dict[str, Any],
    scenario_key: str,
    target_roi: float = 0.0,
) -> Optional[float]:
    """Find the CAC at which ROI equals target (default: break-even at 0 ROI)."""
    # Binary search for break-even CAC
    low = 0
    high = 10000
    tolerance = 1
    max_iterations = 50
    
    for _ in range(max_iterations):
        mid = (low + high) / 2
        test_model = copy.deepcopy(model)
        test_model[scenario_key]["stage_6_cac"] = mid
        
        result = run_scenario(test_model, scenario_key)
        
        if abs(result.roi - target_roi) < 0.01:
            return mid
        elif result.roi > target_roi:
            low = mid
        else:
            high = mid
        
        if high - low < tolerance:
            break
    
    return (low + high) / 2

def run_full_model(model: Dict[str, Any]) -> Dict[str, Any]:
    """Run complete model analysis."""
    baseline = run_scenario(model, "baseline")
    dario = run_scenario(model, "dario")
    incremental = compute_incremental(baseline, dario)
    
    # Ad-agency comparison
    dario_scenario = model.get("dario", {})
    ad_agency = compute_ad_agency(
        model,
        dario_scenario.get("arpp", 85000),
        dario_scenario.get("treatment_years", 3),
        dario_scenario.get("discount", 0.7),
    )
    
    # Breakeven analysis
    breakeven_cac = compute_breakeven_cac(model, "dario", 0.0)
    
    return {
        "baseline": baseline,
        "dario": dario,
        "incremental": incremental,
        "ad_agency": ad_agency,
        "breakeven_cac": breakeven_cac,
    }

# =============================================================================
# TIMELINE MODE FUNCTIONS
# =============================================================================

def compute_timeline_profit(models: List[Dict[str, Any]], model_names: List[str]) -> pd.DataFrame:
    """
    Compute cumulative profit over time for timeline mode.
    Maps up to 4 models to: Launch, Opt1, Opt2, Steady State
    """
    if len(models) < 2:
        return pd.DataFrame()
    
    # Map available models to periods
    num_models = min(len(models), 4)
    data_rows = []
    cumulative_profit = 0.0
    month = 0
    
    for i in range(num_models):
        model = models[i]
        model_name = model_names[i]
        period = TIMELINE_PERIODS[i]
        
        # Run the model
        results = run_full_model(model)
        dario = results["dario"]
        
        # Monthly profit rate (annualize the figures)
        annual_profit = dario.net_profit
        monthly_profit = annual_profit / 12
        
        # Generate monthly data points for this period
        for m in range(period["months"]):
            month += 1
            cumulative_profit += monthly_profit
            data_rows.append({
                "Month": month,
                "Period": period["name"],
                "Model": model_name,
                "Monthly Profit": monthly_profit,
                "Cumulative Profit": cumulative_profit,
                "Color": period["color"],
            })
    
    return pd.DataFrame(data_rows)

def compute_baseline_overlay(models: List[Dict[str, Any]], timeline_df: pd.DataFrame) -> pd.DataFrame:
    """Compute baseline cumulative profit for overlay."""
    if timeline_df.empty or len(models) < 1:
        return pd.DataFrame()
    
    # Use first model's baseline as reference
    baseline = run_scenario(models[0], "baseline")
    monthly_baseline_profit = baseline.net_profit / 12
    
    max_month = timeline_df["Month"].max()
    
    data_rows = []
    cumulative = 0.0
    for m in range(1, int(max_month) + 1):
        cumulative += monthly_baseline_profit
        data_rows.append({
            "Month": m,
            "Cumulative Profit": cumulative,
            "Type": "Baseline",
        })
    
    return pd.DataFrame(data_rows)

# =============================================================================
# EXPORT FUNCTIONS
# =============================================================================

def create_excel_report(model: Dict[str, Any], model_name: str, results: Dict[str, Any]) -> bytes:
    """Create comprehensive Excel report."""
    buffer = io.BytesIO()
    
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        # Summary sheet
        baseline = results["baseline"]
        dario = results["dario"]
        incr = results["incremental"]
        
        summary_data = {
            "Metric": [
                "Model Name",
                "Base Population",
                "",
                "=== BASELINE ===",
                "Treated Patients",
                "Gross Revenue",
                "Net Revenue",
                "Total Cost",
                "Net Profit",
                "ROI",
                "",
                "=== DARIO ===",
                "Treated Patients",
                "Gross Revenue",
                "Net Revenue",
                "Total Cost",
                "Net Profit",
                "ROI",
                "",
                "=== INCREMENTAL ===",
                "Additional Patients",
                "Additional Revenue",
                "Additional Cost",
                "Additional Profit",
                "Incremental ROI",
            ],
            "Value": [
                model_name,
                model.get("shared", {}).get("base_population", 0),
                "",
                "",
                baseline.treated_patients,
                baseline.gross_revenue,
                baseline.net_revenue,
                baseline.total_cost,
                baseline.net_profit,
                baseline.roi,
                "",
                "",
                dario.treated_patients,
                dario.gross_revenue,
                dario.net_revenue,
                dario.total_cost,
                dario.net_profit,
                dario.roi,
                "",
                "",
                incr.incremental_patients,
                incr.incremental_revenue,
                incr.incremental_cost,
                incr.incremental_profit,
                incr.incremental_roi,
            ],
        }
        pd.DataFrame(summary_data).to_excel(writer, sheet_name="Summary", index=False)
        
        # Baseline Funnel
        baseline_funnel = []
        for s in baseline.stages:
            baseline_funnel.append({
                "Stage": s.stage_num,
                "Name": s.name,
                "Active": s.active,
                "Ratio": s.ratio,
                "Patients": s.patients,
                "CAC/Patient": s.cac_per_patient,
                "Stage CAC": s.stage_cac,
                "Cumulative CAC": s.cumulative_cac,
            })
        pd.DataFrame(baseline_funnel).to_excel(writer, sheet_name="Baseline Funnel", index=False)
        
        # Dario Funnel
        dario_funnel = []
        for s in dario.stages:
            dario_funnel.append({
                "Stage": s.stage_num,
                "Name": s.name,
                "Active": s.active,
                "Ratio": s.ratio,
                "Patients": s.patients,
                "CAC/Patient": s.cac_per_patient,
                "Stage CAC": s.stage_cac,
                "Cumulative CAC": s.cumulative_cac,
            })
        pd.DataFrame(dario_funnel).to_excel(writer, sheet_name="Dario Funnel", index=False)
        
        # Ad-Agency comparison if enabled
        if results.get("ad_agency"):
            ad = results["ad_agency"]
            ad_data = {
                "Metric": ["Budget", "ROAS", "Revenue", "Net Profit", "Est. Patients"],
                "Value": [ad.budget, ad.roas, ad.revenue, ad.net_profit, ad.treated_patients],
            }
            pd.DataFrame(ad_data).to_excel(writer, sheet_name="Ad Agency", index=False)
    
    buffer.seek(0)
    return buffer.getvalue()

def model_to_json(model: Dict[str, Any], model_name: str) -> str:
    """Export model configuration to JSON."""
    export = {
        "name": model_name,
        "version": APP_VERSION,
        "config": model,
    }
    return json.dumps(export, indent=2)

# =============================================================================
# SESSION STATE INITIALIZATION
# =============================================================================

def init_session_state():
    """Initialize session state with defaults."""
    if "models" not in st.session_state:
        # Start with Dario Launch preset
        st.session_state["models"] = [copy.deepcopy(DARIO_LAUNCH)]
        st.session_state["model_names"] = ["Model 1"]
    
    if "active_model_idx" not in st.session_state:
        st.session_state["active_model_idx"] = 0
    
    if "model_colors" not in st.session_state:
        st.session_state["model_colors"] = {}
    
    if "confirm_delete" not in st.session_state:
        st.session_state["confirm_delete"] = False
    
    if "show_import_dialog" not in st.session_state:
        st.session_state["show_import_dialog"] = False

def migrate_old_model(model: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate old single-scenario model to new structure."""
    if "shared" in model and "baseline" in model and "dario" in model:
        return model  # Already new format
    
    # Create new structure from old
    return copy.deepcopy(DARIO_LAUNCH)

# =============================================================================
# STREAMLIT APP
# =============================================================================

def main():
    st.set_page_config(
        page_title="PharmaROI Intelligence Platform",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    
    init_session_state()
    
    # Header
    st.title("📊 PharmaROI Intelligence Platform")
    st.caption(f"Version {APP_VERSION} | Multi-Model Analysis with Timeline & Agency Comparison")
    
    # =========================================================================
    # MODEL MANAGEMENT BAR
    # =========================================================================
    st.markdown("---")
    
    mgmt_col1, mgmt_col2, mgmt_col3, mgmt_col4, mgmt_col5 = st.columns([2, 2, 2, 2, 2])
    
    with mgmt_col1:
        if st.button("Add New Model", use_container_width=True):
            new_model = copy.deepcopy(DARIO_LAUNCH)
            new_name = f"Model {len(st.session_state['models']) + 1}"
            st.session_state["models"].append(new_model)
            st.session_state["model_names"].append(new_name)
            st.session_state["active_model_idx"] = len(st.session_state["models"]) - 1
            st.rerun()
    
    with mgmt_col2:
        # Copy From dropdown
        copy_options = st.session_state["model_names"]
        if len(copy_options) > 0:
            copy_source = st.selectbox(
                "Copy from:",
                options=range(len(copy_options)),
                format_func=lambda i: copy_options[i],
                index=st.session_state["active_model_idx"],
                key="copy_source_select",
                label_visibility="collapsed",
            )
            if st.button("Copy This Model", use_container_width=True):
                source_idx = copy_source
                new_model = copy.deepcopy(st.session_state["models"][source_idx])
                new_name = st.session_state["model_names"][source_idx] + " (copy)"
                st.session_state["models"].append(new_model)
                st.session_state["model_names"].append(new_name)
                st.session_state["active_model_idx"] = len(st.session_state["models"]) - 1
                st.rerun()
    
    with mgmt_col3:
        # Delete with confirmation
        if len(st.session_state["models"]) > 1:
            if not st.session_state.get("confirm_delete", False):
                if st.button("Delete Current", use_container_width=True):
                    st.session_state["confirm_delete"] = True
                    st.rerun()
            else:
                st.warning(f"Delete '{st.session_state['model_names'][st.session_state['active_model_idx']]}'?")
                del_col1, del_col2 = st.columns(2)
                with del_col1:
                    if st.button("Yes, Delete", use_container_width=True):
                        idx = st.session_state["active_model_idx"]
                        st.session_state["models"].pop(idx)
                        st.session_state["model_names"].pop(idx)
                        st.session_state["active_model_idx"] = max(0, idx - 1)
                        st.session_state["confirm_delete"] = False
                        st.rerun()
                with del_col2:
                    if st.button("Cancel", use_container_width=True):
                        st.session_state["confirm_delete"] = False
                        st.rerun()
    
    with mgmt_col4:
        # Rename
        current_idx = st.session_state["active_model_idx"]
        new_name = st.text_input(
            "Rename:",
            value=st.session_state["model_names"][current_idx],
            key="model_rename_input",
            label_visibility="collapsed",
        )
        if new_name != st.session_state["model_names"][current_idx]:
            st.session_state["model_names"][current_idx] = new_name
    
    with mgmt_col5:
        # Load preset
        preset_choice = st.selectbox(
            "Load Preset:",
            options=list(MODEL_PRESETS.keys()),
            key="preset_select",
            label_visibility="collapsed",
        )
        if st.button("Apply Preset", use_container_width=True):
            st.session_state["models"][st.session_state["active_model_idx"]] = copy.deepcopy(MODEL_PRESETS[preset_choice])
            st.rerun()
    
    # Model reordering
    if len(st.session_state["models"]) > 1:
        reorder_col1, reorder_col2, reorder_spacer = st.columns([1, 1, 8])
        idx = st.session_state["active_model_idx"]
        
        with reorder_col1:
            if st.button("Move Left", disabled=(idx == 0), use_container_width=True):
                st.session_state["models"][idx], st.session_state["models"][idx-1] = \
                    st.session_state["models"][idx-1], st.session_state["models"][idx]
                st.session_state["model_names"][idx], st.session_state["model_names"][idx-1] = \
                    st.session_state["model_names"][idx-1], st.session_state["model_names"][idx]
                st.session_state["active_model_idx"] = idx - 1
                st.rerun()
        
        with reorder_col2:
            if st.button("Move Right", disabled=(idx >= len(st.session_state["models"]) - 1), use_container_width=True):
                st.session_state["models"][idx], st.session_state["models"][idx+1] = \
                    st.session_state["models"][idx+1], st.session_state["models"][idx]
                st.session_state["model_names"][idx], st.session_state["model_names"][idx+1] = \
                    st.session_state["model_names"][idx+1], st.session_state["model_names"][idx]
                st.session_state["active_model_idx"] = idx + 1
                st.rerun()
    
    # =========================================================================
    # MODEL TABS
    # =========================================================================
    
    tab_names = st.session_state["model_names"] + ["📊 Comparison"]
    tabs = st.tabs(tab_names)
    
    # Individual model tabs
    for model_idx, model_tab in enumerate(tabs[:-1]):
        with model_tab:
            st.session_state["active_model_idx"] = model_idx
            model = st.session_state["models"][model_idx]
            
            # Ensure model has all required keys
            if "shared" not in model:
                model["shared"] = copy.deepcopy(DARIO_LAUNCH["shared"])
            if "baseline" not in model:
                model["baseline"] = copy.deepcopy(DARIO_LAUNCH["baseline"])
            if "dario" not in model:
                model["dario"] = copy.deepcopy(DARIO_LAUNCH["dario"])
            if "ad_agency_comparison" not in model:
                model["ad_agency_comparison"] = copy.deepcopy(DARIO_LAUNCH["ad_agency_comparison"])
            
            shared = model["shared"]
            baseline_cfg = model["baseline"]
            dario_cfg = model["dario"]
            ad_agency_cfg = model["ad_agency_comparison"]
            
            # -----------------------------------------------------------------
            # SHARED SETTINGS
            # -----------------------------------------------------------------
            with st.expander("🔧 Shared Model Settings", expanded=False):
                sh_col1, sh_col2 = st.columns(2)
                
                with sh_col1:
                    shared["base_population"] = st.number_input(
                        "Base Population (TAM)",
                        min_value=0,
                        value=int(shared.get("base_population", 30_000_000)),
                        step=1_000_000,
                        key=f"base_pop_{model_idx}",
                        help="Total addressable market size",
                    )
                
                with sh_col2:
                    shared["use_timeline_mode"] = st.checkbox(
                        "Enable Timeline Mode (for Comparison tab)",
                        value=shared.get("use_timeline_mode", False),
                        key=f"timeline_mode_{model_idx}",
                        help="When enabled, models map to: Launch → Opt1 → Opt2 → Steady State",
                    )
                
                st.markdown("**Customize Stage Names:**")
                stage_cols = st.columns(3)
                if "stage_names" not in shared:
                    shared["stage_names"] = STAGE_NAMES.copy()
                
                for i, stage_name in enumerate(shared["stage_names"]):
                    with stage_cols[i % 3]:
                        shared["stage_names"][i] = st.text_input(
                            f"Stage {i+1}",
                            value=stage_name,
                            key=f"stage_name_{model_idx}_{i}",
                            label_visibility="visible",
                        )
                
                reset_col1, reset_col2 = st.columns(2)
                with reset_col1:
                    if st.button("Reset to Defaults", key=f"reset_defaults_{model_idx}", use_container_width=True):
                        st.session_state["models"][model_idx] = copy.deepcopy(DARIO_LAUNCH)
                        st.rerun()
                with reset_col2:
                    if st.button("Clear All (Zero)", key=f"reset_zero_{model_idx}", use_container_width=True):
                        st.session_state["models"][model_idx] = copy.deepcopy(ZERO_MODEL)
                        st.rerun()
            
            # -----------------------------------------------------------------
            # TWO-COLUMN LAYOUT: BASELINE | DARIO
            # -----------------------------------------------------------------
            scenario_col1, scenario_col2 = st.columns(2)
            
            # === BASELINE SCENARIO ===
            with scenario_col1:
                st.subheader("📋 Baseline Scenario")
                st.caption("Traditional approach without Dario platform")
                
                # Revenue inputs
                with st.expander("Revenue Settings", expanded=True):
                    baseline_cfg["arpp"] = st.number_input(
                        "ARPP (Annual Revenue Per Patient)",
                        min_value=0,
                        value=int(baseline_cfg.get("arpp", 85_000)),
                        step=5_000,
                        key=f"baseline_arpp_{model_idx}",
                        format="%d",
                    )
                    baseline_cfg["treatment_years"] = st.number_input(
                        "Treatment Years",
                        min_value=0.0,
                        max_value=20.0,
                        value=float(baseline_cfg.get("treatment_years", 2.5)),
                        step=0.5,
                        key=f"baseline_years_{model_idx}",
                    )
                    baseline_cfg["discount"] = st.slider(
                        "Gross-to-Net Discount",
                        min_value=0.0,
                        max_value=1.0,
                        value=float(baseline_cfg.get("discount", 0.70)),
                        step=0.05,
                        key=f"baseline_discount_{model_idx}",
                        format="%.0f%%",
                    )
                
                # CAC configuration
                with st.expander("CAC Configuration", expanded=True):
                    baseline_cfg["cac_mode"] = st.radio(
                        "CAC Input Mode",
                        options=["direct", "sensitivity"],
                        index=0 if baseline_cfg.get("cac_mode", "direct") == "direct" else 1,
                        key=f"baseline_cac_mode_{model_idx}",
                        horizontal=True,
                    )
                    
                    # Stage 6 warning
                    st.info("⚠️ **Stage 6 CAC Note:** The conversion ratio at Stage 6 is typically expressed as an *annual* rate. If your scenario duration differs, adjust expectations accordingly.")
                    
                    if baseline_cfg["cac_mode"] == "direct":
                        baseline_cfg["stage_6_cac"] = st.number_input(
                            "Stage 6 CAC (per patient)",
                            min_value=0,
                            value=int(baseline_cfg.get("stage_6_cac", 1000)),
                            step=50,
                            key=f"baseline_cac_direct_{model_idx}",
                            help="Customer Acquisition Cost at the 'Aware of Dario' stage",
                        )
                    else:
                        sens = baseline_cfg.get("cac_sensitivity", {"min": 500, "max": 2000, "step": 100, "base": 1000})
                        sens_col1, sens_col2 = st.columns(2)
                        with sens_col1:
                            sens["min"] = st.number_input("Min CAC", min_value=0, value=int(sens.get("min", 500)), step=50, key=f"baseline_sens_min_{model_idx}")
                            sens["step"] = st.number_input("Step", min_value=10, value=int(sens.get("step", 100)), step=10, key=f"baseline_sens_step_{model_idx}")
                        with sens_col2:
                            sens["max"] = st.number_input("Max CAC", min_value=0, value=int(sens.get("max", 2000)), step=50, key=f"baseline_sens_max_{model_idx}")
                            sens["base"] = st.number_input("Base CAC", min_value=0, value=int(sens.get("base", 1000)), step=50, key=f"baseline_sens_base_{model_idx}")
                        baseline_cfg["cac_sensitivity"] = sens
                        baseline_cfg["stage_6_cac"] = sens["base"]
                
                # Funnel stages
                with st.expander("Funnel Stage Ratios", expanded=False):
                    st.caption("Conversion rates between stages (Stage 1 is always 100%)")
                    
                    if "ratios" not in baseline_cfg:
                        baseline_cfg["ratios"] = create_default_ratios()
                    if "stage_active" not in baseline_cfg:
                        baseline_cfg["stage_active"] = [True] * NUM_STAGES
                    
                    for i in range(NUM_STAGES):
                        stage_name = shared["stage_names"][i] if i < len(shared["stage_names"]) else STAGE_NAMES[i]
                        
                        st_col1, st_col2, st_col3 = st.columns([1, 3, 1])
                        
                        with st_col1:
                            baseline_cfg["stage_active"][i] = st.checkbox(
                                f"S{i+1}",
                                value=baseline_cfg["stage_active"][i],
                                key=f"baseline_active_{model_idx}_{i}",
                            )
                        
                        with st_col2:
                            if i == 0:
                                st.text(f"Stage 1: {stage_name[:30]}... (100%)")
                            else:
                                baseline_cfg["ratios"][i] = st.slider(
                                    f"Stage {i+1}: {stage_name[:25]}...",
                                    min_value=0.0,
                                    max_value=1.0,
                                    value=float(baseline_cfg["ratios"][i]),
                                    step=0.01,
                                    key=f"baseline_ratio_{model_idx}_{i}",
                                    disabled=not baseline_cfg["stage_active"][i],
                                    format="%.0f%%",
                                )
                        
                        with st_col3:
                            if i >= 6:
                                st.caption("(CAC derived)")
                
                # Platform costs (baseline typically has traditional marketing)
                with st.expander("Platform / Marketing Costs", expanded=False):
                    if "platform_costs" not in baseline_cfg:
                        baseline_cfg["platform_costs"] = {
                            "dario_connect_config": 0,
                            "dario_care_config": 0,
                            "sub_dario_connect": 0,
                            "sub_dario_care": 0,
                            "maintenance_support": 0,
                        }
                    
                    pc = baseline_cfg["platform_costs"]
                    pc["dario_connect_config"] = st.number_input("Marketing Config Cost", min_value=0, value=int(pc.get("dario_connect_config", 0)), step=10000, key=f"baseline_pc1_{model_idx}")
                    pc["dario_care_config"] = st.number_input("Support Config Cost", min_value=0, value=int(pc.get("dario_care_config", 0)), step=10000, key=f"baseline_pc2_{model_idx}")
                    pc["sub_dario_connect"] = st.number_input("Platform Subscription 1", min_value=0, value=int(pc.get("sub_dario_connect", 0)), step=10000, key=f"baseline_pc3_{model_idx}")
                    pc["sub_dario_care"] = st.number_input("Platform Subscription 2", min_value=0, value=int(pc.get("sub_dario_care", 0)), step=10000, key=f"baseline_pc4_{model_idx}")
                    pc["maintenance_support"] = st.number_input("Maintenance & Support", min_value=0, value=int(pc.get("maintenance_support", 0)), step=10000, key=f"baseline_pc5_{model_idx}")
                    
                    st.caption(f"**Total Platform Costs:** {fmt_money(sum(pc.values()))}")
            
            # === DARIO SCENARIO ===
            with scenario_col2:
                st.subheader("🚀 Dario Scenario")
                st.caption("Enhanced approach with Dario platform")
                
                # Revenue inputs
                with st.expander("Revenue Settings", expanded=True):
                    dario_cfg["arpp"] = st.number_input(
                        "ARPP (Annual Revenue Per Patient)",
                        min_value=0,
                        value=int(dario_cfg.get("arpp", 85_000)),
                        step=5_000,
                        key=f"dario_arpp_{model_idx}",
                        format="%d",
                    )
                    dario_cfg["treatment_years"] = st.number_input(
                        "Treatment Years",
                        min_value=0.0,
                        max_value=20.0,
                        value=float(dario_cfg.get("treatment_years", 3.0)),
                        step=0.5,
                        key=f"dario_years_{model_idx}",
                    )
                    dario_cfg["discount"] = st.slider(
                        "Gross-to-Net Discount",
                        min_value=0.0,
                        max_value=1.0,
                        value=float(dario_cfg.get("discount", 0.70)),
                        step=0.05,
                        key=f"dario_discount_{model_idx}",
                        format="%.0f%%",
                    )
                
                # CAC configuration
                with st.expander("CAC Configuration", expanded=True):
                    dario_cfg["cac_mode"] = st.radio(
                        "CAC Input Mode",
                        options=["direct", "sensitivity"],
                        index=0 if dario_cfg.get("cac_mode", "direct") == "direct" else 1,
                        key=f"dario_cac_mode_{model_idx}",
                        horizontal=True,
                    )
                    
                    st.info("⚠️ **Stage 6 CAC Note:** The conversion ratio at Stage 6 is typically expressed as an *annual* rate.")
                    
                    if dario_cfg["cac_mode"] == "direct":
                        dario_cfg["stage_6_cac"] = st.number_input(
                            "Stage 6 CAC (per patient)",
                            min_value=0,
                            value=int(dario_cfg.get("stage_6_cac", 650)),
                            step=50,
                            key=f"dario_cac_direct_{model_idx}",
                        )
                    else:
                        sens = dario_cfg.get("cac_sensitivity", {"min": 300, "max": 1500, "step": 100, "base": 650})
                        sens_col1, sens_col2 = st.columns(2)
                        with sens_col1:
                            sens["min"] = st.number_input("Min CAC", min_value=0, value=int(sens.get("min", 300)), step=50, key=f"dario_sens_min_{model_idx}")
                            sens["step"] = st.number_input("Step", min_value=10, value=int(sens.get("step", 100)), step=10, key=f"dario_sens_step_{model_idx}")
                        with sens_col2:
                            sens["max"] = st.number_input("Max CAC", min_value=0, value=int(sens.get("max", 1500)), step=50, key=f"dario_sens_max_{model_idx}")
                            sens["base"] = st.number_input("Base CAC", min_value=0, value=int(sens.get("base", 650)), step=50, key=f"dario_sens_base_{model_idx}")
                        dario_cfg["cac_sensitivity"] = sens
                        dario_cfg["stage_6_cac"] = sens["base"]
                
                # Funnel stages
                with st.expander("Funnel Stage Ratios", expanded=False):
                    st.caption("Conversion rates between stages")
                    
                    if "ratios" not in dario_cfg:
                        dario_cfg["ratios"] = create_default_ratios()
                    if "stage_active" not in dario_cfg:
                        dario_cfg["stage_active"] = [True] * NUM_STAGES
                    
                    for i in range(NUM_STAGES):
                        stage_name = shared["stage_names"][i] if i < len(shared["stage_names"]) else STAGE_NAMES[i]
                        
                        st_col1, st_col2, st_col3 = st.columns([1, 3, 1])
                        
                        with st_col1:
                            dario_cfg["stage_active"][i] = st.checkbox(
                                f"S{i+1}",
                                value=dario_cfg["stage_active"][i],
                                key=f"dario_active_{model_idx}_{i}",
                            )
                        
                        with st_col2:
                            if i == 0:
                                st.text(f"Stage 1: {stage_name[:30]}... (100%)")
                            else:
                                dario_cfg["ratios"][i] = st.slider(
                                    f"Stage {i+1}: {stage_name[:25]}...",
                                    min_value=0.0,
                                    max_value=1.0,
                                    value=float(dario_cfg["ratios"][i]),
                                    step=0.01,
                                    key=f"dario_ratio_{model_idx}_{i}",
                                    disabled=not dario_cfg["stage_active"][i],
                                    format="%.0f%%",
                                )
                        
                        with st_col3:
                            if i >= 6:
                                st.caption("(CAC derived)")
                
                # Platform costs (Dario)
                with st.expander("Platform Costs (Dario)", expanded=False):
                    if "platform_costs" not in dario_cfg:
                        dario_cfg["platform_costs"] = {
                            "dario_connect_config": 180_000,
                            "dario_care_config": 120_000,
                            "sub_dario_connect": 96_000,
                            "sub_dario_care": 72_000,
                            "maintenance_support": 50_000,
                        }
                    
                    pc = dario_cfg["platform_costs"]
                    pc["dario_connect_config"] = st.number_input("Dario Connect Config", min_value=0, value=int(pc.get("dario_connect_config", 180000)), step=10000, key=f"dario_pc1_{model_idx}")
                    pc["dario_care_config"] = st.number_input("Dario Care Config", min_value=0, value=int(pc.get("dario_care_config", 120000)), step=10000, key=f"dario_pc2_{model_idx}")
                    pc["sub_dario_connect"] = st.number_input("Sub: Dario Connect", min_value=0, value=int(pc.get("sub_dario_connect", 96000)), step=10000, key=f"dario_pc3_{model_idx}")
                    pc["sub_dario_care"] = st.number_input("Sub: Dario Care", min_value=0, value=int(pc.get("sub_dario_care", 72000)), step=10000, key=f"dario_pc4_{model_idx}")
                    pc["maintenance_support"] = st.number_input("Maintenance & Support", min_value=0, value=int(pc.get("maintenance_support", 50000)), step=10000, key=f"dario_pc5_{model_idx}")
                    
                    st.caption(f"**Total Platform Costs:** {fmt_money(sum(pc.values()))}")
            
            # -----------------------------------------------------------------
            # AD-AGENCY COMPARISON
            # -----------------------------------------------------------------
            with st.expander("📺 Ad-Agency Comparison (Optional)", expanded=False):
                ad_agency_cfg["enabled"] = st.checkbox(
                    "Enable Ad-Agency Comparison",
                    value=ad_agency_cfg.get("enabled", False),
                    key=f"ad_agency_enabled_{model_idx}",
                    help="Compare Dario results against traditional digital advertising",
                )
                
                if ad_agency_cfg["enabled"]:
                    st.caption("Traditional pharma digital advertising typically achieves 1.2x-1.5x ROAS")
                    
                    ad_col1, ad_col2 = st.columns(2)
                    with ad_col1:
                        ad_agency_cfg["budget"] = st.number_input(
                            "Ad Spend Budget",
                            min_value=0,
                            value=int(ad_agency_cfg.get("budget", 500_000)),
                            step=50_000,
                            key=f"ad_budget_{model_idx}",
                        )
                    with ad_col2:
                        ad_agency_cfg["roas"] = st.number_input(
                            "Expected ROAS (default: 1.35x)",
                            min_value=0.0,
                            max_value=10.0,
                            value=float(ad_agency_cfg.get("roas", 1.35)),
                            step=0.05,
                            key=f"ad_roas_{model_idx}",
                            help="Return on Ad Spend (typical pharma: 1.2-1.5x)",
                        )
            
            # -----------------------------------------------------------------
            # RUN CALCULATIONS
            # -----------------------------------------------------------------
            st.markdown("---")
            results = run_full_model(model)
            baseline_res = results["baseline"]
            dario_res = results["dario"]
            incr_res = results["incremental"]
            ad_agency_res = results.get("ad_agency")
            breakeven_cac = results.get("breakeven_cac")
            
            # -----------------------------------------------------------------
            # RESULTS SUMMARY
            # -----------------------------------------------------------------
            st.subheader("📈 Results Summary")
            
            # KPI Cards - Row 1: Patients & Revenue
            st.markdown("**Patients & Revenue**")
            kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
            
            with kpi_col1:
                st.metric(
                    "Baseline Patients",
                    fmt_number(baseline_res.treated_patients),
                    help="Patients completing the funnel in baseline scenario",
                )
            with kpi_col2:
                st.metric(
                    "Dario Patients",
                    fmt_number(dario_res.treated_patients),
                    delta=fmt_number(incr_res.incremental_patients),
                )
            with kpi_col3:
                st.metric(
                    "Baseline Net Revenue",
                    fmt_money(baseline_res.net_revenue),
                )
            with kpi_col4:
                st.metric(
                    "Dario Net Revenue",
                    fmt_money(dario_res.net_revenue),
                    delta=fmt_delta(incr_res.incremental_revenue),
                )
            
            # KPI Cards - Row 2: Costs & Profit
            st.markdown("**Costs & Profitability**")
            kpi_col5, kpi_col6, kpi_col7, kpi_col8 = st.columns(4)
            
            with kpi_col5:
                st.metric(
                    "Baseline Total Cost",
                    fmt_money(baseline_res.total_cost),
                )
            with kpi_col6:
                st.metric(
                    "Dario Total Cost",
                    fmt_money(dario_res.total_cost),
                    delta=fmt_delta(incr_res.incremental_cost),
                    delta_color="inverse",
                )
            with kpi_col7:
                st.metric(
                    "Baseline Net Profit",
                    fmt_money(baseline_res.net_profit),
                )
            with kpi_col8:
                profit_color = "normal" if incr_res.incremental_profit >= 0 else "inverse"
                st.metric(
                    "Dario Net Profit",
                    fmt_money(dario_res.net_profit),
                    delta=fmt_delta(incr_res.incremental_profit),
                )
            
            # KPI Cards - Row 3: ROI & Break-even
            st.markdown("**ROI & Break-even Analysis**")
            kpi_col9, kpi_col10, kpi_col11, kpi_col12 = st.columns(4)
            
            with kpi_col9:
                st.metric(
                    "Baseline ROI",
                    fmt_roi(baseline_res.roi),
                    help="Net Profit / Total Cost",
                )
            with kpi_col10:
                st.metric(
                    "Dario ROI",
                    fmt_roi(dario_res.roi),
                )
            with kpi_col11:
                st.metric(
                    "Incremental ROI",
                    fmt_roi(incr_res.incremental_roi),
                    help="Incremental Profit / Incremental Cost",
                )
            with kpi_col12:
                if breakeven_cac and breakeven_cac > 0:
                    current_cac = dario_cfg.get("stage_6_cac", 0)
                    headroom = breakeven_cac - current_cac
                    if headroom > 0:
                        st.metric(
                            "Break-even CAC",
                            fmt_money(breakeven_cac),
                            delta=f"+{fmt_money(headroom)} headroom",
                        )
                    else:
                        st.metric(
                            "Break-even CAC",
                            fmt_money(breakeven_cac),
                            delta=f"{fmt_money(headroom)} over",
                            delta_color="inverse",
                        )
                else:
                    st.metric("Break-even CAC", "N/A")
            
            # Ad-Agency Comparison Results
            if ad_agency_res:
                st.markdown("**Ad-Agency Comparison**")
                ad_col1, ad_col2, ad_col3, ad_col4 = st.columns(4)
                
                with ad_col1:
                    st.metric("Ad Spend", fmt_money(ad_agency_res.budget))
                with ad_col2:
                    st.metric("Ad Revenue (ROAS)", fmt_money(ad_agency_res.revenue))
                with ad_col3:
                    st.metric("Ad Net Profit", fmt_money(ad_agency_res.net_profit))
                with ad_col4:
                    dario_vs_ad = dario_res.net_profit - ad_agency_res.net_profit
                    st.metric(
                        "Dario vs Ad Advantage",
                        fmt_money(dario_vs_ad),
                        delta="Better" if dario_vs_ad > 0 else "Worse",
                        delta_color="normal" if dario_vs_ad > 0 else "inverse",
                    )
            
            # -----------------------------------------------------------------
            # FUNNEL TABLES
            # -----------------------------------------------------------------
            st.markdown("---")
            st.subheader("📊 Funnel Details")
            
            table_col1, table_col2 = st.columns(2)
            
            with table_col1:
                st.markdown("**Baseline Funnel**")
                baseline_df = pd.DataFrame([{
                    "Stage": s.stage_num,
                    "Name": s.name[:35] + ("..." if len(s.name) > 35 else ""),
                    "Active": "✓" if s.active else "✗",
                    "Ratio": fmt_pct(s.ratio),
                    "Patients": fmt_number(s.patients),
                    "CAC/Patient": fmt_money(s.cac_per_patient),
                    "Stage CAC": fmt_money(s.stage_cac),
                } for s in baseline_res.stages])
                st.dataframe(baseline_df, use_container_width=True, hide_index=True)
            
            with table_col2:
                st.markdown("**Dario Funnel**")
                dario_df = pd.DataFrame([{
                    "Stage": s.stage_num,
                    "Name": s.name[:35] + ("..." if len(s.name) > 35 else ""),
                    "Active": "✓" if s.active else "✗",
                    "Ratio": fmt_pct(s.ratio),
                    "Patients": fmt_number(s.patients),
                    "CAC/Patient": fmt_money(s.cac_per_patient),
                    "Stage CAC": fmt_money(s.stage_cac),
                } for s in dario_res.stages])
                st.dataframe(dario_df, use_container_width=True, hide_index=True)
            
            # -----------------------------------------------------------------
            # VISUALIZATIONS
            # -----------------------------------------------------------------
            st.markdown("---")
            st.subheader("📈 Visualizations")
            
            chart_col1, chart_col2 = st.columns(2)
            
            with chart_col1:
                st.markdown("**Key Metrics Comparison**")
                metrics_data = pd.DataFrame([
                    {"Metric": "Treated Patients", "Baseline": baseline_res.treated_patients, "Dario": dario_res.treated_patients},
                    {"Metric": "Net Revenue ($M)", "Baseline": baseline_res.net_revenue / 1_000_000, "Dario": dario_res.net_revenue / 1_000_000},
                    {"Metric": "Total Cost ($M)", "Baseline": baseline_res.total_cost / 1_000_000, "Dario": dario_res.total_cost / 1_000_000},
                    {"Metric": "Net Profit ($M)", "Baseline": baseline_res.net_profit / 1_000_000, "Dario": dario_res.net_profit / 1_000_000},
                ])
                
                metrics_melted = metrics_data.melt(id_vars=["Metric"], var_name="Scenario", value_name="Value")
                
                bar_chart = alt.Chart(metrics_melted).mark_bar().encode(
                    x=alt.X("Metric:N", axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y("Value:Q", title="Value"),
                    color=alt.Color("Scenario:N", scale=alt.Scale(
                        domain=["Baseline", "Dario"],
                        range=[COLORS["baseline"], COLORS["dario"]]
                    )),
                    xOffset="Scenario:N",
                    tooltip=["Metric", "Scenario", alt.Tooltip("Value:Q", format=",.2f")],
                ).properties(height=350)
                
                st.altair_chart(bar_chart, use_container_width=True)
            
            with chart_col2:
                st.markdown("**Funnel Patient Flow**")
                
                use_log = st.checkbox("Use log scale", value=False, key=f"log_scale_{model_idx}")
                
                funnel_data = []
                for s in baseline_res.stages:
                    val = safe_log(s.patients) if use_log else s.patients
                    funnel_data.append({
                        "Stage": f"S{s.stage_num}",
                        "Patients": val,
                        "Scenario": "Baseline",
                        "Actual": s.patients,
                    })
                for s in dario_res.stages:
                    val = safe_log(s.patients) if use_log else s.patients
                    funnel_data.append({
                        "Stage": f"S{s.stage_num}",
                        "Patients": val,
                        "Scenario": "Dario",
                        "Actual": s.patients,
                    })
                
                funnel_df = pd.DataFrame(funnel_data)
                
                funnel_chart = alt.Chart(funnel_df).mark_line(point=True).encode(
                    x=alt.X("Stage:N", sort=None),
                    y=alt.Y("Patients:Q", title="Patients" + (" (log)" if use_log else "")),
                    color=alt.Color("Scenario:N", scale=alt.Scale(
                        domain=["Baseline", "Dario"],
                        range=[COLORS["baseline"], COLORS["dario"]]
                    )),
                    tooltip=["Stage", "Scenario", alt.Tooltip("Actual:Q", format=",.0f", title="Patients")],
                ).properties(height=350)
                
                st.altair_chart(funnel_chart, use_container_width=True)
            
            # Sensitivity Analysis Chart (if enabled)
            if dario_cfg.get("cac_mode") == "sensitivity":
                st.markdown("---")
                st.markdown("**CAC Sensitivity Analysis**")
                
                sensitivity_data = compute_cac_sensitivity(model, "dario")
                
                if sensitivity_data:
                    sens_df = pd.DataFrame(sensitivity_data)
                    
                    sens_chart = alt.Chart(sens_df).mark_line(point=True, color=COLORS["dario"]).encode(
                        x=alt.X("stage_6_cac:Q", title="Stage 6 CAC ($)"),
                        y=alt.Y("dario_roi:Q", title="Dario ROI (x)"),
                        tooltip=[
                            alt.Tooltip("stage_6_cac:Q", title="CAC", format="$,.0f"),
                            alt.Tooltip("dario_roi:Q", title="ROI", format=".2f"),
                            alt.Tooltip("dario_profit:Q", title="Profit", format="$,.0f"),
                        ],
                    ).properties(height=300)
                    
                    # Add break-even line
                    breakeven_line = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
                        strokeDash=[5, 5],
                        color="red"
                    ).encode(y="y:Q")
                    
                    st.altair_chart(sens_chart + breakeven_line, use_container_width=True)
                    
                    with st.expander("Sensitivity Data Table"):
                        display_sens = sens_df.copy()
                        display_sens["stage_6_cac"] = display_sens["stage_6_cac"].apply(lambda x: fmt_money(x))
                        display_sens["dario_roi"] = display_sens["dario_roi"].apply(lambda x: fmt_roi(x))
                        display_sens["dario_profit"] = display_sens["dario_profit"].apply(lambda x: fmt_money(x))
                        st.dataframe(display_sens, use_container_width=True, hide_index=True)
            
            # -----------------------------------------------------------------
            # EXPORT SECTION
            # -----------------------------------------------------------------
            st.markdown("---")
            st.subheader("📥 Export")
            
            export_col1, export_col2 = st.columns(2)
            
            with export_col1:
                excel_data = create_excel_report(model, st.session_state["model_names"][model_idx], results)
                st.download_button(
                    label="Download Excel Report",
                    data=excel_data,
                    file_name=f"{st.session_state['model_names'][model_idx].replace(' ', '_')}_report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            
            with export_col2:
                json_data = model_to_json(model, st.session_state["model_names"][model_idx])
                st.download_button(
                    label="Download Model Config (JSON)",
                    data=json_data,
                    file_name=f"{st.session_state['model_names'][model_idx].replace(' ', '_')}_config.json",
                    mime="application/json",
                    use_container_width=True,
                )
    
    # =========================================================================
    # COMPARISON TAB
    # =========================================================================
    with tabs[-1]:
        st.subheader("📊 Model Comparison")
        
        if len(st.session_state["models"]) < 2:
            st.info("Add at least 2 models to compare them here.")
        else:
            # Model selection
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
            
            selected_indices = [i for i, name in enumerate(st.session_state["model_names"]) if name in selected_model_names]
            selected_models = [st.session_state["models"][i] for i in selected_indices]
            selected_names = [st.session_state["model_names"][i] for i in selected_indices]
            
            # Run all models
            all_results = []
            for m in selected_models:
                all_results.append(run_full_model(m))
            
            # Check if timeline mode is enabled (use first model's setting)
            use_timeline = selected_models[0].get("shared", {}).get("use_timeline_mode", False) if selected_models else False
            
            # -----------------------------------------------------------------
            # SECTION 1: Baseline vs Dario Within Each Model
            # -----------------------------------------------------------------
            st.markdown("---")
            st.markdown("### Baseline vs Dario (Per Model)")
            
            comparison_rows = []
            for name, res in zip(selected_names, all_results):
                baseline = res["baseline"]
                dario = res["dario"]
                incr = res["incremental"]
                comparison_rows.append({
                    "Model": name,
                    "Baseline Patients": baseline.treated_patients,
                    "Dario Patients": dario.treated_patients,
                    "Baseline Net Revenue": baseline.net_revenue,
                    "Dario Net Revenue": dario.net_revenue,
                    "Baseline Profit": baseline.net_profit,
                    "Dario Profit": dario.net_profit,
                    "Incremental Profit": incr.incremental_profit,
                    "Baseline ROI": baseline.roi,
                    "Dario ROI": dario.roi,
                })
            
            comp_df = pd.DataFrame(comparison_rows)
            
            # Format for display
            display_df = comp_df.copy()
            for col in ["Baseline Patients", "Dario Patients"]:
                display_df[col] = display_df[col].apply(lambda x: fmt_number(x))
            for col in ["Baseline Net Revenue", "Dario Net Revenue", "Baseline Profit", "Dario Profit", "Incremental Profit"]:
                display_df[col] = display_df[col].apply(lambda x: fmt_money(x))
            for col in ["Baseline ROI", "Dario ROI"]:
                display_df[col] = display_df[col].apply(lambda x: fmt_roi(x))
            
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            
            # Grouped bar chart: Baseline vs Dario patients
            patients_data = []
            for name, res in zip(selected_names, all_results):
                patients_data.append({"Model": name, "Scenario": "Baseline", "Patients": res["baseline"].treated_patients})
                patients_data.append({"Model": name, "Scenario": "Dario", "Patients": res["dario"].treated_patients})
            
            patients_df = pd.DataFrame(patients_data)
            
            patients_chart = alt.Chart(patients_df).mark_bar().encode(
                x=alt.X("Model:N"),
                y=alt.Y("Patients:Q"),
                color=alt.Color("Scenario:N", scale=alt.Scale(
                    domain=["Baseline", "Dario"],
                    range=[COLORS["baseline"], COLORS["dario"]]
                )),
                xOffset="Scenario:N",
                tooltip=["Model", "Scenario", alt.Tooltip("Patients:Q", format=",.0f")],
            ).properties(height=300, title="Treated Patients: Baseline vs Dario")
            
            st.altair_chart(patients_chart, use_container_width=True)
            
            # -----------------------------------------------------------------
            # SECTION 2: Incremental Metrics Comparison
            # -----------------------------------------------------------------
            st.markdown("---")
            st.markdown("### Incremental Metrics Across Models")
            
            incr_data = []
            for name, res in zip(selected_names, all_results):
                incr = res["incremental"]
                incr_data.append({
                    "Model": name,
                    "Add'l Patients": incr.incremental_patients,
                    "Add'l Revenue": incr.incremental_revenue,
                    "Add'l Cost": incr.incremental_cost,
                    "Add'l Profit": incr.incremental_profit,
                    "Incremental ROI": incr.incremental_roi,
                })
            
            incr_df = pd.DataFrame(incr_data)
            
            # Format for display
            incr_display = incr_df.copy()
            incr_display["Add'l Patients"] = incr_display["Add'l Patients"].apply(lambda x: fmt_number(x))
            for col in ["Add'l Revenue", "Add'l Cost", "Add'l Profit"]:
                incr_display[col] = incr_display[col].apply(lambda x: fmt_money(x))
            incr_display["Incremental ROI"] = incr_display["Incremental ROI"].apply(lambda x: fmt_roi(x))
            
            st.dataframe(incr_display, use_container_width=True, hide_index=True)
            
            # Charts row
            chart_col1, chart_col2 = st.columns(2)
            
            with chart_col1:
                # Incremental ROI chart
                roi_chart_data = pd.DataFrame([{
                    "Model": name,
                    "Incremental ROI": res["incremental"].incremental_roi
                } for name, res in zip(selected_names, all_results)])
                
                roi_chart = alt.Chart(roi_chart_data).mark_bar(color=COLORS["secondary"]).encode(
                    x=alt.X("Model:N"),
                    y=alt.Y("Incremental ROI:Q", title="ROI (x)"),
                    tooltip=["Model", alt.Tooltip("Incremental ROI:Q", format=".2f")],
                ).properties(height=250, title="Incremental ROI by Model")
                
                # Add zero line
                zero_line = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="red", strokeDash=[3, 3]).encode(y="y:Q")
                
                st.altair_chart(roi_chart + zero_line, use_container_width=True)
            
            with chart_col2:
                # Incremental Profit chart
                profit_chart_data = pd.DataFrame([{
                    "Model": name,
                    "Incremental Profit": res["incremental"].incremental_profit / 1_000_000
                } for name, res in zip(selected_names, all_results)])
                
                profit_chart = alt.Chart(profit_chart_data).mark_bar(color=COLORS["success"]).encode(
                    x=alt.X("Model:N"),
                    y=alt.Y("Incremental Profit:Q", title="Profit ($M)"),
                    tooltip=["Model", alt.Tooltip("Incremental Profit:Q", format=",.2f")],
                ).properties(height=250, title="Incremental Profit by Model")
                
                st.altair_chart(profit_chart + zero_line, use_container_width=True)
            
            # -----------------------------------------------------------------
            # SECTION 3: Cumulative Profit Over Time (Timeline Mode)
            # -----------------------------------------------------------------
            st.markdown("---")
            st.markdown("### Cumulative Profit Over Time")
            
            if use_timeline and len(selected_models) >= 2:
                st.caption("Timeline Mode: Models mapped to Launch → Opt1 → Opt2 → Steady State")
                
                timeline_df = compute_timeline_profit(selected_models, selected_names)
                
                if not timeline_df.empty:
                    show_baseline_overlay = st.checkbox("Show Baseline Overlay", value=True, key="baseline_overlay")
                    
                    # Main timeline chart
                    timeline_chart = alt.Chart(timeline_df).mark_line(strokeWidth=2).encode(
                        x=alt.X("Month:Q", title="Month"),
                        y=alt.Y("Cumulative Profit:Q", title="Cumulative Profit ($)"),
                        color=alt.Color("Period:N", scale=alt.Scale(
                            domain=[p["name"] for p in TIMELINE_PERIODS[:len(selected_models)]],
                            range=[p["color"] for p in TIMELINE_PERIODS[:len(selected_models)]]
                        )),
                        tooltip=[
                            "Month",
                            "Period",
                            "Model",
                            alt.Tooltip("Cumulative Profit:Q", format="$,.0f"),
                            alt.Tooltip("Monthly Profit:Q", format="$,.0f"),
                        ],
                    ).properties(height=400, title="Cumulative Profit Over Time (Segmented by Optimization Phase)")
                    
                    # Baseline overlay
                    if show_baseline_overlay:
                        baseline_df = compute_baseline_overlay(selected_models, timeline_df)
                        if not baseline_df.empty:
                            baseline_line = alt.Chart(baseline_df).mark_line(
                                strokeDash=[5, 5],
                                color=COLORS["baseline"],
                                strokeWidth=2
                            ).encode(
                                x=alt.X("Month:Q"),
                                y=alt.Y("Cumulative Profit:Q"),
                                tooltip=[
                                    "Month",
                                    alt.Tooltip("Cumulative Profit:Q", format="$,.0f", title="Baseline Cum. Profit"),
                                ],
                            )
                            timeline_chart = timeline_chart + baseline_line
                    
                    st.altair_chart(timeline_chart, use_container_width=True)
                    
                    # Period breakdown table
                    with st.expander("Period Breakdown"):
                        period_summary = timeline_df.groupby("Period").agg({
                            "Monthly Profit": "mean",
                            "Cumulative Profit": "last",
                            "Month": "max",
                        }).reset_index()
                        period_summary.columns = ["Period", "Avg Monthly Profit", "End Cumulative Profit", "End Month"]
                        period_summary["Avg Monthly Profit"] = period_summary["Avg Monthly Profit"].apply(lambda x: fmt_money(x))
                        period_summary["End Cumulative Profit"] = period_summary["End Cumulative Profit"].apply(lambda x: fmt_money(x))
                        st.dataframe(period_summary, use_container_width=True, hide_index=True)
            else:
                # Simple cumulative profit comparison (non-timeline mode)
                st.caption("Enable Timeline Mode in model settings to see segmented optimization phases")
                
                profit_over_time_data = []
                for i, (name, res) in enumerate(zip(selected_names, all_results)):
                    monthly_profit = res["dario"].net_profit / 12
                    cumulative = 0
                    for month in range(1, 31):  # 30 months
                        cumulative += monthly_profit
                        profit_over_time_data.append({
                            "Month": month,
                            "Model": name,
                            "Cumulative Profit": cumulative,
                        })
                
                profit_df = pd.DataFrame(profit_over_time_data)
                
                cum_profit_chart = alt.Chart(profit_df).mark_line(strokeWidth=2).encode(
                    x=alt.X("Month:Q"),
                    y=alt.Y("Cumulative Profit:Q", title="Cumulative Profit ($)"),
                    color=alt.Color("Model:N", scale=alt.Scale(
                        domain=selected_names,
                        range=TAB_PALETTE[:len(selected_names)]
                    )),
                    tooltip=["Month", "Model", alt.Tooltip("Cumulative Profit:Q", format="$,.0f")],
                ).properties(height=350, title="Cumulative Profit Over Time")
                
                st.altair_chart(cum_profit_chart, use_container_width=True)
            
            # -----------------------------------------------------------------
            # SECTION 4: Funnel Stage Comparison
            # -----------------------------------------------------------------
            st.markdown("---")
            st.markdown("### Funnel Stage Comparison")
            
            stage_model_select = st.selectbox(
                "Select model to view funnel:",
                options=selected_names,
                key="funnel_model_select",
            )
            
            stage_model_idx = selected_names.index(stage_model_select)
            stage_results = all_results[stage_model_idx]
            
            stage_data = []
            for s in stage_results["baseline"].stages:
                stage_data.append({
                    "Stage": f"S{s.stage_num}",
                    "Scenario": "Baseline",
                    "Patients": s.patients,
                })
            for s in stage_results["dario"].stages:
                stage_data.append({
                    "Stage": f"S{s.stage_num}",
                    "Scenario": "Dario",
                    "Patients": s.patients,
                })
            
            stage_df = pd.DataFrame(stage_data)
            
            stage_chart = alt.Chart(stage_df).mark_line(point=True).encode(
                x=alt.X("Stage:N", sort=None),
                y=alt.Y("Patients:Q"),
                color=alt.Color("Scenario:N", scale=alt.Scale(
                    domain=["Baseline", "Dario"],
                    range=[COLORS["baseline"], COLORS["dario"]]
                )),
                tooltip=["Stage", "Scenario", alt.Tooltip("Patients:Q", format=",.0f")],
            ).properties(height=300, title=f"Funnel Comparison: {stage_model_select}")
            
            st.altair_chart(stage_chart, use_container_width=True)
            
            # -----------------------------------------------------------------
            # SECTION 5: Model Diff View
            # -----------------------------------------------------------------
            st.markdown("---")
            st.markdown("### Model Diff View")
            
            if len(selected_names) >= 2:
                diff_col1, diff_col2 = st.columns(2)
                with diff_col1:
                    diff_model_a = st.selectbox("Model A:", options=selected_names, index=0, key="diff_model_a")
                with diff_col2:
                    remaining = [n for n in selected_names if n != diff_model_a]
                    diff_model_b = st.selectbox("Model B:", options=remaining, index=0, key="diff_model_b")
                
                idx_a = st.session_state["model_names"].index(diff_model_a)
                idx_b = st.session_state["model_names"].index(diff_model_b)
                model_a = st.session_state["models"][idx_a]
                model_b = st.session_state["models"][idx_b]
                
                diff_rows = []
                
                # Compare shared settings
                shared_a = model_a.get("shared", {})
                shared_b = model_b.get("shared", {})
                
                if shared_a.get("base_population") != shared_b.get("base_population"):
                    diff_rows.append({
                        "Parameter": "Base Population",
                        diff_model_a: fmt_number(shared_a.get("base_population", 0)),
                        diff_model_b: fmt_number(shared_b.get("base_population", 0)),
                    })
                
                # Compare dario scenario
                dario_a = model_a.get("dario", {})
                dario_b = model_b.get("dario", {})
                
                dario_params = [
                    ("ARPP", "arpp", fmt_money),
                    ("Treatment Years", "treatment_years", lambda x: f"{x:.1f}"),
                    ("Discount", "discount", fmt_pct),
                    ("Stage 6 CAC", "stage_6_cac", fmt_money),
                ]
                
                for label, key, fmt_func in dario_params:
                    val_a = dario_a.get(key, 0)
                    val_b = dario_b.get(key, 0)
                    if val_a != val_b:
                        diff_rows.append({
                            "Parameter": f"Dario {label}",
                            diff_model_a: fmt_func(val_a),
                            diff_model_b: fmt_func(val_b),
                        })
                
                # Compare stage ratios
                ratios_a = dario_a.get("ratios", [])
                ratios_b = dario_b.get("ratios", [])
                
                for i in range(min(len(ratios_a), len(ratios_b))):
                    if ratios_a[i] != ratios_b[i] and i > 0:
                        diff_rows.append({
                            "Parameter": f"Stage {i+1} Ratio",
                            diff_model_a: fmt_pct(ratios_a[i]),
                            diff_model_b: fmt_pct(ratios_b[i]),
                        })
                
                if diff_rows:
                    diff_df = pd.DataFrame(diff_rows)
                    st.dataframe(diff_df, use_container_width=True, hide_index=True)
                else:
                    st.success("These two models have identical parameters!")
            
            # -----------------------------------------------------------------
            # EXPORT
            # -----------------------------------------------------------------
            st.markdown("---")
            st.markdown("### Export Comparison")
            
            export_col1, export_col2 = st.columns(2)
            
            with export_col1:
                # Full comparison CSV
                csv_data = comp_df.to_csv(index=False)
                st.download_button(
                    label="Download Comparison (CSV)",
                    data=csv_data,
                    file_name="model_comparison.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            
            with export_col2:
                # Incremental metrics CSV
                incr_csv = incr_df.to_csv(index=False)
                st.download_button(
                    label="Download Incremental Metrics (CSV)",
                    data=incr_csv,
                    file_name="incremental_metrics.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
    
    # =========================================================================
    # FOOTER / HELP
    # =========================================================================
    st.divider()
    
    with st.expander("How to Interpret Results"):
        st.markdown("""
        **Key Metrics:**
        
        - **Treated Patients**: Number of patients completing the funnel (Stage 13)
        - **Net Revenue**: Gross revenue minus gross-to-net discount
        - **Total Cost**: CAC (Stage 6) + Platform costs
        - **Net Profit**: Net Revenue - Total Cost
        - **ROI**: Net Profit / Total Cost (1.0x = break-even)
        - **Incremental ROI**: Additional profit per additional dollar spent
        
        **CAC Logic:**
        - Stages 1-5: No customer acquisition cost (awareness stages)
        - Stage 6 (Aware of Dario): CAC pool is created here
        - Stages 7-13: CAC per patient is derived from the Stage 6 pool
        
        **Timeline Mode:**
        - Maps up to 4 models to optimization phases
        - Launch → Optimization 1 → Optimization 2 → Steady State
        - Shows segmented cumulative profit growth
        
        **Ad-Agency Comparison:**
        - Traditional digital advertising typically achieves 1.2-1.5x ROAS
        - Enables apples-to-apples comparison with Dario platform
        """)
    
    st.caption(f"PharmaROI Intelligence Platform v{APP_VERSION} | Built with Streamlit")

if __name__ == "__main__":
    main()
