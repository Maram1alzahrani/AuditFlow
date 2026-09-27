from decimal import Decimal
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import audit_civil as audit  # noqa: E402


def test_contract_rounding_modes_are_distinct():
    assert audit.half_even(Decimal("1.005")) == Decimal("1.00")
    assert audit.half_up(Decimal("1.005")) == Decimal("1.01")
    assert audit.floor_halala(Decimal("1.019")) == Decimal("1.01")


def test_confirmed_c32010_daily_limit_is_six():
    assert audit.DAILY_LIMITS["C.32.010"] == Decimal("6")


def test_a12020_middle_band_is_97_percent():
    parts = audit.band_parts("A.12.020", Decimal("1490"), Decimal("20"))
    assert parts == [
        (Decimal("10"), Decimal("1.00")),
        (Decimal("10"), Decimal("0.97")),
    ]


def test_a3_rate_is_available_only_when_issued_or_forced():
    work_date = pd.Timestamp("2025-11-01")
    assert audit.base_rate(
        "A.14.010", work_date, pd.Timestamp("2026-05-11")
    ) == Decimal("53.20")
    assert audit.base_rate(
        "A.14.010", work_date, pd.Timestamp("2026-05-12")
    ) == Decimal("56.80")
    assert audit.base_rate(
        "A.14.010", work_date, pd.Timestamp("2026-05-11"), force_a3=True
    ) == Decimal("56.80")


def test_extension_period_forces_ground_factor_to_g2():
    result = audit.pre_band_rate(
        "A.12.020", pd.Timestamp("2025-09-28"), pd.Timestamp("2025-10-10"),
        "Z1 Compound", "G5 Sound Rock", False,
    )
    assert result == Decimal("34.8000")


def test_rest_day_uplift_replaces_uninstructed_night_uplift():
    # Friday 10-Jan-2025: B.21.020 gets rest-day 35%, not night 22% as well.
    result = audit.pre_band_rate(
        "B.21.020", pd.Timestamp("2025-01-10"), pd.Timestamp("2025-01-20"),
        "Z1 Compound", "G2 Firm Sabkha", True,
    )
    assert result == Decimal("560.2500")


def test_night_uplift_is_blocked_when_zone_factor_exceeds_1_1():
    result = audit.pre_band_rate(
        "A.12.020", pd.Timestamp("2025-01-08"), pd.Timestamp("2025-01-20"),
        "Z3 Wadi Crossing", "G2 Firm Sabkha", True,
    )
    assert result == Decimal("39.84600")


def test_full_dataset_reconciles_expected_controls():
    apps, lines, records = audit.load_inputs(PROJECT_ROOT)
    line_audit, merged = audit.audit_lines(apps, lines, records)
    forced_audit, _ = audit.audit_lines(apps, lines, records, force_a3=True)
    adjustment = audit.calculate_a3_adjustment(
        apps, line_audit, forced_audit, merged
    )
    app_audit, adjustment_target, release_target, release = audit.audit_applications(
        apps, lines, line_audit, adjustment
    )

    assert len(line_audit) == 7746
    assert len(app_audit) == 900
    assert int(line_audit["error_count"].gt(0).sum()) == 82
    assert int(app_audit["flagged"].sum()) == 77
    assert adjustment == Decimal("60508.18")
    assert adjustment_target == "PA-00006"
    assert release_target == "PA-00678"
    assert release == Decimal("4027429.62")
