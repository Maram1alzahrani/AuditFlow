#!/usr/bin/env python3
"""Audit CW-2025-0417-CIV applications against the contract and site records.

The implementation is deterministic, uses Decimal arithmetic, preserves the
contract's two different rounding rules, and emits both evidence-rich audit
files and a submission-shaped CSV.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ZERO = Decimal("0.00")
HALALA = Decimal("0.01")
CONTRACT_START = pd.Timestamp("2025-01-05")
ORIGINAL_COMPLETION = pd.Timestamp("2025-09-27")
CONTRACT_END = pd.Timestamp("2026-09-30")
A3_EFFECTIVE = pd.Timestamp("2025-11-01")
A3_ISSUED = pd.Timestamp("2026-05-12")


def D(value: Any) -> Decimal:
    if value is None or value == "" or pd.isna(value):
        return ZERO
    return Decimal(str(value))


def half_even(value: Decimal) -> Decimal:
    return value.quantize(HALALA, rounding=ROUND_HALF_EVEN)


def half_up(value: Decimal) -> Decimal:
    return value.quantize(HALALA, rounding=ROUND_HALF_UP)


def floor_halala(value: Decimal) -> Decimal:
    return value.quantize(HALALA, rounding=ROUND_DOWN)


def cents(value: Decimal) -> int:
    return int((half_up(value) * 100).to_integral_exact())


def money_text(value: Decimal) -> str:
    return format(half_up(value), "f")


BASE_RATES = {
    "A.11.010": D("3.85"), "A.11.020": D("12.40"), "A.11.030": D("148.00"),
    "A.12.010": D("21.50"), "A.12.020": D("34.80"), "A.12.030": D("47.60"),
    "A.12.040": D("69.20"), "A.12.050": D("52.40"), "A.12.060": D("6.90"),
    "A.13.010": D("18.90"), "A.13.020": D("6.40"), "A.13.030": D("9.80"),
    "A.14.010": D("53.20"), "A.14.020": D("22.40"), "A.14.030": D("14.60"),
    "A.15.010": D("31.80"), "A.15.020": D("49.50"), "A.16.010": D("1480.00"),
    "B.21.010": D("29.60"), "B.21.020": D("415.00"), "B.21.030": D("389.00"),
    "B.21.040": D("448.00"), "B.21.050": D("296.00"), "B.22.010": D("74.50"),
    "B.22.020": D("91.80"), "B.22.030": D("42.60"), "B.23.010": D("4120.00"),
    "B.23.020": D("38.40"), "B.24.010": D("67.40"), "B.25.010": D("219.00"),
    "B.26.010": D("17.20"), "B.27.010": D("89.50"),
    "C.31.010": D("86.20"), "C.31.020": D("214.00"), "C.31.030": D("54.80"),
    "C.31.040": D("73.10"), "C.32.010": D("1860.00"), "C.32.020": D("287.00"),
    "C.32.030": D("3120.00"), "C.32.040": D("423.00"), "C.33.010": D("59.10"),
    "C.34.010": D("965.00"), "C.35.010": D("9.40"),
    "D.41.010": D("41.80"), "D.41.020": D("63.50"), "D.41.030": D("89.40"),
    "D.41.040": D("32.60"), "D.41.050": D("6.20"), "D.42.010": D("71.20"),
    "D.42.020": D("64.80"), "D.42.030": D("39.40"), "D.43.010": D("14.80"),
    "D.43.020": D("42.60"), "D.44.010": D("31.80"),
    "E.51.010": D("246.00"), "E.51.020": D("684.00"), "E.51.030": D("312.00"),
    "E.52.010": D("478.00"), "E.53.010": D("389.00"), "E.54.010": D("876.00"),
}

EXPECTED_UNITS = {
    "A.11.010": "m2", "A.11.020": "m2", "A.11.030": "no.", "A.12.010": "m3",
    "A.12.020": "m3", "A.12.030": "m3", "A.12.040": "m3", "A.12.050": "m3",
    "A.12.060": "m2", "A.13.010": "m3", "A.13.020": "m3", "A.13.030": "m3",
    "A.14.010": "m3", "A.14.020": "m3", "A.14.030": "m2", "A.15.010": "m2",
    "A.15.020": "m2", "A.16.010": "week", "B.21.010": "m2", "B.21.020": "m3",
    "B.21.030": "m3", "B.21.040": "m3", "B.21.050": "m3", "B.22.010": "m2",
    "B.22.020": "m2", "B.22.030": "lm", "B.23.010": "tonne", "B.23.020": "m2",
    "B.24.010": "lm", "B.25.010": "no.", "B.26.010": "m2", "B.27.010": "lm",
    "C.31.010": "lm", "C.31.020": "lm", "C.31.030": "lm", "C.31.040": "lm",
    "C.32.010": "no.", "C.32.020": "no.", "C.32.030": "no.", "C.32.040": "no.",
    "C.33.010": "lm", "C.34.010": "no.", "C.35.010": "lm", "D.41.010": "m2",
    "D.41.020": "m2", "D.41.030": "m2", "D.41.040": "m2", "D.41.050": "m2",
    "D.42.010": "lm", "D.42.020": "lm", "D.42.030": "lm", "D.43.010": "lm",
    "D.43.020": "m2", "D.44.010": "no.", "E.51.010": "hour", "E.51.020": "day",
    "E.51.030": "hour", "E.52.010": "no.", "E.53.010": "day", "E.54.010": "week",
}

ZONE_FACTORS = {
    "Z1 Compound": D("1.00"), "Z2 North Spur": D("1.06"),
    "Z3 Wadi Crossing": D("1.145"), "Z4 Escarpment": D("1.28"),
}
GROUND_FACTORS = {
    "G1 Loose Sand": D("0.94"), "G2 Firm Sabkha": D("1.00"),
    "G3 Cemented Fill": D("1.12"), "G4 Weathered Rock": D("1.375"),
    "G5 Sound Rock": D("1.63"),
}
GROUND_RATED = {
    "A.11.020", "A.12.010", "A.12.020", "A.12.030", "A.12.040", "A.12.050",
    "A.14.020", "A.15.010", "A.15.020", "C.31.010", "C.31.020", "C.31.030",
    "C.32.010", "C.32.030", "C.33.010",
}
NIGHT_UPLIFTS = {
    "A.12.020": D("1.18"), "A.12.030": D("1.18"), "A.12.040": D("1.18"),
    "A.14.010": D("1.18"), "B.21.020": D("1.22"), "B.21.030": D("1.22"),
    "B.21.040": D("1.22"), "C.31.010": D("1.18"), "C.31.030": D("1.18"),
    "D.41.020": D("1.25"), "D.41.030": D("1.25"), "D.43.010": D("1.25"),
    "D.43.020": D("1.25"),
}
REST_UPLIFT_CODES = {"B.21.020", "B.21.030", "B.21.040", "D.41.030"}
SURVEYED_CODES = {"B.23.010", "B.23.020", "E.52.010"}
REQUIRED_RECORD_TYPES = {
    "A.12.030": "DX", "A.12.040": "DX", "A.14.010": "CT", "A.16.010": "DW",
    "B.21.020": "PR", "B.21.030": "PR", "B.21.040": "PR", "B.23.010": "JS",
    "B.23.020": "JS", "C.31.020": "PT", "C.32.030": "PT", "C.35.010": "CV",
    "D.41.010": "CT", "D.41.040": "CT", "E.51.010": "MO", "E.51.030": "PS",
    "E.52.010": "JS",
}
DAILY_LIMITS = {
    "A.11.010": D("4500"), "A.12.010": D("1200"), "B.21.020": D("140"),
    "C.32.010": D("6"), "D.41.030": D("3200"), "E.51.020": D("1"),
    "A.13.030": D("800"), "C.32.030": D("3"), "E.53.010": D("2"),
}
SURFACING_CODES = {"D.41.020", "D.41.030", "D.41.050", "D.43.010", "D.43.020"}
USD_CODES = {"B.23.020", "B.25.010", "C.32.040"}
INDEXED_CODES = {"C.31.010", "D.41.030"}
DISCOUNT_CODES = {"C.32.030", "C.32.010", "D.41.020", "B.23.010"}

SITE_INDEX = {
    "2025-01": D("100.00"), "2025-02": D("100.40"), "2025-03": D("101.10"),
    "2025-04": D("101.80"), "2025-05": D("102.60"), "2025-06": D("103.90"),
    "2025-07": D("104.70"), "2025-08": D("104.20"), "2025-09": D("105.30"),
    "2025-10": D("106.80"), "2025-11": D("107.40"), "2025-12": D("108.10"),
    "2026-01": D("109.60"), "2026-02": D("110.20"), "2026-03": D("109.80"),
    "2026-04": D("111.50"), "2026-05": D("112.30"), "2026-06": D("113.10"),
    "2026-07": D("112.40"), "2026-08": D("113.80"), "2026-09": D("114.60"),
    "2026-10": D("115.20"), "2026-11": D("115.90"), "2026-12": D("116.50"),
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

# Each tuple is (exclusive upper cumulative quantity or None, percentage).
BANDS = {
    "A.12.010": [(D("4000"), D("1.00")), (D("16000"), D("0.96")), (None, D("0.93"))],
    "A.12.020": [(D("1500"), D("1.00")), (D("6000"), D("0.97")), (None, D("0.94"))],
    "A.13.010": [(D("5000"), D("1.00")), (D("20000"), D("0.94")), (None, D("0.90"))],
    "A.14.010": [(D("2000"), D("1.00")), (D("8000"), D("0.95")), (None, D("0.91"))],
    "B.22.010": [(D("1200"), D("1.00")), (D("4800"), D("0.96")), (None, D("0.93"))],
    "B.23.010": [(D("60"), D("1.00")), (D("240"), D("0.97")), (None, D("0.94"))],
    "D.41.010": [(D("4500"), D("1.00")), (D("18000"), D("0.95")), (None, D("0.92"))],
    "D.41.040": [(D("3500"), D("1.00")), (D("14500"), D("0.95")), (None, D("0.92"))],
}


def parse_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def load_inputs(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    apps = pd.read_csv(root / "civilwork/invoices/applications.csv", keep_default_na=False)
    lines = pd.read_csv(root / "civilwork/invoices/application_lines.csv", keep_default_na=False)
    records = pd.read_csv(root / "artifacts/parsed/civil_records.csv", keep_default_na=False)
    for c in ["period_from", "period_to", "application_date"]:
        apps[c + "_dt"] = parse_dates(apps[c])
    lines["work_date_dt"] = parse_dates(lines["work_date"])
    records["record_date_dt"] = parse_dates(records["record_date"])
    records["week_beginning_dt"] = parse_dates(records["week_beginning"])
    for c in ["quantity", "rate_applied", "amount"]:
        lines[c] = pd.to_numeric(lines[c], errors="coerce")
    for c in ["application_total", "retention", "net_payable", "adjustment", "retention_released"]:
        apps[c] = pd.to_numeric(apps[c], errors="coerce")
    for c in ["quantity", "days_on_count", "week_eligible", "signatures_complete", "parse_ok"]:
        records[c] = pd.to_numeric(records[c], errors="coerce").fillna(0)
    return apps, lines, records


def contract_year(date: pd.Timestamp) -> int:
    return 1 if date < pd.Timestamp("2026-01-05") else 2


def base_rate(code: str, work_date: pd.Timestamp, app_date: pd.Timestamp, *, force_a3: bool = False) -> Decimal:
    rate = BASE_RATES[code]
    month = work_date.strftime("%Y-%m")
    if code in INDEXED_CODES:
        rate = half_even(rate * SITE_INDEX[month] / D("100"))
    elif code in USD_CODES:
        rate = half_even(rate * FX_HALALAS_PER_USD[month] / D("100"))

    if code == "B.23.010":
        if work_date >= pd.Timestamp("2025-10-01"):
            rate = D("4450.00")
        elif work_date >= pd.Timestamp("2025-05-01"):
            rate = D("4385.00")
    elif code == "B.21.020" and work_date >= pd.Timestamp("2025-05-01"):
        rate = D("431.50")
    elif code == "A.16.010" and work_date >= pd.Timestamp("2025-05-01"):
        rate = D("1524.00")
    elif code == "D.41.020":
        monthly = {
            "2025-05": D("214.50"), "2025-06": D("219.80"), "2025-07": D("226.40"),
            "2025-08": D("223.10"), "2025-09": D("220.50"), "2025-10": D("220.50"),
            "2025-11": D("220.50"),
        }
        if work_date >= pd.Timestamp("2025-12-01"):
            rate = D("228.00")
        elif month in monthly:
            rate = monthly[month]
    elif code == "E.54.010":
        if work_date >= pd.Timestamp("2026-04-01"):
            monthly = {
                "2026-04": D("976.00"), "2026-05": D("991.00"), "2026-06": D("1013.00"),
                "2026-07": D("1038.00"), "2026-08": D("1038.00"), "2026-09": D("1052.00"),
            }
            rate = monthly.get(month, D("1052.00"))
        elif work_date >= pd.Timestamp("2025-10-01"):
            rate = D("948.00")

    a3_available = force_a3 or app_date >= A3_ISSUED
    if a3_available and work_date >= A3_EFFECTIVE:
        if code == "C.32.010":
            rate = D("1984.00")
        elif code == "A.14.010":
            rate = D("56.80")
    return rate


def discount_factor(code: str, work_date: pd.Timestamp) -> Decimal:
    if code not in DISCOUNT_CODES:
        return D("1.00")
    if work_date >= pd.Timestamp("2026-04-01"):
        return D("0.92")
    if work_date >= pd.Timestamp("2025-12-01"):
        return D("0.95")
    return D("1.00")


def pre_band_rate(
    code: str, work_date: pd.Timestamp, app_date: pd.Timestamp, zone: str,
    ground: str, night_work: bool, *, force_a3: bool = False,
) -> Decimal:
    rate = base_rate(code, work_date, app_date, force_a3=force_a3)
    if not code.startswith("E."):
        rate *= ZONE_FACTORS[zone]
    if code in GROUND_RATED:
        effective_ground = "G2 Firm Sabkha" if work_date > ORIGINAL_COMPLETION else ground
        rate *= GROUND_FACTORS[effective_ground]
    is_rest_day = work_date.weekday() in {4, 5}  # Friday and Saturday
    if is_rest_day and code in REST_UPLIFT_CODES:
        rate *= D("1.35")
    elif night_work and code in NIGHT_UPLIFTS and ZONE_FACTORS.get(zone, D("1")) <= D("1.1"):
        rate *= NIGHT_UPLIFTS[code]
    return rate


def rate_with_final_factors(pre_rate: Decimal, band_factor: Decimal, discount: Decimal) -> Decimal:
    return half_up(pre_rate * band_factor * discount)


def band_parts(code: str, prior: Decimal, quantity: Decimal) -> list[tuple[Decimal, Decimal]]:
    if code not in BANDS:
        return [(quantity, D("1.00"))]
    remaining = quantity
    cursor = prior
    parts: list[tuple[Decimal, Decimal]] = []
    for upper, factor in BANDS[code]:
        if remaining <= ZERO:
            break
        if upper is None:
            take = remaining
        else:
            available = max(upper - cursor, ZERO)
            take = min(remaining, available)
        if take > ZERO:
            parts.append((take, factor))
            remaining -= take
            cursor += take
    return parts


def evidence_supported_quantity(row: pd.Series) -> tuple[Decimal, set[str]]:
    errors: set[str] = set()
    billed = D(row["quantity"])
    code = row["item_code"]
    if code not in REQUIRED_RECORD_TYPES:
        return billed, errors
    if not row["record_ref"] or pd.isna(row["record_type"]) or not row["record_type"]:
        errors.add("missing_required_record")
        return ZERO, errors
    if row["record_type"] != REQUIRED_RECORD_TYPES[code] or row["inferred_item_code"] != code:
        errors.add("wrong_record_type_or_item")
        return ZERO, errors
    if not D(row["parse_ok"]) or not D(row["signatures_complete"]):
        errors.add("invalid_record")
        return ZERO, errors
    if row["site"] != row["record_area"]:
        errors.add("record_area_mismatch")
        return ZERO, errors
    if code == "A.16.010":
        start = row["week_beginning_dt"]
        if pd.isna(start) or not D(row["week_eligible"]) or not (start <= row["work_date_dt"] <= start + pd.Timedelta(days=6)):
            errors.add("record_date_mismatch")
            return ZERO, errors
    elif row["work_date_dt"] != row["record_date_dt"]:
        errors.add("record_date_mismatch")
        return ZERO, errors
    supported = D(row["record_quantity"])
    if billed <= supported:
        return billed, errors
    if code in SURVEYED_CODES and supported > ZERO and billed <= supported * D("1.02"):
        return billed, errors
    errors.add("unsupported_quantity")
    return supported, errors


def prepare_merged(apps: pd.DataFrame, lines: pd.DataFrame, records: pd.DataFrame) -> pd.DataFrame:
    app_cols = [
        "application_no", "contract_ref", "subcontractor", "site", "site_zone",
        "period_from_dt", "period_to_dt", "application_date_dt",
    ]
    app = apps[app_cols].rename(columns={"site": "app_site", "site_zone": "app_zone"})
    record_cols = [
        "record_ref", "record_type", "area", "record_date_dt", "week_beginning_dt",
        "week_eligible", "ground_class", "inferred_item_code", "quantity",
        "unit", "signatures_complete", "parse_ok",
    ]
    rec = records[record_cols].rename(columns={
        "area": "record_area", "ground_class": "record_ground", "quantity": "record_quantity",
        "unit": "record_unit",
    })
    merged = lines.merge(app, on="application_no", how="left", validate="many_to_one")
    merged = merged.merge(rec, on="record_ref", how="left", validate="many_to_one")
    return merged


def duplicate_rejections(merged: pd.DataFrame) -> set[str]:
    ordered = merged.sort_values(
        ["item_code", "site", "work_date_dt", "application_date_dt", "application_no", "line_no"]
    )
    mask = ordered.duplicated(["item_code", "site", "work_date_dt"], keep="first")
    return set(ordered.loc[mask, "line_ref"])


def reused_record_rejections(merged: pd.DataFrame) -> set[str]:
    required = merged[
        merged["item_code"].isin(REQUIRED_RECORD_TYPES)
        & merged["record_ref"].ne("")
        & merged.apply(
            lambda r: r["record_type"] == REQUIRED_RECORD_TYPES.get(r["item_code"])
            and r["inferred_item_code"] == r["item_code"],
            axis=1,
        )
    ]
    ordered = required.sort_values(["record_ref", "application_date_dt", "application_no", "line_no"])
    mask = ordered.duplicated("record_ref", keep="first")
    return set(ordered.loc[mask, "line_ref"])


def exclusion_rejections(merged: pd.DataFrame) -> set[str]:
    fills = merged[merged["item_code"].eq("A.14.010")][["site", "work_date_dt"]]
    by_site: dict[str, list[pd.Timestamp]] = defaultdict(list)
    for row in fills.itertuples(index=False):
        by_site[row.site].append(row.work_date_dt)
    rejected: set[str] = set()
    for row in merged[merged["item_code"].eq("A.14.020")].itertuples(index=False):
        if any(d <= row.work_date_dt <= d + pd.Timedelta(days=2) for d in by_site[row.site]):
            rejected.add(row.line_ref)
    return rejected


def traffic_rejections(merged: pd.DataFrame) -> set[str]:
    surfaced = set(
        zip(
            merged.loc[merged["item_code"].isin(SURFACING_CODES), "site"],
            merged.loc[merged["item_code"].isin(SURFACING_CODES), "work_date_dt"],
        )
    )
    return {
        row.line_ref for row in merged[merged["item_code"].eq("E.51.020")].itertuples(index=False)
        if (row.site, row.work_date_dt) in surfaced
    }


def audit_lines(
    apps: pd.DataFrame, lines: pd.DataFrame, records: pd.DataFrame, *, force_a3: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    merged = prepare_merged(apps, lines, records)
    duplicates = duplicate_rejections(merged)
    reused = reused_record_rejections(merged)
    exclusions = exclusion_rejections(merged)
    traffic = traffic_rejections(merged)

    provisional: dict[str, dict[str, Any]] = {}
    for _, row in merged.iterrows():
        errors: set[str] = set()
        billed = D(row["quantity"])
        supported, evidence_errors = evidence_supported_quantity(row)
        errors.update(evidence_errors)
        code = row["item_code"]
        date = row["work_date_dt"]
        if row["line_ref"] in duplicates:
            supported = ZERO
            errors.add("duplicate_measurement")
        if row["line_ref"] in reused:
            supported = ZERO
            errors.add("reused_record")
        if row["line_ref"] in exclusions:
            supported = ZERO
            errors.add("mutually_exclusive_item")
        if row["line_ref"] in traffic:
            supported = ZERO
            errors.add("traffic_management_excluded")
        if code not in BASE_RATES:
            supported = ZERO
            errors.add("unknown_item")
        if EXPECTED_UNITS.get(code) != row["unit"]:
            supported = ZERO
            errors.add("wrong_unit")
        if pd.isna(date) or not (CONTRACT_START <= date <= CONTRACT_END):
            supported = ZERO
            errors.add("outside_contract_term")
        if pd.isna(row["period_from_dt"]) or not (row["period_from_dt"] <= date <= row["period_to_dt"]):
            supported = ZERO
            errors.add("outside_application_period")
        if row["site"] != row["app_site"] or row["site_zone"] != row["app_zone"]:
            errors.add("application_location_mismatch")
        if code in GROUND_RATED and date <= ORIGINAL_COMPLETION and row["ground_class"] not in GROUND_FACTORS:
            supported = ZERO
            errors.add("missing_ground_class")
        record_ground_present = pd.notna(row["record_ground"]) and bool(row["record_ground"])
        if code in GROUND_RATED and record_ground_present and date <= ORIGINAL_COMPLETION:
            # Parsed records store the class code (for example "G4"), while
            # invoice lines carry the full label ("G4 Weathered Rock").
            if not str(row["ground_class"]).startswith(str(row["record_ground"])):
                errors.add("ground_class_mismatch")
                supported = ZERO
        if code in DAILY_LIMITS and supported > DAILY_LIMITS[code]:
            supported = DAILY_LIMITS[code]
            errors.add("daily_limit_exceeded")
        if supported != billed and "unsupported_quantity" not in errors:
            errors.add("unsupported_quantity")
        provisional[row["line_ref"]] = {"supported": supported, "errors": errors}

    # Contract-year band accumulation is global and follows work date, application, line.
    cumulative: dict[tuple[int, str], Decimal] = defaultdict(lambda: ZERO)
    band_data: dict[str, tuple[Decimal, list[tuple[Decimal, Decimal]]]] = {}
    order = merged.sort_values(["work_date_dt", "application_no", "line_no"])
    for row in order.itertuples(index=False):
        qty = provisional[row.line_ref]["supported"]
        if pd.isna(row.work_date_dt):
            year = 0
        else:
            year = contract_year(row.work_date_dt)
        key = (year, row.item_code)
        prior = cumulative[key]
        parts = band_parts(row.item_code, prior, qty)
        band_data[row.line_ref] = (prior, parts)
        cumulative[key] += qty

    output: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        code = row["item_code"]
        errors = provisional[row["line_ref"]]["errors"]
        payable = provisional[row["line_ref"]]["supported"]
        billed_qty = D(row["quantity"])
        billed_rate = D(row["rate_applied"])
        billed_amount = D(row["amount"])
        prior, parts = band_data[row["line_ref"]]
        expected_amount = ZERO
        component_rates: list[str] = []
        try:
            ground = row["ground_class"] if row["ground_class"] else "G2 Firm Sabkha"
            pre = pre_band_rate(
                code, row["work_date_dt"], row["application_date_dt"], row["site_zone"],
                ground, str(row["night_work"]).upper() == "Y", force_a3=force_a3,
            )
            discount = discount_factor(code, row["work_date_dt"])
            for part_qty, band_factor in parts:
                component_rate = rate_with_final_factors(pre, band_factor, discount)
                component_rates.append(f"{part_qty}@{component_rate}")
                expected_amount += part_qty * component_rate
            expected_amount = half_up(expected_amount)
            expected_rate = rate_with_final_factors(pre, parts[0][1] if parts else D("1"), discount)
        except (KeyError, ValueError, TypeError):
            expected_rate = ZERO
            expected_amount = ZERO
            errors.add("unpriceable_line")

        # A line crossing a cumulative band is expressly the sum of its band
        # parts (Clause 28); no single displayed rate can reproduce that sum.
        if len(parts) <= 1 and half_up(billed_qty * billed_rate) != half_up(billed_amount):
            errors.add("line_arithmetic")
        # For a band-crossing line, the contractual amount is authoritative; a single rate is blended.
        if len(parts) <= 1 and billed_rate != expected_rate:
            errors.add("wrong_rate")
        if half_up(billed_amount) != expected_amount:
            errors.add("wrong_line_amount")

        output.append({
            "line_ref": row["line_ref"], "application_no": row["application_no"],
            "line_no": row["line_no"], "item_code": code, "work_date": row["work_date"],
            "record_ref": row["record_ref"], "billed_quantity": str(billed_qty),
            "supported_quantity": str(payable), "payable_quantity": str(payable),
            "cumulative_quantity_before": str(prior), "rate_components": "|".join(component_rates),
            "billed_rate": money_text(billed_rate), "expected_rate": money_text(expected_rate),
            "billed_amount": money_text(billed_amount), "expected_amount": money_text(expected_amount),
            "errors": "|".join(sorted(errors)), "error_count": len(errors),
        })
    return pd.DataFrame(output), merged


def calculate_a3_adjustment(
    apps: pd.DataFrame, normal_audit: pd.DataFrame, forced_audit: pd.DataFrame, merged: pd.DataFrame,
) -> Decimal:
    normal = normal_audit.set_index("line_ref")
    forced = forced_audit.set_index("line_ref")
    eligible = merged[
        merged["work_date_dt"].ge(A3_EFFECTIVE)
        & merged["application_date_dt"].lt(A3_ISSUED)
        & merged["item_code"].isin({"A.14.010", "C.32.010"})
    ]
    total = ZERO
    for ref in eligible["line_ref"]:
        total += D(forced.loc[ref, "expected_amount"]) - D(normal.loc[ref, "expected_amount"])
    return half_up(total)


def categories_from_errors(errors: Iterable[str]) -> set[str]:
    mapping = {
        "missing_required_record": "EVIDENCE", "wrong_record_type_or_item": "EVIDENCE",
        "invalid_record": "EVIDENCE", "record_area_mismatch": "EVIDENCE",
        "record_date_mismatch": "EVIDENCE", "reused_record": "EVIDENCE",
        "unsupported_quantity": "QUANTITY", "daily_limit_exceeded": "LIMIT",
        "duplicate_measurement": "DUPLICATE", "mutually_exclusive_item": "EXCLUSION",
        "traffic_management_excluded": "EXCLUSION", "wrong_unit": "UNIT",
        "outside_contract_term": "TERM", "outside_application_period": "PERIOD",
        "application_location_mismatch": "IDENTITY", "missing_ground_class": "CONTENT",
        "ground_class_mismatch": "CONTENT", "wrong_rate": "RATE",
        "line_arithmetic": "ARITHMETIC", "wrong_line_amount": "AMOUNT",
        "unpriceable_line": "QUERY", "unknown_item": "QUERY",
    }
    return {mapping[e] for e in errors if e in mapping}


def audit_applications(
    apps: pd.DataFrame, lines: pd.DataFrame, line_audit: pd.DataFrame,
    a3_adjustment: Decimal,
) -> tuple[pd.DataFrame, str, str, Decimal]:
    expected_line = line_audit.set_index("line_ref")["expected_amount"].map(D)
    line_errors: dict[str, set[str]] = defaultdict(set)
    for row in line_audit.itertuples(index=False):
        if row.errors:
            line_errors[row.application_no].update(row.errors.split("|"))
    adjustment_target = str(
        apps[apps["application_date_dt"].ge(A3_ISSUED)]
        .sort_values(["application_date_dt", "application_no"]).iloc[0]["application_no"]
    )
    adjustment_target_date = apps.loc[
        apps["application_no"].eq(adjustment_target), "application_date_dt"
    ].iloc[0]
    same_day_adjustment_candidates = set(
        apps.loc[
            apps["application_date_dt"].eq(adjustment_target_date),
            "application_no",
        ]
    )

    expected_totals: dict[str, Decimal] = {}
    expected_retentions: dict[str, Decimal] = {}
    for app in apps.itertuples(index=False):
        refs = lines.loc[lines["application_no"].eq(app.application_no), "line_ref"]
        total = half_up(sum((expected_line[r] for r in refs), ZERO))
        expected_totals[app.application_no] = total
        expected_retentions[app.application_no] = floor_halala(total * D("0.05"))

    release_row = apps[apps["application_date_dt"].gt(CONTRACT_END)].sort_values(
        ["application_date_dt", "application_no"]
    ).iloc[0]
    release_target = str(release_row["application_no"])
    earlier = apps[
        (apps["application_date_dt"] < release_row["application_date_dt"])
        | ((apps["application_date_dt"] == release_row["application_date_dt"])
           & (apps["application_no"] < release_target))
    ]
    held = sum((expected_retentions[x] for x in earlier["application_no"]), ZERO)
    expected_release = floor_halala(held * D("0.50"))

    output: list[dict[str, Any]] = []
    for app in apps.itertuples(index=False):
        categories = categories_from_errors(line_errors[app.application_no])
        total = expected_totals[app.application_no]
        retention = expected_retentions[app.application_no]
        adjustment = a3_adjustment if app.application_no == adjustment_target else ZERO
        release = expected_release if app.application_no == release_target else ZERO
        net = half_up(total + adjustment - retention + release)
        details: list[str] = []
        if half_up(D(app.application_total)) != total:
            categories.add("SUBTOTAL")
        if floor_halala(D(app.retention)) != retention:
            categories.add("RETENTION")
        if half_up(D(app.adjustment)) != adjustment:
            categories.add("ADJUSTMENT")
            details.append(f"adjustment billed={money_text(D(app.adjustment))} expected={money_text(adjustment)}")
        if half_up(D(app.retention_released)) != release:
            categories.add("RETENTION_RELEASE")
            details.append(f"release billed={money_text(D(app.retention_released))} expected={money_text(release)}")
        if half_up(D(app.net_payable)) != net:
            categories.add("TOTAL")
        if app.contract_ref != "CW-2025-0417-CIV" or app.subcontractor != "Ridgeway Civil Engineering LLC":
            categories.add("IDENTITY")
        if pd.isna(app.application_date_dt) or pd.isna(app.period_to_dt):
            categories.add("DATE")
        else:
            if app.application_date_dt < app.period_to_dt:
                categories.add("DATE")
            if (app.application_date_dt - app.period_to_dt).days > 21:
                categories.add("DATE")

        confidence = "0.90" if app.application_no in same_day_adjustment_candidates else "0.99"
        output.append({
            "invoice_id": app.application_no, "flagged": 1 if categories else 0,
            "error_category": "|".join(sorted(categories)),
            "expected_total_cents": cents(net), "billed_total_cents": cents(D(app.net_payable)),
            "confidence": confidence, "expected_application_total": money_text(total),
            "expected_adjustment": money_text(adjustment), "expected_retention": money_text(retention),
            "expected_retention_released": money_text(release), "expected_net_payable": money_text(net),
            "billed_net_payable": money_text(D(app.net_payable)), "details": " | ".join(details),
        })
    return pd.DataFrame(output), adjustment_target, release_target, expected_release


def write_outputs(
    root: Path, line_audit: pd.DataFrame, app_audit: pd.DataFrame,
    adjustment: Decimal, adjustment_target: str, release_target: str, release: Decimal,
) -> None:
    out = root / "artifacts/audit"
    out.mkdir(parents=True, exist_ok=True)
    line_audit.to_csv(out / "civil_line_audit.csv", index=False)
    app_audit.to_csv(out / "civil_application_audit.csv", index=False)
    submission_cols = [
        "invoice_id", "flagged", "error_category", "expected_total_cents",
        "billed_total_cents", "confidence",
    ]
    app_audit[submission_cols].to_csv(out / "civil_submission.csv", index=False)
    counts: dict[str, int] = defaultdict(int)
    for value in app_audit.loc[app_audit["flagged"].eq(1), "error_category"]:
        for category in str(value).split("|"):
            if category:
                counts[category] += 1
    summary = {
        "application_count": int(len(app_audit)),
        "flagged_application_count": int(app_audit["flagged"].sum()),
        "clean_application_count": int(len(app_audit) - app_audit["flagged"].sum()),
        "line_count": int(len(line_audit)),
        "line_issue_count": int(line_audit["error_count"].gt(0).sum()),
        "a3_adjustment": money_text(adjustment), "a3_adjustment_application": adjustment_target,
        "retention_release": money_text(release), "retention_release_application": release_target,
        "category_application_counts": dict(sorted(counts.items())),
    }
    (out / "civil_audit_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    apps, lines, records = load_inputs(root)
    line_audit, merged = audit_lines(apps, lines, records)
    forced_audit, _ = audit_lines(apps, lines, records, force_a3=True)
    adjustment = calculate_a3_adjustment(apps, line_audit, forced_audit, merged)
    app_audit, adjustment_target, release_target, release = audit_applications(
        apps, lines, line_audit, adjustment
    )
    write_outputs(
        root, line_audit, app_audit, adjustment, adjustment_target, release_target, release
    )
    print(f"Audited civil lines: {len(line_audit)}")
    print(f"Audited civil applications: {len(app_audit)}")
    print(f"Flagged applications: {int(app_audit['flagged'].sum())}")
    print(f"A3 adjustment: {money_text(adjustment)}")
    print(f"A3 adjustment application: {adjustment_target}")
    print(f"Retention release: {money_text(release)}")
    print(f"Retention release application: {release_target}")
    print(f"Outputs: {root / 'artifacts/audit'}")


if __name__ == "__main__":
    main()
