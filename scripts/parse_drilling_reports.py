#!/usr/bin/env python3
"""Parse and validate directional-drilling daily reports.

The parser converts DDR free-text terminology into structured contract
service evidence using Appendix G mappings. It never uses billed prices
or invoice amounts to infer a service.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


CONTRACT_REF = "DDS-2025-118"
VALID_STATUSES = {"Operating", "Standby"}
VALID_HOLE_SECTIONS = {
    '26"',
    '17-1/2"',
    '12-1/4"',
    '8-1/2"',
    '6"',
}

TOOL_TERM_TO_CODE = {
    "mud motor": "DD-110",
    "rotary steerable": "DD-120",
    "circulating sub": "HC-601",
    "drilling jars": "HC-620",
    "float sub": "HC-640",
    "gamma tool": "LW-410",
    "resistivity tool": "LW-411",
    "density-neutron": "LW-412",
    "mwd collar": "MW-310",
    "survey package": "MW-320",
    "real-time link": "MW-330",
    "bit and reamer": "PD-220",
    "hydraulics package": "PD-230",
    "hole opener": "RM-511",
    "stabiliser string": "RM-520",
}

PERSONNEL_TERM_TO_CODE = {
    "directional hand": "DD-101",
    "directional hands": "DD-101",
    "night man": "DD-102",
    "mwd engineer": "MW-301",
    "mwd engineers": "MW-301",
    "logging engineer": "LW-401",
    "logging engineers": "LW-401",
    "performance engineer": "PD-201",
    "performance engineers": "PD-201",
}

LOST_TOOL_TO_CODE = {
    "mud motor": "LH-711",
    "rotary steerable": "LH-712",
    "mwd collar": "LH-713",
    "gamma tool": "LH-714",
}

TOOL_CODES = sorted(set(TOOL_TERM_TO_CODE.values()))
PERSONNEL_CODES = sorted(set(PERSONNEL_TERM_TO_CODE.values()))

BASE_OUTPUT_FIELDS = [
    "report_ref",
    "file_name",
    "contract_ref",
    "well_name",
    "rig",
    "report_date",
    "part_a_present",
    "part_b_present",
    "part_c_present",
    "part_d_present",
    "part_e_present",
    "hole_section",
    "day_status",
    "depth_start_m",
    "depth_end_m",
    "metres_drilled",
    "circulating_hours",
    "bha_run",
    "tools_in_hole_raw",
    "tools_in_hole_codes",
    "unmapped_tools_in_hole",
    "crew_on_tour_raw",
    "personnel_counts",
    "unmapped_personnel",
    "gyro_surveys",
    "pressure_points",
    "wiper_trips",
    "back_reaming_hours",
    "clean_out_runs",
    "run_number",
    "run_first_day",
    "run_last_day",
    "tools_in_run_raw",
    "tools_in_run_codes",
    "unmapped_tools_in_run",
    "run_circulating_hours",
    "metres_logged",
    "metres_reamed",
    "radioactive_source_carried",
    "part_c_gyro_surveys",
    "surveyed_section",
    "source_run",
    "sources_handled",
    "source_handling_certified",
    "lost_in_hole_run",
    "lost_in_hole_tool",
    "lost_in_hole_code",
    "lost_tool_hours_on_well",
    "company_representative",
    "lead_directional_driller",
    "signatures_complete",
    "parse_ok",
    "parse_errors",
]

TOOL_OUTPUT_FIELDS = [
    f"tool_{code.replace('-', '_')}"
    for code in TOOL_CODES
]

PERSONNEL_OUTPUT_FIELDS = [
    f"personnel_{code.replace('-', '_')}"
    for code in PERSONNEL_CODES
]

OUTPUT_FIELDS = (
    BASE_OUTPUT_FIELDS
    + TOOL_OUTPUT_FIELDS
    + PERSONNEL_OUTPUT_FIELDS
)


@dataclass
class ParsedReport:
    report_ref: str
    file_name: str
    contract_ref: str
    well_name: str
    rig: str
    report_date: str
    part_a_present: int
    part_b_present: int
    part_c_present: int
    part_d_present: int
    part_e_present: int
    hole_section: str
    day_status: str
    depth_start_m: int | str
    depth_end_m: int | str
    metres_drilled: int | str
    circulating_hours: int | str
    bha_run: int | str
    tools_in_hole_raw: str
    tools_in_hole_codes: str
    unmapped_tools_in_hole: str
    crew_on_tour_raw: str
    personnel_counts: str
    unmapped_personnel: str
    gyro_surveys: int | str
    pressure_points: int | str
    wiper_trips: int | str
    back_reaming_hours: int | str
    clean_out_runs: int | str
    run_number: int | str
    run_first_day: str
    run_last_day: str
    tools_in_run_raw: str
    tools_in_run_codes: str
    unmapped_tools_in_run: str
    run_circulating_hours: int | str
    metres_logged: int | str
    metres_reamed: int | str
    radioactive_source_carried: str
    part_c_gyro_surveys: int | str
    surveyed_section: str
    source_run: int | str
    sources_handled: str
    source_handling_certified: str
    lost_in_hole_run: int | str
    lost_in_hole_tool: str
    lost_in_hole_code: str
    lost_tool_hours_on_well: int | str
    company_representative: str
    lead_directional_driller: str
    signatures_complete: int
    parse_ok: int
    parse_errors: str
    tool_DD_110: int
    tool_DD_120: int
    tool_HC_601: int
    tool_HC_620: int
    tool_HC_640: int
    tool_LW_410: int
    tool_LW_411: int
    tool_LW_412: int
    tool_MW_310: int
    tool_MW_320: int
    tool_MW_330: int
    tool_PD_220: int
    tool_PD_230: int
    tool_RM_511: int
    tool_RM_520: int
    personnel_DD_101: int
    personnel_DD_102: int
    personnel_LW_401: int
    personnel_MW_301: int
    personnel_PD_201: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse and validate daily drilling reports."
    )
    parser.add_argument(
        "--records-dir",
        type=Path,
        default=Path("drilling_services/records"),
        help="Directory containing DDR .txt files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/parsed"),
        help="Directory for parsed CSV and validation summary.",
    )
    return parser.parse_args()


def clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_field(text: str, label: str) -> str:
    pattern = rf"(?m)^{re.escape(label)}\s*(.*?)\s*$"
    match = re.search(pattern, text)
    return clean_space(match.group(1)) if match else ""


def parse_contract_date(value: str) -> date | None:
    if not value:
        return None

    try:
        return datetime.strptime(value, "%d-%b-%Y").date()
    except ValueError:
        return None


def parse_integer(value: str) -> int | None:
    if not value:
        return None

    try:
        return int(value.strip())
    except ValueError:
        return None


def split_terms(value: str) -> list[str]:
    if not value:
        return []

    return [
        clean_space(term).lower()
        for term in value.split(",")
        if clean_space(term)
    ]


def map_tool_terms(
    value: str,
) -> tuple[set[str], list[str]]:
    codes: set[str] = set()
    unmapped: list[str] = []

    for term in split_terms(value):
        code = TOOL_TERM_TO_CODE.get(term)

        if code:
            codes.add(code)
        else:
            unmapped.append(term)

    return codes, unmapped


def parse_personnel(
    value: str,
) -> tuple[dict[str, int], list[str]]:
    counts = {code: 0 for code in PERSONNEL_CODES}
    unmapped: list[str] = []

    for term in split_terms(value):
        match = re.match(r"^(\d+)\s+(.+)$", term)

        if not match:
            unmapped.append(term)
            continue

        quantity = int(match.group(1))
        description = clean_space(match.group(2)).lower()
        code = PERSONNEL_TERM_TO_CODE.get(description)

        if code:
            counts[code] += quantity
        else:
            unmapped.append(term)

    return counts, unmapped


def expected_file_stem(
    well_name: str,
    report_date: date | None,
) -> str:
    if not well_name or report_date is None:
        return ""

    return f"DDR_{well_name}_{report_date:%Y%m%d}"


def expected_report_ref(
    well_name: str,
    report_date: date | None,
) -> str:
    if not well_name or report_date is None:
        return ""

    well_suffix = well_name.rsplit("-", maxsplit=1)[-1]
    return f"DDR-{well_suffix}-{report_date:%Y%m%d}"


def append_missing_integer_error(
    errors: list[str],
    field_name: str,
    value: int | None,
) -> None:
    if value is None:
        errors.append(f"invalid_or_missing_{field_name}")


def parse_report(path: Path) -> ParsedReport:
    text = path.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []

    first_line = text.splitlines()[0].strip() if text.splitlines() else ""

    report_ref = extract_field(text, "Report:")
    contract_ref = extract_field(text, "Contract:")
    well_name = extract_field(text, "Well:")
    rig = extract_field(text, "Rig:")
    report_date_text = extract_field(text, "Date:")
    report_date = parse_contract_date(report_date_text)

    part_letters = set(
        re.findall(r"(?m)^PART ([A-E])\b", text)
    )

    hole_section = extract_field(text, "Hole section:")
    day_status = extract_field(text, "Status:")
    depth_start = parse_integer(
        extract_field(text, "Depth start (m MD):")
    )
    depth_end = parse_integer(
        extract_field(text, "Depth end (m MD):")
    )
    circulating_hours = parse_integer(
        extract_field(text, "Circulating hours:")
    )
    bha_run = parse_integer(extract_field(text, "BHA run:"))

    tools_in_hole_raw = extract_field(text, "In the hole:")
    crew_on_tour_raw = extract_field(text, "Crew on tour:")

    gyro_surveys = parse_integer(
        extract_field(text, "Gyro surveys:")
    )
    pressure_points = parse_integer(
        extract_field(text, "Pressure points:")
    )
    wiper_trips = parse_integer(
        extract_field(text, "Wiper trips:")
    )
    back_reaming_hours = parse_integer(
        extract_field(text, "Back-reaming hours:")
    )
    clean_out_runs = parse_integer(
        extract_field(text, "Clean-out runs:")
    )

    run_number = parse_integer(extract_field(text, "Run:"))
    run_first_day = parse_contract_date(
        extract_field(text, "Run first day:")
    )
    run_last_day = parse_contract_date(
        extract_field(text, "Run last day:")
    )
    tools_in_run_raw = extract_field(text, "Tools in run:")
    run_circulating_hours = parse_integer(
        extract_field(text, "Run circulating hours:")
    )
    metres_logged = parse_integer(
        extract_field(text, "Metres logged:")
    )
    metres_reamed = parse_integer(
        extract_field(text, "Metres reamed:")
    )
    radioactive_source_carried = extract_field(
        text,
        "Radioactive source carried:",
    )

    part_c_gyro_surveys = parse_integer(
        extract_field(text, "Gyro surveys taken:")
    )
    surveyed_section = extract_field(text, "Surveyed section:")

    source_run = parse_integer(
        extract_field(text, "Source run:")
    )
    sources_handled = extract_field(text, "Sources handled:")
    source_handling_certified = extract_field(
        text,
        "Source handling certified:",
    )

    lost_in_hole_run = parse_integer(
        extract_field(text, "Lost in hole run:")
    )
    lost_in_hole_tool = extract_field(
        text,
        "Lost in hole tool:",
    ).lower()
    lost_tool_hours = parse_integer(
        extract_field(
            text,
            "Circulating hours accumulated on the well:",
        )
    )

    company_representative = extract_field(
        text,
        "Signed (Company Representative):",
    )
    lead_directional_driller = extract_field(
        text,
        "Signed (lead directional driller):",
    )

    tools_in_hole_codes, unmapped_tools_in_hole = (
        map_tool_terms(tools_in_hole_raw)
    )
    tools_in_run_codes, unmapped_tools_in_run = (
        map_tool_terms(tools_in_run_raw)
    )
    personnel_counts, unmapped_personnel = parse_personnel(
        crew_on_tour_raw
    )

    lost_in_hole_code = LOST_TOOL_TO_CODE.get(
        lost_in_hole_tool,
        "",
    )

    if first_line != "DAILY DRILLING REPORT":
        errors.append("unexpected_title")

    if not report_ref:
        errors.append("missing_report_ref")

    if contract_ref != CONTRACT_REF:
        errors.append("contract_reference_mismatch")

    if not well_name:
        errors.append("missing_well_name")

    if not rig:
        errors.append("missing_rig")

    if report_date is None:
        errors.append("invalid_or_missing_report_date")

    expected_stem = expected_file_stem(
        well_name,
        report_date,
    )

    if expected_stem and path.stem != expected_stem:
        errors.append("filename_report_mismatch")

    expected_ref = expected_report_ref(
        well_name,
        report_date,
    )

    if expected_ref and report_ref != expected_ref:
        errors.append("report_reference_mismatch")

    if "A" not in part_letters:
        errors.append("missing_part_a")

    if "B" not in part_letters:
        errors.append("missing_part_b")

    if hole_section not in VALID_HOLE_SECTIONS:
        errors.append("invalid_or_missing_hole_section")

    if day_status not in VALID_STATUSES:
        errors.append("invalid_or_missing_day_status")

    numeric_fields = {
        "depth_start": depth_start,
        "depth_end": depth_end,
        "circulating_hours": circulating_hours,
        "bha_run": bha_run,
        "gyro_surveys": gyro_surveys,
        "pressure_points": pressure_points,
        "wiper_trips": wiper_trips,
        "back_reaming_hours": back_reaming_hours,
        "clean_out_runs": clean_out_runs,
        "run_number": run_number,
        "run_circulating_hours": run_circulating_hours,
        "metres_logged": metres_logged,
        "metres_reamed": metres_reamed,
    }

    for field_name, value in numeric_fields.items():
        append_missing_integer_error(
            errors,
            field_name,
            value,
        )

    for field_name, value in numeric_fields.items():
        if value is not None and value < 0:
            errors.append(f"negative_{field_name}")

    if (
        depth_start is not None
        and depth_end is not None
        and depth_end < depth_start
    ):
        errors.append("depth_end_before_start")

    if bha_run is not None and run_number is not None:
        if bha_run != run_number:
            errors.append("bha_run_number_mismatch")

    if run_first_day is None:
        errors.append("invalid_or_missing_run_first_day")

    if run_last_day is None:
        errors.append("invalid_or_missing_run_last_day")

    if (
        run_first_day is not None
        and run_last_day is not None
        and run_last_day < run_first_day
    ):
        errors.append("run_last_day_before_first_day")

    if (
        report_date is not None
        and run_first_day is not None
        and run_last_day is not None
        and not (run_first_day <= report_date <= run_last_day)
    ):
        errors.append("report_date_outside_run")

    if radioactive_source_carried not in {"Yes", "No"}:
        errors.append("invalid_radioactive_source_value")

    if not tools_in_hole_raw:
        errors.append("missing_tools_in_hole")

    if not tools_in_run_raw:
        errors.append("missing_tools_in_run")

    if unmapped_tools_in_hole:
        errors.append("unmapped_tool_in_hole")

    if unmapped_tools_in_run:
        errors.append("unmapped_tool_in_run")

    if not crew_on_tour_raw:
        errors.append("missing_crew_on_tour")

    if unmapped_personnel:
        errors.append("unmapped_personnel")

    if gyro_surveys is not None:
        if gyro_surveys > 0 and "C" not in part_letters:
            errors.append("gyro_count_without_part_c")

        if gyro_surveys == 0 and "C" in part_letters:
            errors.append("part_c_without_gyro_count")

    if "C" in part_letters:
        if part_c_gyro_surveys is None:
            errors.append("missing_part_c_gyro_count")
        elif (
            gyro_surveys is not None
            and part_c_gyro_surveys != gyro_surveys
        ):
            errors.append("part_c_gyro_count_mismatch")

        if surveyed_section != hole_section:
            errors.append("surveyed_section_mismatch")

    if "D" in part_letters:
        if source_run is None:
            errors.append("missing_source_run")
        elif run_number is not None and source_run != run_number:
            errors.append("source_run_mismatch")

        if not sources_handled:
            errors.append("missing_sources_handled")

        if source_handling_certified != "Yes":
            errors.append("source_handling_not_certified")

        if radioactive_source_carried != "Yes":
            errors.append("part_d_without_radioactive_source")

    if "E" in part_letters:
        if lost_in_hole_run is None:
            errors.append("missing_lost_in_hole_run")
        elif (
            run_number is not None
            and lost_in_hole_run != run_number
        ):
            errors.append("lost_in_hole_run_mismatch")

        if not lost_in_hole_tool:
            errors.append("missing_lost_in_hole_tool")

        if not lost_in_hole_code:
            errors.append("unmapped_lost_in_hole_tool")

        if lost_tool_hours is None:
            errors.append("missing_lost_tool_hours")
        elif lost_tool_hours < 0:
            errors.append("negative_lost_tool_hours")

    if not company_representative:
        errors.append("missing_company_signature")

    if not lead_directional_driller:
        errors.append("missing_contractor_signature")

    metres_drilled: int | str = ""

    if depth_start is not None and depth_end is not None:
        metres_drilled = depth_end - depth_start

    tool_flags = {
        f"tool_{code.replace('-', '_')}": int(
            code in tools_in_hole_codes
        )
        for code in TOOL_CODES
    }

    personnel_fields = {
        f"personnel_{code.replace('-', '_')}": (
            personnel_counts.get(code, 0)
        )
        for code in PERSONNEL_CODES
    }

    signatures_complete = int(
        bool(
            company_representative
            and lead_directional_driller
        )
    )

    return ParsedReport(
        report_ref=report_ref,
        file_name=path.name,
        contract_ref=contract_ref,
        well_name=well_name,
        rig=rig,
        report_date=(
            report_date.isoformat() if report_date else ""
        ),
        part_a_present=int("A" in part_letters),
        part_b_present=int("B" in part_letters),
        part_c_present=int("C" in part_letters),
        part_d_present=int("D" in part_letters),
        part_e_present=int("E" in part_letters),
        hole_section=hole_section,
        day_status=day_status,
        depth_start_m=depth_start if depth_start is not None else "",
        depth_end_m=depth_end if depth_end is not None else "",
        metres_drilled=metres_drilled,
        circulating_hours=(
            circulating_hours
            if circulating_hours is not None
            else ""
        ),
        bha_run=bha_run if bha_run is not None else "",
        tools_in_hole_raw=tools_in_hole_raw,
        tools_in_hole_codes=";".join(
            sorted(tools_in_hole_codes)
        ),
        unmapped_tools_in_hole=";".join(
            unmapped_tools_in_hole
        ),
        crew_on_tour_raw=crew_on_tour_raw,
        personnel_counts=json.dumps(
            personnel_counts,
            sort_keys=True,
        ),
        unmapped_personnel=";".join(unmapped_personnel),
        gyro_surveys=(
            gyro_surveys if gyro_surveys is not None else ""
        ),
        pressure_points=(
            pressure_points
            if pressure_points is not None
            else ""
        ),
        wiper_trips=(
            wiper_trips if wiper_trips is not None else ""
        ),
        back_reaming_hours=(
            back_reaming_hours
            if back_reaming_hours is not None
            else ""
        ),
        clean_out_runs=(
            clean_out_runs
            if clean_out_runs is not None
            else ""
        ),
        run_number=(
            run_number if run_number is not None else ""
        ),
        run_first_day=(
            run_first_day.isoformat() if run_first_day else ""
        ),
        run_last_day=(
            run_last_day.isoformat() if run_last_day else ""
        ),
        tools_in_run_raw=tools_in_run_raw,
        tools_in_run_codes=";".join(
            sorted(tools_in_run_codes)
        ),
        unmapped_tools_in_run=";".join(
            unmapped_tools_in_run
        ),
        run_circulating_hours=(
            run_circulating_hours
            if run_circulating_hours is not None
            else ""
        ),
        metres_logged=(
            metres_logged if metres_logged is not None else ""
        ),
        metres_reamed=(
            metres_reamed if metres_reamed is not None else ""
        ),
        radioactive_source_carried=(
            radioactive_source_carried
        ),
        part_c_gyro_surveys=(
            part_c_gyro_surveys
            if part_c_gyro_surveys is not None
            else ""
        ),
        surveyed_section=surveyed_section,
        source_run=source_run if source_run is not None else "",
        sources_handled=sources_handled,
        source_handling_certified=(
            source_handling_certified
        ),
        lost_in_hole_run=(
            lost_in_hole_run
            if lost_in_hole_run is not None
            else ""
        ),
        lost_in_hole_tool=lost_in_hole_tool,
        lost_in_hole_code=lost_in_hole_code,
        lost_tool_hours_on_well=(
            lost_tool_hours
            if lost_tool_hours is not None
            else ""
        ),
        company_representative=company_representative,
        lead_directional_driller=lead_directional_driller,
        signatures_complete=signatures_complete,
        parse_ok=int(not errors),
        parse_errors=";".join(errors),
        **tool_flags,
        **personnel_fields,
    )


def write_csv(
    reports: Iterable[ParsedReport],
    output_path: Path,
) -> None:
    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=OUTPUT_FIELDS,
        )
        writer.writeheader()

        for report in reports:
            writer.writerow(asdict(report))


def build_summary(
    reports: list[ParsedReport],
) -> dict:
    error_counts = Counter()
    part_counts = Counter()
    status_counts = Counter()
    hole_section_counts = Counter()
    lost_code_counts = Counter()

    dates = []

    for report in reports:
        for part in "ABCDE":
            field_name = f"part_{part.lower()}_present"

            if getattr(report, field_name):
                part_counts[part] += 1

        status_counts[report.day_status] += 1
        hole_section_counts[report.hole_section] += 1

        if report.lost_in_hole_code:
            lost_code_counts[report.lost_in_hole_code] += 1

        if report.report_date:
            dates.append(report.report_date)

        if report.parse_errors:
            for error in report.parse_errors.split(";"):
                error_counts[error] += 1

    return {
        "total_reports": len(reports),
        "parsed_ok": sum(report.parse_ok for report in reports),
        "reports_with_errors": sum(
            not report.parse_ok for report in reports
        ),
        "signatures_complete": sum(
            report.signatures_complete
            for report in reports
        ),
        "report_date_min": min(dates) if dates else "",
        "report_date_max": max(dates) if dates else "",
        "part_counts": dict(sorted(part_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "hole_section_counts": dict(
            sorted(hole_section_counts.items())
        ),
        "lost_code_counts": dict(
            sorted(lost_code_counts.items())
        ),
        "error_counts": dict(sorted(error_counts.items())),
    }


def main() -> None:
    args = parse_args()

    if not args.records_dir.is_dir():
        raise SystemExit(
            f"Records directory does not exist: "
            f"{args.records_dir}"
        )

    files = sorted(args.records_dir.glob("*.txt"))

    if not files:
        raise SystemExit(
            f"No .txt reports found in: {args.records_dir}"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    reports = [parse_report(path) for path in files]
    summary = build_summary(reports)

    csv_path = args.output_dir / "drilling_reports.csv"
    summary_path = (
        args.output_dir
        / "drilling_report_parse_summary.json"
    )

    write_csv(reports, csv_path)

    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print(f"Parsed reports: {summary['total_reports']}")
    print(f"Parsed without errors: {summary['parsed_ok']}")
    print(
        "Reports with errors:",
        summary["reports_with_errors"],
    )
    print(
        "Complete signature pairs:",
        summary["signatures_complete"],
    )
    print(f"CSV output: {csv_path}")
    print(f"Summary output: {summary_path}")

    if summary["error_counts"]:
        print("\nError counts:")

        for error, count in summary["error_counts"].items():
            print(f"{count:>5}  {error}")


if __name__ == "__main__":
    main()