"""portal_reviews carries each published week's frozen operators (migration 020)."""

from __future__ import annotations

from datetime import datetime

from src import queries

ROW = {
    "team_id": "legacy",
    "team_display_name": "Legacy",
    "run_id": "r1",
    "window_start": datetime(2026, 10, 12),
    "window_end": datetime(2026, 10, 19),
    "published_at": datetime(2026, 10, 19, 8),
    "review_note": None,
    "phase_derived": "phase_1",
    "phase2_readiness_pct": None,
}


def test_review_columns_name_the_operator_columns() -> None:
    assert "r.v1_operators, r.v2_operator" in queries._REVIEW_COLUMNS


def test_operators_keep_exact_values_and_order() -> None:
    row = {**ROW, "v1_operators": '["batch", "BATCH", "batch"]', "v2_operator": "Pay"}
    assert queries._review(row, {}).operators == (("batch", "BATCH", "batch"), "Pay")
    assert queries._review({**row, "v1_operators": "[]", "v2_operator": None}, {}).operators == (
        (),
        None,
    )


def test_a_snapshot_without_an_operator_list_is_unknown() -> None:
    for value in (None, "not json", '{"a": 1}', "5", '["ok", null]', '["ok", 5]'):
        row = {**ROW, "v1_operators": value, "v2_operator": None}
        assert queries._review(row, {}).operators is None
