#!/usr/bin/env python3
"""Audit DDS-2025-118 drilling invoices against contract and field reports.

The script is deterministic and uses Decimal arithmetic throughout pricing.
It writes line-level evidence, invoice-level reconciliation, a submission-shaped
CSV, and a JSON summary under artifacts/audit/.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ZERO = Decimal("0.00")
CENT = Decimal("0.01")
ISSUE_DATE_A3 = pd.Timestamp("2026-08-17")
EFFECTIVE_DATE_A3 = pd.Timestamp("2026-02-01")
CONTRACT_START = pd.Timestamp("2025-01-01")
CONTRACT_END = pd.Timestamp("2026-12-31")


def D(value: Any) -> Decimal:
    """Convert a CSV value to Decimal without passing through binary float."""
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


def apply_step(rate: Decimal, factor: Decimal) -> Decimal:
    return money(rate * factor)


def cents(value: Decimal) -> int:
    return int((money(value) * 100).to_integral_exact())


def decimal_text(value: Decimal) -> str:
    return format(money(value), "f")


BASE_RATES = {
    "DD-101": D("1847.35"),
    "DD-102": D("948.60"),
    "DD-110": D("1417.75"),
    "DD-111": D("3589.45"),
    "DD-120": D("384.15"),
    "DD-121": D("2893.65"),
    "DD-130": D("2446.15"),
    "DD-140": D("12489.50"),
    "PD-201": D("2094.85"),
    "PD-220": D("1148.35"),
    "PD-230": D("639.15"),
    "MW-301": D("1646.55"),
    "MW-310": D("2245.85"),
    "MW-320": D("779.65"),
    "MW-330": D("309.75"),
    "LW-401": D("1898.45"),
    "LW-410": D("11.37"),
    "LW-411": D("16.83"),
    "LW-412": D("13.29"),
    "LW-413": D("1849.65"),
    "LW-420": D("2746.55"),
    "LW-430": D("8394.75"),
    "RM-510": D("38.45"),
    "RM-511": D("1379.15"),
    "RM-520": D("419.85"),
    "RM-530": D("264.55"),
    "HC-601": D("689.35"),
    "HC-610": D("1947.15"),
    "HC-620": D("539.65"),
    "HC-630": D("4295.85"),
    "HC-640": D("719.55"),
    "MB-701": D("18497.50"),
    "MB-702": D("14196.25"),
}


EXPECTED_UNITS = {
    "DD-101": "person-day",
    "DD-102": "day",
    "DD-110": "day",
    "DD-111": "run",
    "DD-120": "hour",
    "DD-121": "day",
    "DD-130": "survey",
    "DD-140": "well",
    "PD-201": "person-day",
    "PD-210": "metre",
    "PD-220": "day",
    "PD-230": "day",
    "MW-301": "person-day",
    "MW-310": "day",
    "MW-320": "day",
    "MW-330": "day",
    "LW-401": "person-day",
    "LW-410": "metre",
    "LW-411": "metre",
    "LW-412": "metre",
    "LW-413": "point",
    "LW-420": "run",
    "LW-430": "well",
    "RM-510": "metre",
    "RM-511": "day",
    "RM-520": "day",
    "RM-530": "hour",
    "HC-601": "day",
    "HC-610": "trip",
    "HC-620": "day",
    "HC-630": "run",
    "HC-640": "day",
    "MB-701": "well",
    "MB-702": "well",
    "LH-711": "each",
    "LH-712": "each",
    "LH-713": "each",
    "LH-714": "each",
}


SECTION_FACTORS = {
    '26"': D("1.315"),
    '17-1/2"': D("1.145"),
    '12-1/4"': D("1.00"),
    '8-1/2"': D("0.945"),
    '6"': D("0.885"),
}

CLASS_FACTORS = {
    "Standard": D("1.00"),
    "Extended Reach": D("1.175"),
    "HPHT": D("1.325"),
}

SECTION_RATED = {"DD-110", "DD-120", "PD-220", "MW-310", "RM-510", "RM-511"}
CLASS_RATED = {"DD-120", "MW-310", "MW-320", "LW-410", "LW-411", "LW-412", "LW-413"}

STANDBY_PERCENT = {
    "DD-101": D("0.80"),
    "DD-102": D("1.00"),
    "DD-110": D("0.50"),
    "DD-111": D("1.00"),
    "DD-120": D("0.00"),
    "DD-130": D("0.00"),
    "PD-201": D("0.80"),
    "PD-210": D("0.00"),
    "PD-220": D("0.50"),
    "PD-230": D("0.50"),
    "MW-301": D("0.80"),
    "MW-310": D("0.50"),
    "MW-320": D("0.50"),
    "MW-330": D("1.00"),
    "LW-401": D("0.80"),
    "LW-410": D("0.00"),
    "LW-411": D("0.00"),
    "LW-412": D("0.00"),
    "LW-413": D("0.00"),
    "LW-420": D("1.00"),
    "RM-510": D("0.00"),
    "RM-511": D("0.50"),
    "RM-520": D("0.50"),
    "RM-530": D("0.00"),
    "HC-601": D("0.50"),
    "HC-610": D("0.00"),
    "HC-620": D("0.50"),
    "HC-630": D("0.00"),
    "HC-640": D("0.00"),
}

FULL_ON_ANY_STATUS = {"DD-140", "LW-430", "MB-701", "MB-702", "LH-711", "LH-712", "LH-713", "LH-714"}
AMENDMENT_DISCOUNT_CODES = {"DD-101", "MW-301", "LW-401", "DD-120", "MB-701"}

RIG_INDEX = {
    "2025-01": D("100.00"), "2025-02": D("100.70"), "2025-03": D("101.50"),
    "2025-04": D("102.30"), "2025-05": D("103.10"), "2025-06": D("103.60"),
    "2025-07": D("104.80"), "2025-08": D("105.40"), "2025-09": D("104.90"),
    "2025-10": D("106.20"), "2025-11": D("107.10"), "2025-12": D("108.00"),
    "2026-01": D("109.30"), "2026-02": D("110.00"), "2026-03": D("110.60"),
    "2026-04": D("111.40"), "2026-05": D("110.90"), "2026-06": D("112.20"),
    "2026-07": D("113.00"), "2026-08": D("112.60"), "2026-09": D("113.90"),
    "2026-10": D("114.70"), "2026-11": D("115.30"), "2026-12": D("116.10"),
}

FX_HALALAS_PER_USD = {
    "2025-01": D("375.00"), "2025-02": D("375.10"), "2025-03": D("375.00"),
    "2025-04": D("374.90"), "2025-05": D("375.20"), "2025-06": D("375.30"),
    "2025-07": D("375.10"), "2025-08": D("375.00"), "2025-09": D("374.80"),
    "2025-10": D("375.40"), "2025-11": D("375.60"), "2025-12": D("375.50"),
    "2026-01": D("376.00"), "2026-02": D("375.80"), "2026-03": D("375.90"),
    "2026-04": D("376.20"), "2026-05": D("376.40"), "2026-06": D("376.10"),
    "2026-07": D("375.70"), "2026-08": D("376.30"), "2026-09": D("376.60"),
    "2026-10": D("376.80"), "2026-11": D("377.00"), "2026-12": D("376.50"),
}

LOST_REPLACEMENT_SAR = {
    "LH-711": D("543750.00"),
    "LH-712": D("4687500.00"),
    "LH-713": D("1443750.00"),
    "LH-714": D("1950000.00"),
}

EXACT_EVIDENCE_COLUMNS = {
    "DD-101": "personnel_DD_101",
    "DD-102": "personnel_DD_102",
    "DD-110": "tool_DD_110",
    "HC-601": "tool_HC_601",
    "HC-610": "wiper_trips",
    "HC-620": "tool_HC_620",
    "HC-630": "clean_out_runs",
    "HC-640": "tool_HC_640",
    "LW-401": "personnel_LW_401",
    "LW-413": "pressure_points",
    "MW-301": "personnel_MW_301",
    "MW-310": "tool_MW_310",
    "MW-320": "tool_MW_320",
    "MW-330": "tool_MW_330",
    "PD-201": "personnel_PD_201",
    "PD-220": "tool_PD_220",
    "PD-230": "tool_PD_230",
    "RM-511": "tool_RM_511",
    "RM-520": "tool_RM_520",
}


@dataclass(frozen=True)
class EventSets:
    dd111_reports: frozenset[str]
    lw420_reports: frozenset[str]
    first_report_by_well: dict[str, str]
    last_report_by_well: dict[str, str]
    lwd_wells: frozenset[str]


def parse_date(series: pd.Series, fmt: str | None = None) -> pd.Series:
    return pd.to_datetime(series, format=fmt, errors="coerce")


def load_inputs(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    invoices = pd.read_csv(root / "drilling_services/invoices/invoices.csv", keep_default_na=False)
    lines = pd.read_csv(root / "drilling_services/invoices/invoice_lines.csv", keep_default_na=False)
    reports = pd.read_csv(root / "artifacts/parsed/drilling_reports.csv", keep_default_na=False)

    invoices["invoice_date_dt"] = parse_date(invoices["invoice_date"], "%d-%b-%Y")
    invoices["period_start_dt"] = parse_date(invoices["period_start"], "%d-%b-%Y")
    invoices["period_end_dt"] = parse_date(invoices["period_end"], "%d-%b-%Y")
    lines["service_date_dt"] = parse_date(lines["service_date"], "%d-%b-%Y")
    reports["report_date_dt"] = parse_date(reports["report_date"])
    reports["run_first_day_dt"] = parse_date(reports["run_first_day"])
    reports["run_last_day_dt"] = parse_date(reports["run_last_day"])

    for column in ["quantity", "unit_rate", "amount", "depth_from_m", "depth_to_m"]:
        lines[column] = pd.to_numeric(lines[column], errors="coerce")
    for column in ["net_amount", "vat_amount", "invoice_total", "adjustment"]:
        invoices[column] = pd.to_numeric(invoices[column], errors="coerce")

    numeric_report_columns = [
        "part_c_present", "part_d_present", "part_e_present", "metres_drilled",
        "circulating_hours", "part_c_gyro_surveys", "pressure_points", "wiper_trips",
        "back_reaming_hours", "clean_out_runs", "lost_tool_hours_on_well",
        *EXACT_EVIDENCE_COLUMNS.values(), "tool_DD_120", "tool_LW_410", "tool_LW_411",
        "tool_LW_412", "tool_RM_511",
    ]
    for column in sorted(set(numeric_report_columns)):
        reports[column] = pd.to_numeric(reports[column], errors="coerce").fillna(0)

    return invoices, lines, reports


def build_event_sets(reports: pd.DataFrame) -> EventSets:
    first_reports = (
        reports.sort_values(["well_name", "report_date_dt", "report_ref"])
        .drop_duplicates("well_name", keep="first")
        .set_index("well_name")["report_ref"]
        .to_dict()
    )
    last_reports = (
        reports.sort_values(["well_name", "report_date_dt", "report_ref"])
        .drop_duplicates("well_name", keep="last")
        .set_index("well_name")["report_ref"]
        .to_dict()
    )

    unique_runs = reports.sort_values("report_date_dt").drop_duplicates(
        ["well_name", "run_number"], keep="first"
    )
    motor_runs = unique_runs[
        unique_runs["tools_in_run_codes"].astype(str).str.contains("DD-110", regex=False)
    ]
    dd111_reports: set[str] = set()
    for run in motor_runs.itertuples(index=False):
        matches = reports[
            reports["well_name"].eq(run.well_name)
            & reports["run_number"].eq(run.run_number)
            & reports["report_date_dt"].eq(run.run_last_day_dt)
        ]
        if not matches.empty:
            dd111_reports.add(str(matches.iloc[0]["report_ref"]))

    lwd_wells = set(
        reports.loc[
            reports[["tool_LW_410", "tool_LW_411", "tool_LW_412"]].max(axis=1).eq(1),
            "well_name",
        ]
    )
    return EventSets(
        dd111_reports=frozenset(dd111_reports),
        lw420_reports=frozenset(reports.loc[reports["part_d_present"].eq(1), "report_ref"]),
        first_report_by_well=first_reports,
        last_report_by_well=last_reports,
        lwd_wells=frozenset(lwd_wells),
    )


def amendment_discount(code: str, service_date: pd.Timestamp) -> Decimal:
    if code not in AMENDMENT_DISCOUNT_CODES:
        return D("1.00")
    if service_date >= pd.Timestamp("2026-07-01"):
        return D("0.93")
    if service_date >= pd.Timestamp("2026-04-01"):
        return D("0.96")
    return D("1.00")


def dd120_historical_base(service_date: pd.Timestamp) -> Decimal:
    if service_date < pd.Timestamp("2025-07-01"):
        return D("384.15")
    if service_date < pd.Timestamp("2026-04-01"):
        return D("398.50")
    monthly = {
        "2026-04": D("406.00"), "2026-05": D("411.50"), "2026-06": D("411.50"),
        "2026-07": D("423.00"), "2026-08": D("429.50"), "2026-09": D("434.00"),
        "2026-10": D("434.00"), "2026-11": D("441.00"), "2026-12": D("447.50"),
    }
    return monthly[service_date.strftime("%Y-%m")]


def base_rate(
    code: str,
    service_date: pd.Timestamp,
    invoice_date: pd.Timestamp,
    *,
    depth_from: Decimal | None = None,
    force_a3: bool = False,
) -> Decimal:
    if code == "PD-210":
        if depth_from is None:
            raise ValueError("PD-210 requires depth_from")
        if depth_from < D("1500"):
            return D("42.35")
        if depth_from < D("3000"):
            return D("58.15")
        if depth_from < D("4500"):
            return D("76.45")
        return D("98.70")

    if code in LOST_REPLACEMENT_SAR:
        raise ValueError("Lost-in-hole rates use replacement_rate")

    rate = BASE_RATES[code]
    if code == "DD-101":
        if service_date >= pd.Timestamp("2026-01-01"):
            rate = D("1916.50")
        if service_date >= EFFECTIVE_DATE_A3 and (force_a3 or invoice_date >= ISSUE_DATE_A3):
            rate = D("1954.00")
    elif code == "DD-120":
        rate = dd120_historical_base(service_date)
        if service_date >= EFFECTIVE_DATE_A3 and (force_a3 or invoice_date >= ISSUE_DATE_A3):
            rate = D("416.00")
    elif code == "DD-121" and service_date >= pd.Timestamp("2025-07-01"):
        rate = D("2984.00")
    elif code == "MW-301":
        if service_date >= pd.Timestamp("2026-07-01"):
            rate = D("1763.00")
        elif service_date >= pd.Timestamp("2026-01-01"):
            rate = D("1708.00")
    elif code == "LW-401" and service_date >= pd.Timestamp("2026-01-01"):
        rate = D("1969.00")
    elif code == "MB-701" and service_date >= pd.Timestamp("2026-07-01"):
        rate = D("19237.00")
    elif code == "HC-601" and service_date >= pd.Timestamp("2025-07-01"):
        published = {
            "2025-07": D("701.50"), "2025-08": D("714.00"), "2025-09": D("722.60"),
            "2025-10": D("719.80"), "2025-11": D("731.00"), "2025-12": D("736.40"),
        }
        rate = published.get(service_date.strftime("%Y-%m"), D("736.40"))

    if code in {"MW-310", "HC-620"}:
        rate = money(rate * RIG_INDEX[service_date.strftime("%Y-%m")] / D("100.00"))
    return rate


def replacement_rate(code: str, service_date: pd.Timestamp, hours: Decimal) -> Decimal:
    fx = FX_HALALAS_PER_USD[service_date.strftime("%Y-%m")]
    converted = money(LOST_REPLACEMENT_SAR[code] * D("100") / fx)
    completed_blocks = int(hours // D("25"))
    depreciation_percent = min(completed_blocks, 50)
    return apply_step(converted, D("1") - D(depreciation_percent) / D("100"))


def expected_rate(
    code: str,
    service_date: pd.Timestamp,
    invoice_date: pd.Timestamp,
    section: str,
    well_class: str,
    status: str,
    depth_from: Decimal | None,
    lost_hours: Decimal,
    *,
    force_a3: bool = False,
) -> Decimal:
    if code in LOST_REPLACEMENT_SAR:
        return replacement_rate(code, service_date, lost_hours)

    rate = base_rate(
        code, service_date, invoice_date, depth_from=depth_from, force_a3=force_a3
    )
    if status == "Standby":
        if code == "DD-121":
            pass
        elif code in FULL_ON_ANY_STATUS:
            pass
        else:
            if code in CLASS_RATED:
                rate = apply_step(rate, CLASS_FACTORS[well_class])
            rate = apply_step(rate, STANDBY_PERCENT.get(code, D("0.00")))
    else:
        if code in SECTION_RATED:
            rate = apply_step(rate, SECTION_FACTORS[section])
        if code in CLASS_RATED:
            rate = apply_step(rate, CLASS_FACTORS[well_class])

    rate = apply_step(rate, amendment_discount(code, service_date))
    return rate


def supported_quantity(row: pd.Series, events: EventSets) -> Decimal:
    code = row["service_code"]
    status = row["evidence_status"]
    report_ref = str(row["report_ref"])
    well = row["evidence_well"]

    if status == "Standby" and code not in FULL_ON_ANY_STATUS and code != "DD-121":
        if STANDBY_PERCENT.get(code, D("0.00")) == ZERO:
            return ZERO
    if status != "Standby" and code == "DD-121":
        return ZERO

    if code in EXACT_EVIDENCE_COLUMNS:
        return D(row[EXACT_EVIDENCE_COLUMNS[code]])
    if code == "DD-120":
        if not D(row["tool_DD_120"]):
            return ZERO
        return max(D(row["circulating_hours"]) - D("1"), D("6"))
    if code == "DD-121":
        return D("1") if status == "Standby" and D(row["tool_DD_120"]) else ZERO
    if code == "DD-130":
        return D(row["part_c_gyro_surveys"]) if D(row["part_c_present"]) else ZERO
    if code in {"LW-410", "LW-411", "LW-412"}:
        tool = D(row[f"tool_{code.replace('-', '_')}"])
        return D(row["metres_drilled"]) * tool
    if code == "RM-510":
        return D(row["metres_drilled"]) * D(row["tool_RM_511"])
    if code == "RM-530":
        return max(D(row["back_reaming_hours"]) - D("1"), ZERO)
    if code == "PD-210":
        start = D(row["depth_from_m"])
        end = D(row["depth_to_m"])
        if end <= start:
            return ZERO
        evidence_start = D(row["depth_start_m"])
        evidence_end = D(row["depth_end_m"])
        if start < evidence_start or end > evidence_end:
            return ZERO
        return end - start
    if code == "DD-111":
        return D("1") if report_ref in events.dd111_reports else ZERO
    if code == "LW-420":
        return D("1") if report_ref in events.lw420_reports else ZERO
    if code in {"DD-140", "MB-701"}:
        return D("1") if events.first_report_by_well.get(well) == report_ref else ZERO
    if code == "MB-702":
        return D("1") if events.last_report_by_well.get(well) == report_ref else ZERO
    if code == "LW-430":
        valid = well in events.lwd_wells and events.last_report_by_well.get(well) == report_ref
        return D("1") if valid else ZERO
    if code in LOST_REPLACEMENT_SAR:
        valid = D(row["part_e_present"]) == D("1") and row["lost_in_hole_code"] == code
        return D("1") if valid else ZERO
    return ZERO


def payable_quantity(code: str, billed: Decimal, supported: Decimal) -> Decimal:
    if billed <= supported:
        return billed
    if code in {"LW-410", "LW-411", "LW-412", "RM-510", "PD-210"}:
        if supported > ZERO and billed <= supported * D("1.01"):
            return billed
    return supported


def choose_duplicate_rejections(merged: pd.DataFrame) -> set[str]:
    candidates = merged[
        merged["service_code"].ne("DS-900")
        & merged["report_date_dt"].notna()
        & merged["report_date_dt"].between(merged["period_start_dt"], merged["period_end_dt"])
        & merged["well_name"].eq(merged["evidence_well"])
    ].copy()
    candidates = candidates[candidates["service_code"].ne("PD-210")]
    candidates = candidates.sort_values(
        ["report_ref", "service_code", "invoice_date_dt", "invoice_no", "line_no"]
    )
    duplicate_mask = candidates.duplicated(["report_ref", "service_code"], keep="first")
    return set(candidates.loc[duplicate_mask, "line_ref"])


def audit_lines(
    invoices: pd.DataFrame,
    lines: pd.DataFrame,
    reports: pd.DataFrame,
    events: EventSets,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    invoice_columns = [
        "invoice_no", "contract_ref", "contractor", "well_name", "rig", "well_class",
        "period_start_dt", "period_end_dt", "invoice_date_dt",
    ]
    report_columns = [
        "report_ref", "well_name", "rig", "report_date_dt", "hole_section", "day_status",
        "depth_start_m", "depth_end_m", "metres_drilled", "circulating_hours",
        "part_c_present", "part_c_gyro_surveys", "part_d_present", "part_e_present",
        "pressure_points", "wiper_trips", "back_reaming_hours", "clean_out_runs",
        "lost_in_hole_code", "lost_tool_hours_on_well", "parse_ok", "parse_errors",
        *sorted(set(EXACT_EVIDENCE_COLUMNS.values())), "tool_DD_120", "tool_LW_410",
        "tool_LW_411", "tool_LW_412", "tool_RM_511",
    ]
    inv = invoices[invoice_columns].rename(
        columns={"well_name": "invoice_well", "rig": "invoice_rig"}
    )
    rep = reports[report_columns].rename(
        columns={
            "well_name": "evidence_well", "rig": "evidence_rig",
            "hole_section": "evidence_section", "day_status": "evidence_status",
        }
    )
    merged = lines.merge(inv, on="invoice_no", how="left", validate="many_to_one")
    merged = merged.merge(rep, on="report_ref", how="left", validate="many_to_one")
    duplicate_rejections = choose_duplicate_rejections(merged)

    results: list[dict[str, Any]] = []
    for row in merged.itertuples(index=False):
        data = row._asdict()
        code = data["service_code"]
        if code == "DS-900":
            continue
        errors: set[str] = set()
        evidence_date = data["report_date_dt"]
        invoice_date = data["invoice_date_dt"]
        billed_qty = D(data["quantity"])
        billed_rate = D(data["unit_rate"])
        billed_amount = D(data["amount"])

        if pd.isna(evidence_date):
            errors.add("missing_evidence")
            supported = ZERO
            rate = ZERO
        else:
            if data["service_date_dt"] != evidence_date:
                errors.add("service_date_mismatch")
            if data["well_name"] != data["evidence_well"] or data["invoice_well"] != data["evidence_well"]:
                errors.add("well_mismatch")
            if data["invoice_rig"] != data["evidence_rig"]:
                errors.add("rig_mismatch")
            if data["hole_section"] != data["evidence_section"]:
                errors.add("section_mismatch")
            if data["day_status"] != data["evidence_status"]:
                errors.add("status_mismatch")
            period_valid = data["period_start_dt"] <= evidence_date <= data["period_end_dt"]
            if not period_valid:
                errors.add("outside_invoice_period")
            term_valid = CONTRACT_START <= evidence_date <= CONTRACT_END
            if not term_valid:
                errors.add("outside_contract_term")
            expected_unit = EXPECTED_UNITS.get(code)
            unit_valid = expected_unit == data["unit"]
            if not unit_valid:
                errors.add("wrong_unit")

            supported = supported_quantity(pd.Series(data), events)
            if data["line_ref"] in duplicate_rejections:
                supported = ZERO
                errors.add("duplicate_charge")
            if not period_valid or not term_valid or not unit_valid:
                supported = ZERO
            payable = payable_quantity(code, billed_qty, supported)
            if payable != billed_qty:
                errors.add("unsupported_quantity")

            depth_from = None if pd.isna(data["depth_from_m"]) else D(data["depth_from_m"])
            try:
                rate = expected_rate(
                    code=code,
                    service_date=evidence_date,
                    invoice_date=invoice_date,
                    section=data["evidence_section"],
                    well_class=data["well_class"],
                    status=data["evidence_status"],
                    depth_from=depth_from,
                    lost_hours=D(data["lost_tool_hours_on_well"]),
                )
            except (KeyError, ValueError):
                rate = ZERO
                errors.add("unpriceable_line")

        payable = payable_quantity(code, billed_qty, supported)
        expected_amount = money(payable * rate)
        billed_arithmetic = money(billed_qty * billed_rate)
        if billed_arithmetic != money(billed_amount):
            errors.add("line_arithmetic")
        if billed_rate != rate:
            errors.add("wrong_rate")
        if money(billed_amount) != expected_amount:
            errors.add("wrong_line_amount")

        results.append(
            {
                "line_ref": data["line_ref"], "invoice_no": data["invoice_no"],
                "line_no": data["line_no"], "service_code": code,
                "service_date_billed": data["service_date"],
                "evidence_date": "" if pd.isna(evidence_date) else evidence_date.date().isoformat(),
                "report_ref": data["report_ref"], "billed_quantity": str(billed_qty),
                "supported_quantity": str(supported), "payable_quantity": str(payable),
                "billed_rate": decimal_text(billed_rate), "expected_rate": decimal_text(rate),
                "billed_amount": decimal_text(billed_amount),
                "expected_amount": decimal_text(expected_amount),
                "errors": "|".join(sorted(errors)), "error_count": len(errors),
            }
        )

    return pd.DataFrame(results), merged


def calculate_a3_adjustment(
    line_audit: pd.DataFrame,
    merged: pd.DataFrame,
) -> Decimal:
    lookup = line_audit.set_index("line_ref")
    total = ZERO
    historical = merged[
        merged["service_code"].isin(["DD-101", "DD-120"])
        & merged["report_date_dt"].ge(EFFECTIVE_DATE_A3)
        & merged["invoice_date_dt"].lt(ISSUE_DATE_A3)
    ]
    for row in historical.itertuples(index=False):
        audited = lookup.loc[row.line_ref]
        quantity = D(audited["payable_quantity"])
        if quantity == ZERO:
            continue
        old_rate = D(audited["expected_rate"])
        new_rate = expected_rate(
            code=row.service_code,
            service_date=row.report_date_dt,
            invoice_date=row.invoice_date_dt,
            section=row.evidence_section,
            well_class=row.well_class,
            status=row.evidence_status,
            depth_from=None,
            lost_hours=ZERO,
            force_a3=True,
        )
        total += money(quantity * new_rate) - money(quantity * old_rate)
    return money(total)


def categories_from_line_errors(errors: Iterable[str]) -> set[str]:
    mapping = {
        "missing_evidence": "EVIDENCE", "unsupported_quantity": "QUANTITY",
        "duplicate_charge": "DUPLICATE", "wrong_rate": "RATE",
        "line_arithmetic": "ARITHMETIC", "wrong_line_amount": "AMOUNT",
        "service_date_mismatch": "DATE", "outside_invoice_period": "PERIOD",
        "outside_contract_term": "TERM", "wrong_unit": "UNIT",
        "well_mismatch": "IDENTITY", "rig_mismatch": "IDENTITY",
        "section_mismatch": "CONTENT", "status_mismatch": "CONTENT",
        "unpriceable_line": "QUERY",
    }
    return {mapping[e] for e in errors if e in mapping}


def audit_invoices(
    invoices: pd.DataFrame,
    lines: pd.DataFrame,
    line_audit: pd.DataFrame,
    merged: pd.DataFrame,
) -> tuple[pd.DataFrame, Decimal, str]:
    expected_by_line = line_audit.set_index("line_ref")["expected_amount"].map(D)
    line_errors_by_invoice: dict[str, set[str]] = defaultdict(set)
    for row in line_audit.itertuples(index=False):
        if row.errors:
            line_errors_by_invoice[row.invoice_no].update(row.errors.split("|"))

    a3_adjustment = calculate_a3_adjustment(line_audit, merged)
    target_row = invoices[invoices["invoice_date_dt"].ge(ISSUE_DATE_A3)].sort_values(
        ["invoice_date_dt", "invoice_no"]
    ).iloc[0]
    adjustment_invoice = str(target_row["invoice_no"])

    results: list[dict[str, Any]] = []
    for invoice in invoices.itertuples(index=False):
        invoice_lines = lines[lines["invoice_no"].eq(invoice.invoice_no)]
        service_lines = invoice_lines[invoice_lines["service_code"].ne("DS-900")]
        service_subtotal = sum(
            (expected_by_line[line_ref] for line_ref in service_lines["line_ref"]), ZERO
        )
        expected_discount = ZERO
        if service_subtotal > D("250000.00"):
            expected_discount = -money((service_subtotal - D("250000.00")) * D("0.04"))

        expected_adjustment = a3_adjustment if invoice.invoice_no == adjustment_invoice else ZERO
        expected_net = money(service_subtotal + expected_discount + expected_adjustment)
        expected_vat = money(expected_net * D("0.15"))
        expected_total = money(expected_net + expected_vat)

        actual_ds = invoice_lines[invoice_lines["service_code"].eq("DS-900")]
        actual_discount = sum((D(v) for v in actual_ds["amount"]), ZERO)
        categories = categories_from_line_errors(line_errors_by_invoice[invoice.invoice_no])
        details: list[str] = []
        if actual_discount != expected_discount or len(actual_ds) != (1 if expected_discount else 0):
            categories.add("DISCOUNT")
            details.append(f"discount billed={decimal_text(actual_discount)} expected={decimal_text(expected_discount)}")
        if D(invoice.adjustment) != expected_adjustment:
            categories.add("ADJUSTMENT")
            details.append(f"adjustment billed={decimal_text(D(invoice.adjustment))} expected={decimal_text(expected_adjustment)}")
        if money(D(invoice.net_amount)) != expected_net:
            categories.add("NET")
        if money(D(invoice.vat_amount)) != expected_vat:
            categories.add("VAT")
        if money(D(invoice.invoice_total)) != expected_total:
            categories.add("TOTAL")

        if invoice.contract_ref != "DDS-2025-118" or invoice.contractor != "Meridian Downhole Services Ltd":
            categories.add("IDENTITY")
        if pd.isna(invoice.invoice_date_dt) or pd.isna(invoice.period_end_dt):
            categories.add("DATE")
        else:
            if invoice.invoice_date_dt < invoice.period_end_dt:
                categories.add("DATE")
            if (invoice.invoice_date_dt - invoice.period_end_dt).days > 30:
                categories.add("DATE")

        results.append(
            {
                "invoice_id": invoice.invoice_no,
                "flagged": 1 if categories else 0,
                "error_category": "|".join(sorted(categories)),
                "expected_total_cents": cents(expected_total),
                "billed_total_cents": cents(D(invoice.invoice_total)),
                "confidence": "0.99",
                "expected_service_subtotal": decimal_text(service_subtotal),
                "expected_discount": decimal_text(expected_discount),
                "expected_adjustment": decimal_text(expected_adjustment),
                "expected_net": decimal_text(expected_net),
                "expected_vat": decimal_text(expected_vat),
                "expected_total": decimal_text(expected_total),
                "billed_total": decimal_text(D(invoice.invoice_total)),
                "details": " | ".join(details),
            }
        )

    return pd.DataFrame(results), a3_adjustment, adjustment_invoice


def write_outputs(
    root: Path,
    line_audit: pd.DataFrame,
    invoice_audit: pd.DataFrame,
    adjustment: Decimal,
    adjustment_invoice: str,
) -> None:
    output_dir = root / "artifacts/audit"
    output_dir.mkdir(parents=True, exist_ok=True)
    line_audit.to_csv(output_dir / "drilling_line_audit.csv", index=False)
    invoice_audit.to_csv(output_dir / "drilling_invoice_audit.csv", index=False)
    submission_columns = [
        "invoice_id", "flagged", "error_category", "expected_total_cents",
        "billed_total_cents", "confidence",
    ]
    invoice_audit[submission_columns].to_csv(
        output_dir / "drilling_submission.csv", index=False
    )

    flagged = invoice_audit[invoice_audit["flagged"].eq(1)]
    category_counts: dict[str, int] = defaultdict(int)
    for value in flagged["error_category"]:
        for category in str(value).split("|"):
            if category:
                category_counts[category] += 1
    summary = {
        "invoice_count": int(len(invoice_audit)),
        "flagged_invoice_count": int(len(flagged)),
        "clean_invoice_count": int(len(invoice_audit) - len(flagged)),
        "line_count": int(len(line_audit)),
        "line_issue_count": int(line_audit["error_count"].gt(0).sum()),
        "a3_adjustment": decimal_text(adjustment),
        "a3_adjustment_invoice": adjustment_invoice,
        "category_invoice_counts": dict(sorted(category_counts.items())),
    }
    (output_dir / "drilling_audit_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1],
        help="Project root containing drilling_services/ and artifacts/",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    invoices, lines, reports = load_inputs(root)
    events = build_event_sets(reports)
    line_audit, merged = audit_lines(invoices, lines, reports, events)
    invoice_audit, adjustment, adjustment_invoice = audit_invoices(
        invoices, lines, line_audit, merged
    )
    write_outputs(root, line_audit, invoice_audit, adjustment, adjustment_invoice)

    print(f"Audited drilling lines: {len(line_audit)}")
    print(f"Audited drilling invoices: {len(invoice_audit)}")
    print(f"Flagged invoices: {int(invoice_audit['flagged'].sum())}")
    print(f"A3 adjustment: {decimal_text(adjustment)}")
    print(f"A3 adjustment invoice: {adjustment_invoice}")
    print(f"Outputs: {root / 'artifacts/audit'}")


if __name__ == "__main__":
    main()
