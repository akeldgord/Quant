"""P6-13 (SAFETY_OR_INTEGRITY_BLOCKING): token safety and pre-entry
sellability -- MASTER_SPEC.md sections 68/69, orchestrator instruction
``argus-phase-6-001``.

Unknown dangerous token mechanics or missing/unsafe reverse
executability can never become auto-live eligible -- every flag missing
from evidence is treated exactly like UNKNOWN, and any FAIL always wins
over UNKNOWN in the overall status.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from argus.executor.token_safety import (
    ALL_RISK_FLAGS,
    OVERALL_SAFE,
    OVERALL_UNKNOWN,
    OVERALL_UNSAFE,
    RISK_FLAG_EXTREME_LIQUIDITY_WEAKNESS,
    RISK_FLAG_FREEZE_AUTHORITY,
    RISK_FLAG_MINT_AUTHORITY,
    RISK_FLAG_SUPPLY_CONCENTRATION,
    RISK_FLAG_SUSPICIOUS_MUTABILITY,
    RISK_FLAG_TOKEN_2022_EXTENSIONS,
    RISK_FLAG_TRANSFER_FEES,
    RISK_FLAG_UNSUPPORTED_TRANSFER_BEHAVIOR,
    FlagStatus,
    SellabilityEvidence,
    evaluate_pre_entry_sellability,
    evaluate_token_safety,
)

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def _all_pass_flags() -> dict[str, FlagStatus]:
    return dict.fromkeys(ALL_RISK_FLAGS, "PASS")


def test_all_flags_pass_yields_safe() -> None:
    flags = _all_pass_flags()
    result = evaluate_token_safety(flags)
    assert result.overall_status == OVERALL_SAFE
    assert result.unsafe_flags == ()
    assert result.unknown_flags == ()


def test_exactly_eight_risk_flags() -> None:
    assert len(ALL_RISK_FLAGS) == 8
    assert len(set(ALL_RISK_FLAGS)) == 8


@pytest.mark.parametrize(
    "flag",
    [
        RISK_FLAG_MINT_AUTHORITY,
        RISK_FLAG_FREEZE_AUTHORITY,
        RISK_FLAG_TOKEN_2022_EXTENSIONS,
        RISK_FLAG_TRANSFER_FEES,
        RISK_FLAG_UNSUPPORTED_TRANSFER_BEHAVIOR,
        RISK_FLAG_SUPPLY_CONCENTRATION,
        RISK_FLAG_EXTREME_LIQUIDITY_WEAKNESS,
        RISK_FLAG_SUSPICIOUS_MUTABILITY,
    ],
)
def test_each_flag_fail_independently_makes_overall_unsafe(flag: str) -> None:
    flags = _all_pass_flags()
    flags[flag] = "FAIL"
    result = evaluate_token_safety(flags)
    assert result.overall_status == OVERALL_UNSAFE
    assert flag in result.unsafe_flags


@pytest.mark.parametrize("flag", ALL_RISK_FLAGS)
def test_each_flag_unknown_independently_makes_overall_unknown(flag: str) -> None:
    flags = _all_pass_flags()
    flags[flag] = "UNKNOWN"
    result = evaluate_token_safety(flags)
    assert result.overall_status == OVERALL_UNKNOWN
    assert flag in result.unknown_flags


def test_missing_flag_is_treated_exactly_like_unknown() -> None:
    flags: dict[str, FlagStatus] = {
        f: "PASS" for f in ALL_RISK_FLAGS if f != RISK_FLAG_MINT_AUTHORITY
    }
    result = evaluate_token_safety(flags)
    assert result.overall_status == OVERALL_UNKNOWN
    assert RISK_FLAG_MINT_AUTHORITY in result.unknown_flags


def test_fail_wins_over_unknown_in_overall_status() -> None:
    flags = _all_pass_flags()
    flags[RISK_FLAG_MINT_AUTHORITY] = "FAIL"
    flags[RISK_FLAG_FREEZE_AUTHORITY] = "UNKNOWN"
    result = evaluate_token_safety(flags)
    assert result.overall_status == OVERALL_UNSAFE


def test_empty_flags_dict_is_fully_unknown() -> None:
    result = evaluate_token_safety({})
    assert result.overall_status == OVERALL_UNKNOWN
    assert set(result.unknown_flags) == set(ALL_RISK_FLAGS)


def _sellable_evidence(**overrides: object) -> SellabilityEvidence:
    base: dict = {
        "reverse_route_available": True,
        "reverse_price_impact_fraction": Decimal("0.01"),
        "reverse_quote_at": _NOW - timedelta(seconds=5),
    }
    base.update(overrides)
    return SellabilityEvidence(**base)


def test_full_sellable_evidence_passes() -> None:
    result = evaluate_pre_entry_sellability(
        _sellable_evidence(),
        cutoff=_NOW,
        max_reverse_price_impact_fraction=Decimal("0.10"),
        max_quote_age_seconds=Decimal(30),
    )
    assert result.status == "PASS"


def test_missing_route_evidence_is_unknown() -> None:
    result = evaluate_pre_entry_sellability(
        _sellable_evidence(reverse_route_available=None),
        cutoff=_NOW,
        max_reverse_price_impact_fraction=Decimal("0.10"),
        max_quote_age_seconds=Decimal(30),
    )
    assert result.status == "UNKNOWN"


def test_no_reverse_route_is_fail() -> None:
    result = evaluate_pre_entry_sellability(
        _sellable_evidence(reverse_route_available=False),
        cutoff=_NOW,
        max_reverse_price_impact_fraction=Decimal("0.10"),
        max_quote_age_seconds=Decimal(30),
    )
    assert result.status == "FAIL"


def test_missing_price_impact_evidence_is_unknown() -> None:
    result = evaluate_pre_entry_sellability(
        _sellable_evidence(reverse_price_impact_fraction=None),
        cutoff=_NOW,
        max_reverse_price_impact_fraction=Decimal("0.10"),
        max_quote_age_seconds=Decimal(30),
    )
    assert result.status == "UNKNOWN"


def test_excessive_price_impact_is_fail() -> None:
    result = evaluate_pre_entry_sellability(
        _sellable_evidence(reverse_price_impact_fraction=Decimal("0.50")),
        cutoff=_NOW,
        max_reverse_price_impact_fraction=Decimal("0.10"),
        max_quote_age_seconds=Decimal(30),
    )
    assert result.status == "FAIL"


def test_missing_quote_timestamp_is_unknown() -> None:
    result = evaluate_pre_entry_sellability(
        _sellable_evidence(reverse_quote_at=None),
        cutoff=_NOW,
        max_reverse_price_impact_fraction=Decimal("0.10"),
        max_quote_age_seconds=Decimal(30),
    )
    assert result.status == "UNKNOWN"


def test_future_quote_timestamp_is_unknown_never_trusted() -> None:
    result = evaluate_pre_entry_sellability(
        _sellable_evidence(reverse_quote_at=_NOW + timedelta(seconds=5)),
        cutoff=_NOW,
        max_reverse_price_impact_fraction=Decimal("0.10"),
        max_quote_age_seconds=Decimal(30),
    )
    assert result.status == "UNKNOWN"


def test_stale_quote_is_fail() -> None:
    result = evaluate_pre_entry_sellability(
        _sellable_evidence(reverse_quote_at=_NOW - timedelta(seconds=120)),
        cutoff=_NOW,
        max_reverse_price_impact_fraction=Decimal("0.10"),
        max_quote_age_seconds=Decimal(30),
    )
    assert result.status == "FAIL"
