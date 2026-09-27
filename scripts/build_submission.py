#!/usr/bin/env python3
"""Run both audit engines and build the final submission in template order."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

import audit_civil
import audit_drilling
import parse_civil_records
import parse_drilling_reports


SUBMISSION_COLUMNS = [
    "invoice_id",
    "flagged",
    "error_category",
    "expected_total_cents",
    "billed_total_cents",
    "confidence",
]


def parse_source_evidence(root: Path) -> None:
    """Rebuild structured evidence from the repository's raw text records."""
    output_dir = root / "artifacts/parsed"
    output_dir.mkdir(parents=True, exist_ok=True)

    civil_files = sorted((root / "civilwork/records").glob("*.txt"))
    drilling_files = sorted(
        (root / "drilling_services/records").glob("*.txt")
    )
    if not civil_files or not drilling_files:
        raise ValueError("Raw civil or drilling evidence files are missing")

    civil_records = [
        parse_civil_records.parse_record(path) for path in civil_files
    ]
    civil_summary = parse_civil_records.build_summary(civil_records)
    parse_civil_records.write_csv(
        civil_records, output_dir / "civil_records.csv"
    )
    (output_dir / "civil_record_parse_summary.json").write_text(
        json.dumps(civil_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    drilling_reports = [
        parse_drilling_reports.parse_report(path) for path in drilling_files
    ]
    drilling_summary = parse_drilling_reports.build_summary(
        drilling_reports
    )
    parse_drilling_reports.write_csv(
        drilling_reports, output_dir / "drilling_reports.csv"
    )
    (output_dir / "drilling_report_parse_summary.json").write_text(
        json.dumps(drilling_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_civil(root: Path) -> pd.DataFrame:
    applications, lines, records = audit_civil.load_inputs(root)
    line_audit, merged = audit_civil.audit_lines(applications, lines, records)
    forced_audit, _ = audit_civil.audit_lines(
        applications, lines, records, force_a3=True
    )
    adjustment = audit_civil.calculate_a3_adjustment(
        applications, line_audit, forced_audit, merged
    )
    application_audit, adjustment_target, release_target, release = (
        audit_civil.audit_applications(
            applications, lines, line_audit, adjustment
        )
    )
    audit_civil.write_outputs(
        root,
        line_audit,
        application_audit,
        adjustment,
        adjustment_target,
        release_target,
        release,
    )
    return application_audit[SUBMISSION_COLUMNS].copy()


def run_drilling(root: Path) -> pd.DataFrame:
    invoices, lines, reports = audit_drilling.load_inputs(root)
    events = audit_drilling.build_event_sets(reports)
    line_audit, merged = audit_drilling.audit_lines(
        invoices, lines, reports, events
    )
    invoice_audit, adjustment, adjustment_target = (
        audit_drilling.audit_invoices(invoices, lines, line_audit, merged)
    )
    audit_drilling.write_outputs(
        root, line_audit, invoice_audit, adjustment, adjustment_target
    )
    return invoice_audit[SUBMISSION_COLUMNS].copy()


def validate_submission(
    template: pd.DataFrame,
    combined_results: pd.DataFrame,
    submission: pd.DataFrame,
) -> dict[str, Any]:
    if list(submission.columns) != SUBMISSION_COLUMNS:
        raise ValueError("Submission columns do not exactly match the template")
    if template["invoice_id"].duplicated().any():
        raise ValueError("Template contains duplicate invoice IDs")
    if combined_results["invoice_id"].duplicated().any():
        duplicates = combined_results.loc[
            combined_results["invoice_id"].duplicated(False), "invoice_id"
        ].tolist()
        raise ValueError(f"Duplicate audited invoice IDs: {duplicates[:10]}")

    template_ids = set(template["invoice_id"])
    result_ids = set(combined_results["invoice_id"])
    missing = sorted(template_ids - result_ids)
    unexpected = sorted(result_ids - template_ids)
    if missing or unexpected:
        raise ValueError(
            f"Coverage mismatch: {len(missing)} missing, "
            f"{len(unexpected)} unexpected"
        )
    if len(submission) != len(template):
        raise ValueError("Submission row count does not match template")
    if submission.isna().any().any():
        null_columns = submission.columns[submission.isna().any()].tolist()
        raise ValueError(f"Submission contains nulls in: {null_columns}")
    if not submission["flagged"].isin([0, 1]).all():
        raise ValueError("flagged must contain only 0 or 1")
    if not submission["expected_total_cents"].map(
        lambda value: isinstance(value, int)
    ).all():
        raise ValueError("expected_total_cents must be integer-valued")
    if not submission["billed_total_cents"].map(
        lambda value: isinstance(value, int)
    ).all():
        raise ValueError("billed_total_cents must be integer-valued")
    if not submission["confidence"].between(0, 1).all():
        raise ValueError("confidence must be between 0 and 1")
    clean_with_category = submission[
        submission["flagged"].eq(0)
        & submission["error_category"].ne("")
    ]
    flagged_without_category = submission[
        submission["flagged"].eq(1)
        & submission["error_category"].eq("")
    ]
    if not clean_with_category.empty or not flagged_without_category.empty:
        raise ValueError("flagged and error_category are inconsistent")

    return {
        "row_count": int(len(submission)),
        "unique_invoice_ids": int(submission["invoice_id"].nunique()),
        "flagged_count": int(submission["flagged"].sum()),
        "clean_count": int(submission["flagged"].eq(0).sum()),
        "civil_count": int(submission["invoice_id"].str.startswith("PA-").sum()),
        "drilling_count": int(submission["invoice_id"].str.startswith("MDS-").sum()),
        "missing_ids": 0,
        "unexpected_ids": 0,
        "duplicate_ids": 0,
        "null_cells": 0,
    }


def build_submission(root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    template = pd.read_csv(
        root / "submission_template.csv", keep_default_na=False
    )
    if list(template.columns) != SUBMISSION_COLUMNS:
        raise ValueError("Unexpected submission template schema")

    parse_source_evidence(root)
    civil = run_civil(root)
    drilling = run_drilling(root)
    combined = pd.concat([civil, drilling], ignore_index=True)

    # A left merge on only the template IDs preserves the required row order
    # and prevents stale placeholder values from leaking into the result.
    submission = template[["invoice_id"]].merge(
        combined, on="invoice_id", how="left", validate="one_to_one"
    )
    submission = submission[SUBMISSION_COLUMNS]
    submission["flagged"] = pd.to_numeric(
        submission["flagged"], errors="raise"
    ).astype(int)
    submission["expected_total_cents"] = pd.to_numeric(
        submission["expected_total_cents"], errors="raise"
    ).astype(int)
    submission["billed_total_cents"] = pd.to_numeric(
        submission["billed_total_cents"], errors="raise"
    ).astype(int)
    submission["confidence"] = pd.to_numeric(
        submission["confidence"], errors="raise"
    ).astype(float)

    summary = validate_submission(template, combined, submission)
    submission.to_csv(root / "submission.csv", index=False)
    output_dir = root / "artifacts/audit"
    output_dir.mkdir(parents=True, exist_ok=True)
    submission.to_csv(output_dir / "final_submission.csv", index=False)
    (output_dir / "final_submission_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return submission, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    root = args.root.resolve()
    _, summary = build_submission(root)
    print(f"Final rows: {summary['row_count']}")
    print(f"Civil rows: {summary['civil_count']}")
    print(f"Drilling rows: {summary['drilling_count']}")
    print(f"Flagged: {summary['flagged_count']}")
    print(f"Clean: {summary['clean_count']}")
    print("Coverage: complete; no missing, unexpected, or duplicate IDs")
    print(f"Output: {root / 'submission.csv'}")


if __name__ == "__main__":
    main()
