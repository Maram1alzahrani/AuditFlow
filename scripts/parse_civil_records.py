#!/usr/bin/env python3
"""Parse and validate civil-work site records.

The parser converts the free-text site records into structured evidence.
It does not use invoice prices or billed amounts to infer record meaning.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


RECORD_TITLES = {
    "CT": "COMPACTION TEST CERTIFICATE",
    "DX": "DAILY EXCAVATION RECORD",
    "PR": "CONCRETE POUR RECORD",
    "JS": "JOINT SURVEY SHEET",
    "PT": "PRESSURE TEST CERTIFICATE",
    "CV": "CCTV SURVEY REPORT",
    "MO": "METEOROLOGICAL RECORD",
    "PS": "PLANT STANDING RECORD",
    "DW": "DEWATERING LOG",
}

VALID_AREAS = {
    "S-01 Platform North",
    "S-02 Platform South",
    "S-03 Access Road",
    "S-04 Drainage Corridor",
    "S-05 Compound Extension",
}

VALID_GROUND_CLASSES = {"G1", "G2", "G3", "G4", "G5"}

HEADER_PREFIXES = (
    "Ticket:",
    "Job:",
    "Area:",
    "Date:",
    "Ground:",
    "Week beginning:",
    "Days on:",
    "Signed (foreman):",
    "Countersigned (Engineer's representative):",
)

OUTPUT_FIELDS = [
    "record_ref",
    "file_name",
    "record_type",
    "title",
    "job",
    "area",
    "record_date",
    "week_beginning",
    "days_on_count",
    "days_on_dates",
    "week_eligible",
    "ground_class",
    "ground_description",
    "body_text",
    "inferred_item_code",
    "quantity",
    "unit",
    "foreman",
    "engineer_representative",
    "signatures_complete",
    "parse_ok",
    "parse_errors",
]


@dataclass
class ParsedRecord:
    record_ref: str
    file_name: str
    record_type: str
    title: str
    job: str
    area: str
    record_date: str
    week_beginning: str
    days_on_count: int | str
    days_on_dates: str
    week_eligible: int | str
    ground_class: str
    ground_description: str
    body_text: str
    inferred_item_code: str
    quantity: str
    unit: str
    foreman: str
    engineer_representative: str
    signatures_complete: int
    parse_ok: int
    parse_errors: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse and validate civil-work site records."
    )
    parser.add_argument(
        "--records-dir",
        type=Path,
        default=Path("civilwork/records"),
        help="Directory containing civil record .txt files.",
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


def parse_date(value: str) -> date | None:
    if not value:
        return None

    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return None


def decimal_text(value: str) -> str:
    try:
        number = Decimal(value)
    except InvalidOperation:
        return ""

    return format(number.normalize(), "f")


def extract_body(lines: list[str]) -> str:
    body_lines = []

    for line in lines[1:]:
        stripped = line.strip()

        if not stripped:
            continue

        if stripped.startswith(HEADER_PREFIXES):
            continue

        body_lines.append(stripped)

    return clean_space(" ".join(body_lines))


def infer_item_code(record_type: str, body: str) -> str:
    lowered = body.lower()

    if record_type == "CT":
        if "capping layer" in lowered:
            return "D.41.040"
        if "sub-base" in lowered or "type 1" in lowered:
            return "D.41.010"
        if (
            "imported stone" in lowered
            or "cube of fill" in lowered
            or "brought in" in lowered
        ):
            return "A.14.010"

    elif record_type == "DX":
        if "over four metres" in lowered:
            return "A.12.040"
        if (
            "between two and four metres" in lowered
            or re.search(r"\b[234]\s*m\s+deep\b", lowered)
        ):
            return "A.12.030"

    elif record_type == "PR":
        if "wall pour" in lowered:
            return "B.21.040"
        if "slab" in lowered:
            return "B.21.030"
        if "foundation" in lowered:
            return "B.21.020"

    elif record_type == "JS":
        if "mesh" in lowered:
            return "B.23.020"
        if "chainage band" in lowered:
            return "E.52.010"
        if "high yield bar" in lowered or "tonne of bar" in lowered:
            return "B.23.010"

    elif record_type == "PT":
        if "large chamber" in lowered and "1800" in lowered:
            return "C.32.030"
        if "ductile main" in lowered:
            return "C.31.020"

    elif record_type == "CV":
        return "C.35.010"

    elif record_type == "MO":
        return "E.51.010"

    elif record_type == "PS":
        return "E.51.030"

    elif record_type == "DW":
        return "A.16.010"

    return ""


def quantity_pattern_for_item(item_code: str) -> tuple[str, str]:
    patterns = {
        "A.12.030": (r"\b(\d+(?:\.\d+)?)\s*(?:m3|cube)\b", "m3"),
        "A.12.040": (r"\b(\d+(?:\.\d+)?)\s*(?:m3|cube)\b", "m3"),
        "A.14.010": (r"\b(\d+(?:\.\d+)?)\s*(?:m3|cube)\b", "m3"),
        "A.16.010": (r"\b(\d+(?:\.\d+)?)\s+week\b", "week"),
        "B.21.020": (r"\b(\d+(?:\.\d+)?)\s*(?:m3|cube)\b", "m3"),
        "B.21.030": (r"\b(\d+(?:\.\d+)?)\s*(?:m3|cube)\b", "m3"),
        "B.21.040": (r"\b(\d+(?:\.\d+)?)\s*(?:m3|cube)\b", "m3"),
        "B.23.010": (r"\b(\d+(?:\.\d+)?)\s*(?:tonne|t)\b", "tonne"),
        "B.23.020": (r"\b(\d+(?:\.\d+)?)\s*m2\b", "m2"),
        "C.31.020": (r"\blaid\s+(\d+(?:\.\d+)?)\s*m\b", "lm"),
        "C.32.030": (r"\bbuilt\s+(\d+(?:\.\d+)?)\s+large chamber", "no."),
        "C.35.010": (r"\bsurveyed\s+(\d+(?:\.\d+)?)\s*m\b", "lm"),
        "D.41.010": (r"\b(\d+(?:\.\d+)?)\s*(?:m2|square metres)\b", "m2"),
        "D.41.040": (r"\b(\d+(?:\.\d+)?)\s*m2\b", "m2"),
        "E.51.010": (r"\b(\d+(?:\.\d+)?)\s+hours?\b", "hour"),
        "E.51.030": (r"\b(\d+(?:\.\d+)?)\s+hours?\b", "hour"),
        "E.52.010": (
            r"\b(\d+(?:\.\d+)?)\s+chainage band\b",
            "no.",
        ),
    }

    return patterns.get(item_code, ("", ""))


def extract_quantity_and_unit(
    item_code: str,
    body: str,
) -> tuple[str, str]:
    pattern, unit = quantity_pattern_for_item(item_code)

    if not pattern:
        return "", ""

    match = re.search(pattern, body, flags=re.IGNORECASE)

    if not match:
        return "", unit

    return decimal_text(match.group(1)), unit


def derive_day_date(
    day_month: str,
    week_beginning: date,
) -> date | None:
    try:
        day_value, month_value = map(int, day_month.split("/"))
    except (TypeError, ValueError):
        return None

    candidates = []

    for year_value in (
        week_beginning.year - 1,
        week_beginning.year,
        week_beginning.year + 1,
    ):
        try:
            candidate = date(year_value, month_value, day_value)
        except ValueError:
            continue

        distance = abs((candidate - week_beginning).days)
        candidates.append((distance, candidate))

    if not candidates:
        return None

    _, best = min(candidates, key=lambda pair: pair[0])
    return best


def parse_days_on(
    days_on_text: str,
    week_beginning: date | None,
) -> list[date]:
    if not days_on_text or week_beginning is None:
        return []

    day_month_values = re.findall(
        r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{2}/\d{2})\b",
        days_on_text,
    )

    parsed_dates = []

    for value in day_month_values:
        parsed = derive_day_date(value, week_beginning)

        if parsed is not None:
            parsed_dates.append(parsed)

    return parsed_dates


def parse_ground(value: str) -> tuple[str, str]:
    if not value:
        return "", ""

    match = re.match(r"^(G[1-5])\s*(.*)$", value)

    if not match:
        return "", clean_space(value)

    return match.group(1), clean_space(match.group(2))


def parse_record(path: Path) -> ParsedRecord:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    nonempty_lines = [line.strip() for line in lines if line.strip()]

    errors: list[str] = []

    file_ref = path.stem
    record_type = file_ref.split("-", maxsplit=1)[0]
    title = nonempty_lines[0] if nonempty_lines else ""

    ticket = extract_field(text, "Ticket:")
    job = extract_field(text, "Job:")
    area = extract_field(text, "Area:")
    date_text = extract_field(text, "Date:")
    week_text = extract_field(text, "Week beginning:")
    days_on_text = extract_field(text, "Days on:")
    ground_text = extract_field(text, "Ground:")
    foreman = extract_field(text, "Signed (foreman):")
    engineer = extract_field(
        text,
        "Countersigned (Engineer's representative):",
    )

    body = extract_body(nonempty_lines)
    item_code = infer_item_code(record_type, body)
    quantity, unit = extract_quantity_and_unit(item_code, body)

    record_date = parse_date(date_text)
    week_beginning = parse_date(week_text)
    days_on = parse_days_on(days_on_text, week_beginning)

    ground_class, ground_description = parse_ground(ground_text)

    expected_title = RECORD_TITLES.get(record_type, "")

    if record_type not in RECORD_TITLES:
        errors.append("unknown_record_type")

    if expected_title and title != expected_title:
        errors.append("unexpected_title")

    if not ticket:
        errors.append("missing_ticket")
    elif ticket != file_ref:
        errors.append("ticket_filename_mismatch")

    if not job:
        errors.append("missing_job")

    if not area:
        errors.append("missing_area")
    elif area not in VALID_AREAS:
        errors.append("unknown_area")

    if record_type == "DW":
        if week_beginning is None:
            errors.append("invalid_or_missing_week_beginning")

        if not days_on_text:
            errors.append("missing_days_on")

        if len(days_on) < 5:
            errors.append("fewer_than_five_days_on")
    else:
        if record_date is None:
            errors.append("invalid_or_missing_record_date")

    if record_type in {"DX", "PT"}:
        if not ground_class:
            errors.append("missing_ground_class")
        elif ground_class not in VALID_GROUND_CLASSES:
            errors.append("invalid_ground_class")

    if not body:
        errors.append("missing_body_text")

    if not item_code:
        errors.append("item_code_not_inferred")

    if not quantity:
        errors.append("quantity_not_parsed")
    else:
        try:
            if Decimal(quantity) <= 0:
                errors.append("non_positive_quantity")
        except InvalidOperation:
            errors.append("invalid_quantity")

    if not unit:
        errors.append("unit_not_inferred")

    if not foreman:
        errors.append("missing_foreman_signature")

    if not engineer:
        errors.append("missing_engineer_countersignature")

    signatures_complete = int(bool(foreman and engineer))
    week_eligible: int | str = ""

    if record_type == "DW":
        week_eligible = int(
            week_beginning is not None
            and len(days_on) >= 5
            and quantity == "1"
        )

    return ParsedRecord(
        record_ref=file_ref,
        file_name=path.name,
        record_type=record_type,
        title=title,
        job=job,
        area=area,
        record_date=record_date.isoformat() if record_date else "",
        week_beginning=(
            week_beginning.isoformat() if week_beginning else ""
        ),
        days_on_count=len(days_on) if record_type == "DW" else "",
        days_on_dates=";".join(
            parsed_date.isoformat() for parsed_date in days_on
        ),
        week_eligible=week_eligible,
        ground_class=ground_class,
        ground_description=ground_description,
        body_text=body,
        inferred_item_code=item_code,
        quantity=quantity,
        unit=unit,
        foreman=foreman,
        engineer_representative=engineer,
        signatures_complete=signatures_complete,
        parse_ok=int(not errors),
        parse_errors=";".join(errors),
    )


def write_csv(records: Iterable[ParsedRecord], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()

        for record in records:
            writer.writerow(asdict(record))


def build_summary(records: list[ParsedRecord]) -> dict:
    error_counts = Counter()
    type_counts = Counter()
    item_counts = Counter()

    for record in records:
        type_counts[record.record_type] += 1

        if record.inferred_item_code:
            item_counts[record.inferred_item_code] += 1

        if record.parse_errors:
            for error in record.parse_errors.split(";"):
                error_counts[error] += 1

    return {
        "total_records": len(records),
        "parsed_ok": sum(record.parse_ok for record in records),
        "records_with_errors": sum(
            not record.parse_ok for record in records
        ),
        "signatures_complete": sum(
            record.signatures_complete for record in records
        ),
        "eligible_weekly_records": sum(
            record.week_eligible == 1 for record in records
        ),
        "record_type_counts": dict(sorted(type_counts.items())),
        "inferred_item_code_counts": dict(sorted(item_counts.items())),
        "error_counts": dict(sorted(error_counts.items())),
    }


def main() -> None:
    args = parse_args()

    if not args.records_dir.is_dir():
        raise SystemExit(
            f"Records directory does not exist: {args.records_dir}"
        )

    files = sorted(args.records_dir.glob("*.txt"))

    if not files:
        raise SystemExit(
            f"No .txt records found in: {args.records_dir}"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    records = [parse_record(path) for path in files]
    summary = build_summary(records)

    csv_path = args.output_dir / "civil_records.csv"
    summary_path = args.output_dir / "civil_record_parse_summary.json"

    write_csv(records, csv_path)

    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(f"Parsed records: {summary['total_records']}")
    print(f"Parsed without errors: {summary['parsed_ok']}")
    print(f"Records with errors: {summary['records_with_errors']}")
    print(
        "Complete signature pairs:",
        summary["signatures_complete"],
    )
    print(
        "Eligible weekly records:",
        summary["eligible_weekly_records"],
    )
    print(f"CSV output: {csv_path}")
    print(f"Summary output: {summary_path}")

    if summary["error_counts"]:
        print("\nError counts:")

        for error, count in summary["error_counts"].items():
            print(f"{count:>5}  {error}")


if __name__ == "__main__":
    main()