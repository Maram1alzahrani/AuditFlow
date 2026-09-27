from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import build_submission as builder  # noqa: E402


def test_final_submission_has_exact_template_coverage_and_schema():
    submission, summary = builder.build_submission(PROJECT_ROOT)
    template = pd.read_csv(
        PROJECT_ROOT / "submission_template.csv", keep_default_na=False
    )

    assert list(submission.columns) == builder.SUBMISSION_COLUMNS
    assert submission["invoice_id"].tolist() == template["invoice_id"].tolist()
    assert summary["row_count"] == 2806
    assert summary["unique_invoice_ids"] == 2806
    assert summary["civil_count"] == 900
    assert summary["drilling_count"] == 1906
    assert summary["flagged_count"] == 196
    assert summary["clean_count"] == 2610
    assert summary["missing_ids"] == 0
    assert summary["unexpected_ids"] == 0
    assert summary["duplicate_ids"] == 0
    assert summary["null_cells"] == 0


def test_final_submission_types_and_flag_consistency():
    submission, _ = builder.build_submission(PROJECT_ROOT)

    assert submission["flagged"].isin([0, 1]).all()
    assert submission["expected_total_cents"].map(
        lambda value: isinstance(value, int)
    ).all()
    assert submission["billed_total_cents"].map(
        lambda value: isinstance(value, int)
    ).all()
    assert submission["confidence"].between(0, 1).all()
    assert submission.loc[
        submission["flagged"].eq(0), "error_category"
    ].eq("").all()
    assert submission.loc[
        submission["flagged"].eq(1), "error_category"
    ].ne("").all()

