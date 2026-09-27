from decimal import Decimal
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import audit_drilling as audit  # noqa: E402


def test_half_even_rounding_boundaries():
    assert audit.money(Decimal("1.005")) == Decimal("1.00")
    assert audit.money(Decimal("1.015")) == Decimal("1.02")


def test_a3_is_not_applied_to_pre_issue_invoice_lines():
    service_date = pd.Timestamp("2026-05-01")
    before_issue = audit.base_rate(
        "DD-120",
        service_date,
        pd.Timestamp("2026-08-16"),
    )
    on_issue = audit.base_rate(
        "DD-120",
        service_date,
        pd.Timestamp("2026-08-17"),
    )
    assert before_issue == Decimal("411.50")
    assert on_issue == Decimal("416.00")


def test_a3_rate_overrides_s2_monthly_rate_after_issue():
    assert audit.base_rate(
        "DD-120",
        pd.Timestamp("2026-08-01"),
        pd.Timestamp("2026-08-17"),
    ) == Decimal("416.00")


def test_dd120_rate_applies_section_class_and_discount_in_order():
    result = audit.expected_rate(
        code="DD-120",
        service_date=pd.Timestamp("2026-08-20"),
        invoice_date=pd.Timestamp("2026-09-01"),
        section='8-1/2"',
        well_class="Standard",
        status="Operating",
        depth_from=None,
        lost_hours=Decimal("0"),
    )
    assert result == Decimal("365.60")


def test_standby_omits_hole_section_factor():
    result = audit.expected_rate(
        code="DD-110",
        service_date=pd.Timestamp("2025-01-01"),
        invoice_date=pd.Timestamp("2025-01-10"),
        section='26"',
        well_class="Standard",
        status="Standby",
        depth_from=None,
        lost_hours=Decimal("0"),
    )
    assert result == Decimal("708.88")


def test_lost_in_hole_conversion_and_depreciation():
    result = audit.replacement_rate(
        "LH-711",
        pd.Timestamp("2025-01-15"),
        Decimal("50"),
    )
    assert result == Decimal("142100.00")


def test_quantity_tolerance_boundary():
    assert audit.payable_quantity(
        "LW-410", Decimal("101"), Decimal("100")
    ) == Decimal("101")
    assert audit.payable_quantity(
        "LW-410", Decimal("101.01"), Decimal("100")
    ) == Decimal("100")


def test_full_dataset_reconciles_expected_controls():
    invoices, lines, reports = audit.load_inputs(PROJECT_ROOT)
    events = audit.build_event_sets(reports)
    line_audit, merged = audit.audit_lines(invoices, lines, reports, events)
    invoice_audit, adjustment, target = audit.audit_invoices(
        invoices, lines, line_audit, merged
    )

    assert len(line_audit) == 91181
    assert len(invoice_audit) == 1906
    assert adjustment == Decimal("309965.52")
    assert target == "MDS-01625"
    assert int(invoice_audit["flagged"].sum()) == 119
    assert int(line_audit["error_count"].gt(0).sum()) == 103
