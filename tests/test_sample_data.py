"""Fast, deterministic checks for the public synthetic portfolio."""
from datetime import date

from sample_data import build_sample_dataframe


def test_sample_portfolio_has_20_unique_trials():
    data = build_sample_dataframe(date(2026, 10, 30))
    assert len(data) == 20
    assert data['Trial'].notna().all()
    assert data['Trial'].is_unique


def test_sample_includes_incomplete_records_for_validation():
    data = build_sample_dataframe(date(2026, 10, 30))
    # The demo intentionally contains incomplete records to exercise data-quality workflows.
    assert data['Pharmacy notified'].isna().any()
    assert data['Trial Complexity'].eq('').any()


def test_sample_contains_multiple_workstreams():
    data = build_sample_dataframe(date(2026, 10, 30))
    assert data['Aseptic'].eq('Y').any()
    assert data['Aseptic'].eq('N').any()
    assert data['Prescribing system'].ne('none').any()
