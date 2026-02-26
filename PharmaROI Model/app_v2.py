# app.py
# PharmaROI Intelligence — V2 (Madrigal Funnel) Streamlit Prototype
# Run: streamlit run app.py
#
# This app mirrors the sponsor-provided funnel stages, supports per-stage toggles,
# ratio sliders, CAC inputs, and computes net ROI using a discount (gross > net).
#
# Optional: Place "Madrigal Funnel.xlsx" in the same folder as this app.py to
# pre-populate defaults. The app will still run without it.

# Run Command (copy and paste into terminal): streamlit run "PharmaROI Model/app.py"

from __future__ import annotations

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

# Optional Excel parsing / tables
try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None  # fallback if pandas is not installed


# -----------------------------
# Color palette (editable)
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


# -----------------------------
# Funnel definitions (fixed)
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


# -----------------------------
# Sponsor screenshot defaults
# -----------------------------
SPONSOR_DEFAULTS = {
    "base_population": 10_000_000,
    "ratios": [
        1.00,  # Stage 1 (unused)
        0.35,
        0.16,
        0.22,
        0.75,
        0.40,
        0.15,
        0.80,
        1.00,
        0.75,
        0.90,
        0.50,
        0.90,
    ],
    "cac": [
        0.0,   # stage 1
        0.0,   # stage 2
        0.0,   # stage 3
        0.0,   # stage 4
        0.0,   # stage 5
        10.0,  # stage 6
        67.0,  # stage 7
        83.0,  # stage 8
        83.0,  # stage 9
        111.0, # stage 10
        123.0, # stage 11
        247.0, # stage 12
        274.0, # stage 13
    ],
    "arpp": 47_400.0,
    "treatment_years": 1.0,
    "discount": 0.68,
    "stage_active": [True] * len(STAGE_NAMES),
}

ZERO_SAMPLE = {
    "base_population": 0,
    "ratios": [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    ],
    "cac": [
        0.0,   # stage 1
        0.0,   # stage 2
        0.0,   # stage 3
        0.0,   # stage 4
        0.0,   # stage 5
        0.0,  # stage 6
        0.0,  # stage 7
        0.0,  # stage 8
        0.0,  # stage 9
        0.0, # stage 10
        0.0, # stage 11
        0.0, # stage 12
        0.0, # stage 13
    ],
    "arpp": 0.0,
    "treatment_years": 0.0,
    "discount": 0.0,
    "stage_active": [True] * len(STAGE_NAMES),
}


# -----------------------------
# Formatting helpers
# -----------------------------
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def money(x: float) -> str:
    return f"${x:,.0f}"


def number(x: float) -> str:
    return f"{x:,.0f}"


def pct(x: float) -> str:
    return f"{x*100:,.1f}%"


def roix(x: float) -> str:
    return f"{x:,.2f}x"


# -----------------------------
# Optional Excel defaults loader
# -----------------------------
def try_load_defaults_from_excel(xlsx_path: Path) -> Optional[Dict[str, Any]]:
    if pd is None:
        return None
    if not xlsx_path.exists():
        return None

    try:
        xls = pd.ExcelFile(xlsx_path)
        sheet_name = xls.sheet_names[0]
        df = pd.read_excel(xlsx_path, sheet_name=sheet_name)

        df_cols = list(df.columns)
        stage_col = df_cols[0]

        num_col = next((c for c in df_cols if "number" in str(c).lower() and "patient" in str(c).lower()), None)
        ratio_col = next((c for c in df_cols if "ratio" in str(c).lower()), None)
        cac_col = next((c for c in df_cols if str(c).strip().lower() == "cac"), None)

        stage_series = df[stage_col].astype(str).fillna("")
        stage_rows: Dict[str, int] = {}
        for idx, val in enumerate(stage_series.tolist()):
            v = val.strip().lower()
            for s in STAGE_NAMES:
                if s.lower() == v and s not in stage_rows:
                    stage_rows[s] = idx

        if len(stage_rows) < 6:
            stage_rows = {}
            for idx, val in enumerate(stage_series.tolist()):
                v = val.strip().lower()
                for s in STAGE_NAMES:
                    if s.lower() in v and s not in stage_rows:
                        stage_rows[s] = idx

        if len(stage_rows) < 6:
            return None

        ratios: List[float] = []
        cac: List[float] = []
        base_population: Optional[float] = None

        for k, s in enumerate(STAGE_NAMES):
            idx = stage_rows.get(s)
            if idx is None:
                ratios.append(SPONSOR_DEFAULTS["ratios"][k])
                cac.append(SPONSOR_DEFAULTS["cac"][k])
                continue

            if num_col is not None and k == 0:
                try:
                    base_population = float(df.loc[idx, num_col])
                except Exception:
                    base_population = float(SPONSOR_DEFAULTS["base_population"])

            if ratio_col is not None:
                try:
                    rval = float(df.loc[idx, ratio_col])
                    if rval > 1.0:
                        rval = rval / 100.0
                    ratios.append(clamp(rval, 0.0, 1.0))
                except Exception:
                    ratios.append(SPONSOR_DEFAULTS["ratios"][k])
            else:
                ratios.append(SPONSOR_DEFAULTS["ratios"][k])

            if cac_col is not None:
                try:
                    cval = df.loc[idx, cac_col]
                    cval = 0.0 if pd.isna(cval) else float(cval)
                    cac.append(max(0.0, cval))
                except Exception:
                    cac.append(SPONSOR_DEFAULTS["cac"][k])
            else:
                cac.append(SPONSOR_DEFAULTS["cac"][k])

        if base_population is None:
            base_population = float(SPONSOR_DEFAULTS["base_population"])

        return {
            "base_population": int(base_population),
            "ratios": ratios,
            "cac": cac,
        }

    except Exception:
        return None


# -----------------------------
# Core computations
# -----------------------------
@dataclass(frozen=True)
class StageInput:
    name: str
    active: bool
    ratio: float  # 0..1
    cac: float    # $ per patient


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
    results: List[StageResult] = []
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

        results.append(
            StageResult(
                name=s.name,
                active=s.active,
                ratio_used=ratio_used,
                patients=patients,
                cac_per_patient=cac_pp,
                stage_cac=stage_cac,
                cumulative_cac=cumulative,
            )
        )
        prev_patients = patients

    return results


def compute_financials(
    treated_patients: float,
    arpp: float,
    treatment_years: float,
    discount: float,
    funnel_cac_total: float,
) -> Dict[str, float]:
    treated = max(0.0, float(treated_patients))
    arpp = max(0.0, float(arpp))
    years = max(0.0, float(treatment_years))
    disc = clamp(discount, 0.0, 0.80)
    funnel_cac = max(0.0, float(funnel_cac_total))

    gross = treated * arpp * years
    net = gross * (1.0 - disc)

    net_profit = net
    roi = (net / funnel_cac) if funnel_cac > 0 else float("nan")

    return {
        "treated_patients": treated,
        "gross_revenue": gross,
        "net_revenue": net,
        "discount": disc,
        "funnel_cac_total": funnel_cac,
        "net_profit": net_profit,
        "roi_net": roi,
    }

def build_polished_excel_report(df_funnel, fin: dict, colors: dict) -> bytes:
    """
    Creates a sponsor-ready Excel report with:
      - Summary sheet (KPIs + ROI + chart)
      - Funnel sheet (table + formatting)
    Returns bytes for Streamlit download_button.
    """
    wb = Workbook()

    # ---------- Styles ----------
    header_fill = PatternFill("solid", fgColor="0F172A")  # dark slate
    header_font = Font(bold=True, color="FFFFFF")
    bold_font = Font(bold=True)
    muted_font = Font(color="6B7280")
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    def set_col_widths(ws, widths: dict):
        for col_idx, w in widths.items():
            ws.column_dimensions[get_column_letter(col_idx)].width = w

    def style_header_row(ws, row=1):
        for cell in ws[row]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center

    # ---------- Summary sheet ----------
    ws_sum = wb.active
    ws_sum.title = "Summary"

    ws_sum["A1"] = "PharmaROI Intelligence — Sponsor Summary"
    ws_sum["A1"].font = Font(bold=True, size=14)
    ws_sum.merge_cells("A1:D1")

    # KPI table (label, value)
    summary_rows = [
        ("Treated Patients", fin["treated_patients"], "0"),
        ("Gross Revenue", fin["gross_revenue"], "$#,##0"),
        ("Discount", fin["discount"], "0.0%"),
        ("Net Revenue", fin["net_revenue"], "$#,##0"),
        ("Funnel CAC Total", fin["funnel_cac_total"], "$#,##0"),
        ("Net Profit", fin["net_profit"], "$#,##0"),
        ("ROI (Net)", fin["roi_net"], "0.00x"),
    ]

    ws_sum["A3"] = "Metric"
    ws_sum["B3"] = "Value"
    ws_sum["C3"] = "Format"
    ws_sum["D3"] = "Notes"
    style_header_row(ws_sum, 3)

    start_row = 4
    for i, (label, value, fmt) in enumerate(summary_rows):
        r = start_row + i
        ws_sum[f"A{r}"] = label
        ws_sum[f"B{r}"] = float(value) if value == value else None  # handle nan
        ws_sum[f"C{r}"] = fmt
        ws_sum[f"D{r}"] = ""
        ws_sum[f"A{r}"].font = bold_font if label in ("Net Revenue", "Total Costs", "ROI (Net)") else Font()
        ws_sum[f"A{r}"].alignment = left
        ws_sum[f"B{r}"].alignment = left
        ws_sum[f"C{r}"].font = muted_font
        ws_sum[f"D{r}"].font = muted_font

        # Apply number formats to value cells
        ws_sum[f"B{r}"].number_format = fmt

    ws_sum.freeze_panes = "A4"
    set_col_widths(ws_sum, {1: 26, 2: 18, 3: 12, 4: 20})

    # ---------- Add chart data for Excel chart ----------
    # Put chart data below KPI table
    chart_anchor_row = start_row + len(summary_rows) + 2  # a blank row
    ws_sum[f"A{chart_anchor_row}"] = "Metric"
    ws_sum[f"B{chart_anchor_row}"] = "Value"
    style_header_row(ws_sum, chart_anchor_row)

    chart_data_rows = [
        ("Net Revenue", fin["net_revenue"]),
        ("Gross Revenue", fin["gross_revenue"]),
        ("Net Profit", fin["net_profit"]),
    ]
    for j, (m, v) in enumerate(chart_data_rows):
        rr = chart_anchor_row + 1 + j
        ws_sum[f"A{rr}"] = m
        ws_sum[f"B{rr}"] = float(v)
        ws_sum[f"B{rr}"].number_format = "$#,##0"

    # Create BarChart
    chart = BarChart()
    chart.type = "col"
    chart.title = "Net Revenue vs Costs vs Net Profit"
    chart.y_axis.title = "USD"
    chart.x_axis.title = ""

    data_ref = Reference(ws_sum, min_col=2, min_row=chart_anchor_row, max_row=chart_anchor_row + len(chart_data_rows))
    cats_ref = Reference(ws_sum, min_col=1, min_row=chart_anchor_row + 1, max_row=chart_anchor_row + len(chart_data_rows))

    chart.add_data(data_ref, titles_from_data=True)
    chart.set_categories(cats_ref)
    chart.legend = None

    # Color the single series (Excel chart has 1 series with 3 categories)
    # openpyxl doesn't reliably support per-bar colors across all Excel versions,
    # but we can set series color to primary and rely on labels. Still looks polished.
    try:
        chart.series[0].graphicalProperties.solidFill = colors.get("primary", "0F6CBD").replace("#", "")
    except Exception:
        pass

    # Place chart
    ws_sum.add_chart(chart, "D4")

    # ---------- Funnel sheet ----------
    ws_fun = wb.create_sheet("Funnel")

    # Write headers
    headers = list(df_funnel.columns)
    for c, h in enumerate(headers, start=1):
        ws_fun.cell(row=1, column=c, value=h)
    style_header_row(ws_fun, 1)

    # Write rows
    for r_idx, row in enumerate(df_funnel.itertuples(index=False), start=2):
        for c_idx, val in enumerate(row, start=1):
            ws_fun.cell(row=r_idx, column=c_idx, value=val)

    ws_fun.freeze_panes = "A2"

    # Apply formats if columns exist
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

    # Set column widths (adjust as you like)
    widths = {
        col_map.get("#", 1): 5,
        col_map.get("Stage", 2): 52,
        col_map.get("Status", 3): 22,
        col_map.get("Ratio Used", 4): 12,
        col_map.get("Patients", 5): 14,
        col_map.get("CAC ($/pt)", 6): 12,
        col_map.get("Stage CAC ($)", 7): 15,
        col_map.get("Cumulative CAC ($)", 8): 18,
    }
    set_col_widths(ws_fun, widths)

    # ---------- Export to bytes ----------
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

# -----------------------------
# Streamlit App
# -----------------------------
st.set_page_config(page_title="PharmaROI V2 — Madrigal Funnel", page_icon="📈", layout="wide")

st.title("📈 PharmaROI Intelligence — V2 (Madrigal Funnel Prototype)")
st.caption("Sponsor-style funnel with per-stage toggles, ratios, CAC, and ROI based on net revenue (gross minus discount).")

if "v2_state" not in st.session_state:
    st.session_state["v2_state"] = SPONSOR_DEFAULTS.copy()
    st.session_state["v2_state"]["stage_names"] = STAGE_NAMES.copy()

xlsx_path = Path("Madrigal Funnel.xlsx")
if "excel_loaded" not in st.session_state:
    excel_defaults = try_load_defaults_from_excel(xlsx_path)
    if excel_defaults is not None:
        st.session_state["v2_state"]["base_population"] = excel_defaults["base_population"]
        st.session_state["v2_state"]["ratios"] = excel_defaults["ratios"]
        st.session_state["v2_state"]["cac"] = excel_defaults["cac"]
        st.session_state["excel_loaded"] = True
    else:
        st.session_state["excel_loaded"] = False


with st.sidebar:
    st.header("Controls")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Reset: Sponsor Example", width='stretch'):
            st.session_state["v2_state"] = SPONSOR_DEFAULTS.copy()
            st.session_state["v2_state"]["stage_names"] = STAGE_NAMES.copy()
    with c2:
        if st.button("Reset: Zero", width='stretch'):
            st.session_state["v2_state"] = ZERO_SAMPLE.copy()
            st.session_state["v2_state"]["stage_names"] = ["Insert Funnel Name"] * len(STAGE_NAMES)
            # Clear widget keys so they re-render
            for idx in range(len(STAGE_NAMES)):
                for key in [f"active_{idx}", f"ratio_{idx}", f"cac_{idx}", f"stage_name_{idx}"]:
                    if key in st.session_state:
                        del st.session_state[key]
    st.divider()
    st.subheader("Base Population")
    st.session_state["v2_state"]["base_population"] = st.number_input(
        "Stage 1 — Total Addressable Market (N0)",
        min_value=0,
        step=100_000,
        value=int(st.session_state["v2_state"]["base_population"]),
    )

    st.divider()
    st.subheader("Revenue & Costs")
    st.session_state["v2_state"]["arpp"] = st.number_input(
        "Annual revenue per treated patient (ARPP) — gross $/year",
        min_value=0.0,
        step=1_000.0,
        value=float(st.session_state["v2_state"]["arpp"]),
    )
    st.session_state["v2_state"]["treatment_years"] = st.slider(
        "Length of treatment (years)",
        min_value=0.1,
        max_value=1.0,
        step=0.1,
        value=float(st.session_state["v2_state"]["treatment_years"]),
    )
    st.session_state["v2_state"]["discount"] = st.slider(
        "Discount rate (gross → net)",
        min_value=0.0,
        max_value=0.80,
        step=0.01,
        value=float(st.session_state["v2_state"]["discount"]),
        help="Net Revenue = Gross Revenue × (1 − discount)",
    )

    st.divider()
    st.subheader("Funnel Stages")
    
    # Customizable stage names section
    with st.expander("✏️ Customize Stage Names"):
        st.caption("Edit the names of funnel stages to match your use case.")
        
        # Initialize stage_names if it doesn't exist
        if "stage_names" not in st.session_state["v2_state"]:
            st.session_state["v2_state"]["stage_names"] = STAGE_NAMES.copy()
        
        for idx in range(len(STAGE_NAMES)):
            st.session_state["v2_state"]["stage_names"][idx] = st.text_input(
                f"Stage {idx + 1} name:",
                value=st.session_state["v2_state"]["stage_names"][idx],
                key=f"stage_name_{idx}",
            )
    
    st.caption("Toggle stages on/off. If off: pass-through ratio=100% and CAC=0 in calculations.")

    # Use custom names if available, otherwise use defaults
    stage_names_to_use = st.session_state["v2_state"].get("stage_names", STAGE_NAMES)

    for idx, name in enumerate(stage_names_to_use):
        with st.expander(f"{idx+1}. {name}", expanded=(idx < 3)):
            if len(st.session_state["v2_state"]["stage_active"]) != len(STAGE_NAMES):
                st.session_state["v2_state"]["stage_active"] = [True] * len(STAGE_NAMES)
            if len(st.session_state["v2_state"]["ratios"]) != len(STAGE_NAMES):
                st.session_state["v2_state"]["ratios"] = SPONSOR_DEFAULTS["ratios"][:]
            if len(st.session_state["v2_state"]["cac"]) != len(STAGE_NAMES):
                st.session_state["v2_state"]["cac"] = SPONSOR_DEFAULTS["cac"][:]

            st.session_state["v2_state"]["stage_active"][idx] = st.checkbox(
                "Use this stage",
                value=bool(st.session_state["v2_state"]["stage_active"][idx]),
                key=f"active_{idx}",
            )

            if idx == 0:
                st.info("Stage 1 is the base population. No ratio is applied here.")
            else:
                disabled = not st.session_state["v2_state"]["stage_active"][idx]
                st.session_state["v2_state"]["ratios"][idx] = st.slider(
                    "Funnel ratio (to reach this stage)",
                    min_value=0.0,
                    max_value=1.0,
                    step=0.01,
                    value=float(st.session_state["v2_state"]["ratios"][idx]),
                    disabled=disabled,
                    key=f"ratio_{idx}",
                )

            disabled = not st.session_state["v2_state"]["stage_active"][idx]
            st.session_state["v2_state"]["cac"][idx] = st.number_input(
                "CAC ($ per patient at this stage)",
                min_value=0.0,
                step=1.0,
                value=float(st.session_state["v2_state"]["cac"][idx]),
                disabled=disabled,
                key=f"cac_{idx}",
            )


stages: List[StageInput] = []
stage_names_to_use = st.session_state["v2_state"].get("stage_names", STAGE_NAMES)

for idx, name in enumerate(stage_names_to_use):
    stages.append(
        StageInput(
            name=name,
            active=bool(st.session_state["v2_state"]["stage_active"][idx]),
            ratio=float(st.session_state["v2_state"]["ratios"][idx]) if idx > 0 else 1.0,
            cac=float(st.session_state["v2_state"]["cac"][idx]),
        )
    )

base_pop = float(st.session_state["v2_state"]["base_population"])
funnel_results = compute_funnel(stages, base_pop)

treated_patients = funnel_results[-1].patients
funnel_cac_total = funnel_results[-1].cumulative_cac

fin = compute_financials(
    treated_patients=treated_patients,
    arpp=float(st.session_state["v2_state"]["arpp"]),
    treatment_years=float(st.session_state["v2_state"]["treatment_years"]),
    discount=float(st.session_state["v2_state"]["discount"]),
    funnel_cac_total=funnel_cac_total,
)


# -----------------------------
# Main UI
# -----------------------------
k1, k2, k3, k4, k5 = st.columns(5)
roi = fin["roi_net"]

k1.metric("ROI (Net)", roix(roi) if roi == roi else "—")
k2.metric("Treated Patients", number(fin["treated_patients"]))
k3.metric("Net Revenue", money(fin["net_revenue"]))
k4.metric("Gross Revenue", money(fin["gross_revenue"]))
k5.metric("Funnel CAC", money(fin["funnel_cac_total"]))

st.markdown(
    f"Gross Revenue: \\${fin['gross_revenue']:,.0f}  |  "
    f"Discount: {fin['discount']*100:.1f}%  |  "
    f"Net Revenue: \\${fin['net_revenue']:,.0f}"
)

# Funnel table
st.subheader("Funnel Table (Sponsor-Style)")

table_rows: List[Dict[str, Any]] = []
for idx, r in enumerate(funnel_results):
    ratio_display = "—" if idx == 0 else pct(r.ratio_used)
    status = "Active" if r.active else "Inactive (pass-through)"
    table_rows.append(
        {
            "#": idx + 1,
            "Stage": r.name,
            "Status": status,
            "Ratio Used": ratio_display,
            "Patients": float(r.patients),
            "CAC ($/pt)": float(r.cac_per_patient),
            "Stage CAC ($)": float(r.stage_cac),
            "Cumulative CAC ($)": float(r.cumulative_cac),
        }
    )

if pd is None:
    st.warning("Pandas is not installed. Install with: pip install pandas openpyxl")
    st.write(table_rows)

else:
    # Build DataFrame once
    df_funnel = pd.DataFrame(table_rows)

    # Build polished Excel report (Summary + Funnel + Chart)
    polished_xlsx = build_polished_excel_report(df_funnel, fin, COLORS)

    # Display formatting for Streamlit table
    df_display = df_funnel.copy()
    df_display["Patients"] = df_display["Patients"].map(lambda x: f"{x:,.0f}")
    df_display["CAC ($/pt)"] = df_display["CAC ($/pt)"].map(lambda x: f"${x:,.0f}")
    df_display["Stage CAC ($)"] = df_display["Stage CAC ($)"].map(lambda x: f"${x:,.0f}")
    df_display["Cumulative CAC ($)"] = df_display["Cumulative CAC ($)"].map(lambda x: f"${x:,.0f}")

    # Export buttons
    st.markdown("### Export Reports")
    col1, col2 = st.columns(2)

    with col1:
        st.download_button(
            label="⬇️ Download Polished Excel Report (Summary + Funnel + Chart)",
            data=polished_xlsx,
            file_name="pharmaroi_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with col2:
        csv_data = df_funnel.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Download Funnel (CSV)",
            data=csv_data,
            file_name="pharmaroi_funnel.csv",
            mime="text/csv",
        )

    # Show table
    st.dataframe(df_display, width='stretch', hide_index=True)


# Chart: Net Revenue vs Total Costs vs Net Profit
st.subheader("Financial Summary (Net Revenue vs Costs vs Net Profit)")

chart_data = [
    {"Metric": "Net Revenue", "Value": fin["net_revenue"], "ColorKey": "revenue"},
    {"Metric": "Gross Revenue", "Value": fin["gross_revenue"], "ColorKey": "revenue"},
    {"Metric": "Net Profit", "Value": fin["net_profit"], "ColorKey": "profit"},
]

color_scale = alt.Scale(
    domain=["revenue", "costs", "profit"],
    range=[COLORS["revenue"], COLORS["costs"], COLORS["profit"]],
)

chart = (
    alt.Chart(pd.DataFrame(chart_data) if pd is not None else alt.Data(values=chart_data))
    .mark_bar(size=60)
    .encode(
        x=alt.X("Metric:N", sort=None, title=None),
        y=alt.Y("Value:Q", title="USD"),
        color=alt.Color("ColorKey:N", scale=color_scale, legend=None),
        tooltip=[alt.Tooltip("Metric:N"), alt.Tooltip("Value:Q", format=",.0f")],
    )
)

st.altair_chart(chart, width='stretch')

with st.expander("Optional: Funnel Visualization"):
    funnel_viz = [{"Stage": r.name, "Patients": r.patients} for r in funnel_results]
    if pd is None:
        st.write(funnel_viz)
    else:
        fdf = pd.DataFrame(funnel_viz)
        fchart = (
            alt.Chart(fdf)
            .mark_bar()
            .encode(
                y=alt.Y("Stage:N", sort="-x", title=None),
                x=alt.X("Patients:Q", title="Patients"),
                color=alt.value(COLORS["primary"]),
                tooltip=[alt.Tooltip("Patients:Q", format=",.0f"), "Stage:N"],
            )
        )
        st.altair_chart(fchart, width='stretch')

st.divider()
st.subheader("How to interpret")
st.write(
    """
- The funnel computes *patients at each stage* using the stage ratio (unless the stage is turned off).
- CAC is applied per stage only when that stage is active.
- **Stage CAC** = Patients at Stage x CAC per Patient
- **Total Funnel CAC** = Sum of Stage CAC 1-13
- **Gross Revenue** = Treated Patients × ARPP × Treatment Years  
- **Net Revenue** = Gross Revenue × (1 − Discount)
- **ROI (Net)** = Net Revenue / Total Funnel CAC
"""
)

with st.expander("▶ How to run"):
    st.code(
        """1) Save this file as: app.py
2) (Optional) Place Madrigal Funnel.xlsx in the SAME folder as app.py
3) Install dependencies:
   pip install streamlit altair
   pip install pandas openpyxl
4) Run:
   streamlit run app.py
5) Open the Local URL Streamlit prints (usually http://localhost:8501)
""",
        language="text",
    )
