"""P6-11 (SAFETY_OR_INTEGRITY_BLOCKING): one-open-position-per-mint
default and ALLOW_AUTOMATIC_SCALE_IN=false -- MASTER_SPEC.md section 65,
orchestrator instruction ``argus-phase-6-001``.

Multiple wallet signals for the same mint may raise confidence but can
never create an additional automatic buy. The real database-level
backstop (the partial unique index on ``live_positions``) is exercised
by the concurrent-intents DB-gated test in
``tests/integration/test_phase6_persistence_and_concurrency.py``.
"""

from __future__ import annotations

from argus.executor.position_policy import ALLOW_AUTOMATIC_SCALE_IN, evaluate_scale_in


def test_automatic_scale_in_is_hardcoded_false() -> None:
    assert ALLOW_AUTOMATIC_SCALE_IN is False


def test_no_existing_position_allows_a_new_entry() -> None:
    decision = evaluate_scale_in(existing_open_position_for_mint=False)
    assert decision.allowed is True


def test_existing_open_position_blocks_a_second_automatic_buy() -> None:
    decision = evaluate_scale_in(existing_open_position_for_mint=True)
    assert decision.allowed is False
    assert "ALLOW_AUTOMATIC_SCALE_IN" in decision.reason


def test_repeated_wallet_signals_for_same_mint_still_blocked() -> None:
    """Simulates three separate tracked-wallet signals all pointing at
    the same already-open mint -- every single one is independently
    rejected, never accumulating into an automatic scale-in."""
    for _ in range(3):
        decision = evaluate_scale_in(existing_open_position_for_mint=True)
        assert decision.allowed is False
