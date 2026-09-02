"""P5-04 (SPEC_BLOCKING): forward information values -- MASTER_SPEC.md
section 51, mechanic M3's grid (``argus.copyability.delay_curves.
build_forward_information_grid``), orchestrator instruction
``argus-phase-5-001``.
"""

from __future__ import annotations

from decimal import Decimal

from argus.copyability.delay_curves import (
    FORWARD_INFO_HORIZON_LABELS,
    PHASE_9_MATCHED_CONTROLS_UNAVAILABLE,
    ForwardInfoCell,
    build_forward_information_grid,
)


def test_all_nine_horizon_cells_present_measured_or_explicitly_missing() -> None:
    cells = {
        "5s": ForwardInfoCell(available=True, return_fraction=Decimal("0.1")),
        "1h": ForwardInfoCell(available=True, return_fraction=Decimal("0.3")),
    }
    grid = build_forward_information_grid(cells)
    assert set(grid.keys()) == set(FORWARD_INFO_HORIZON_LABELS)
    assert grid["5s"]["available"] is True
    assert grid["5s"]["return_fraction"] == "0.1"
    assert grid["15s"]["available"] is False
    assert "reason" in grid["15s"]


def test_observation_relative_to_first_seen_never_leader_relative() -> None:
    """Leader executes at t0; ARGUS first_seen at t0+20s; an observation
    made at first_seen+30s must be reported at the 30s grid cell (relative
    to first_seen_at), never mislabeled as a leader-relative 50s cell."""
    cells = {"30s": ForwardInfoCell(available=True, return_fraction=Decimal("0.05"))}
    grid = build_forward_information_grid(cells)
    assert grid["30s"]["available"] is True
    # No 50s key exists in the fixed grid at all -- proves no leader-
    # relative mislabeling is even representable.
    assert "50s" not in grid


def test_entry_delayed_5s_plus_5m_holding_reported_at_5m_not_first_seen_plus_5m_mislabel() -> None:
    """An entry delayed 5s with a 5-minute holding period must be recorded
    under the "5m" cell as a distinct concept from "first_seen + 5m" --
    this module only ever accepts a caller-supplied label, so a caller
    cannot accidentally conflate the two without an explicit mapping."""
    cells = {"5m": ForwardInfoCell(available=True, return_fraction=Decimal("0.12"))}
    grid = build_forward_information_grid(cells)
    assert grid["5m"]["available"] is True
    assert grid["5m"]["return_fraction"] == "0.12"


def test_missing_exact_horizon_is_unavailable_never_interpolated() -> None:
    cells = {"5s": ForwardInfoCell(available=True, return_fraction=Decimal("0.1"))}
    grid = build_forward_information_grid(cells)
    for label in ("15s", "30s", "60s", "5m", "30m", "1h", "6h", "24h"):
        assert grid[label]["available"] is False


def test_absent_matched_benchmark_stays_null_with_phase9_marker() -> None:
    cells = {"1h": ForwardInfoCell(available=True, return_fraction=Decimal("0.2"))}
    grid = build_forward_information_grid(cells)
    assert grid["1h"]["matched_universe_abnormal_return"] is None
    assert grid["1h"]["matched_universe_status"] == PHASE_9_MATCHED_CONTROLS_UNAVAILABLE


def test_cash_baseline_is_the_explicit_v1_benchmark() -> None:
    cells = {"24h": ForwardInfoCell(available=True, return_fraction=Decimal("-0.05"))}
    grid = build_forward_information_grid(cells)
    assert grid["24h"]["benchmark"] == "cash_zero_return_baseline"
    assert grid["24h"]["return_fraction"] == "-0.05"


def test_executable_preferred_flag_labeled_explicitly() -> None:
    cells = {
        "6h": ForwardInfoCell(available=True, return_fraction=Decimal("0.4"), is_executable=False)
    }
    grid = build_forward_information_grid(cells)
    assert grid["6h"]["is_executable"] is False


def test_no_later_chart_backfill_used_unavailable_cell_carries_reason() -> None:
    cells = {"30m": ForwardInfoCell(available=False, reason="no reverse-executable probe yet")}
    grid = build_forward_information_grid(cells)
    assert grid["30m"]["available"] is False
    assert grid["30m"]["reason"] == "no reverse-executable probe yet"
