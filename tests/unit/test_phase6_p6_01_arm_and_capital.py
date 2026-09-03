"""P6-01 (SPEC_BLOCKING): live defaults and authority fail closed --
MASTER_SPEC.md sections 73 (LIVE ARMING) and 74 (DEFAULT CAPITAL
CONFIGURATION), orchestrator instruction ``argus-phase-6-001``.

Repository defaults for max single trade, total exposure, and daily loss
are exactly zero; an absent, malformed, expired, or hash-mismatched arm
file always disables live execution with an explicit reason -- no
fallback ever enables execution.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from argus.executor.arm import ApprovedIdentity, validate_arm_file
from argus.executor.capital import (
    LIVE_MAX_DAILY_LOSS_SOL,
    LIVE_MAX_SINGLE_TRADE_SOL,
    LIVE_MAX_TOTAL_EXPOSURE_SOL,
    RiskMultiplier,
    scaled_notional,
)

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_APPROVED = ApprovedIdentity(
    git_commit="a" * 40,
    executor_build_hash="b" * 64,
    risk_config_hash="c" * 64,
    strategy_versions=frozenset({"strategy_v1"}),
)


def _valid_arm_payload(**overrides: object) -> dict:
    payload = {
        "armed": True,
        "expires_at": (_NOW + timedelta(hours=1)).isoformat(),
        "approved_git_commit": _APPROVED.git_commit,
        "approved_executor_build_hash": _APPROVED.executor_build_hash,
        "approved_risk_config_hash": _APPROVED.risk_config_hash,
        "approved_strategy_versions": ["strategy_v1"],
        "max_single_trade_sol": "0.5",
        "max_total_exposure_sol": "2",
        "max_daily_loss_sol": "1",
    }
    payload.update(overrides)
    return payload


def test_zero_default_capital() -> None:
    assert Decimal(0) == LIVE_MAX_SINGLE_TRADE_SOL
    assert Decimal(0) == LIVE_MAX_TOTAL_EXPOSURE_SOL
    assert Decimal(0) == LIVE_MAX_DAILY_LOSS_SOL


def test_scaled_notional_never_exceeds_normal() -> None:
    normal = Decimal(10)
    for multiplier in RiskMultiplier:
        assert scaled_notional(normal, multiplier) <= normal


def test_missing_arm_file_disables_live_execution(tmp_path: Path) -> None:
    result = validate_arm_file(tmp_path / "does_not_exist.json", approved=_APPROVED, now=_NOW)
    assert result.armed is False
    assert result.reason is not None
    assert result.max_single_trade_sol is None


def test_malformed_json_arm_file_disables_live_execution(tmp_path: Path) -> None:
    path = tmp_path / "arm.json"
    path.write_text("{not valid json")
    result = validate_arm_file(path, approved=_APPROVED, now=_NOW)
    assert result.armed is False
    assert "malformed" in (result.reason or "").lower()


def test_arm_file_not_a_json_object_disables_live_execution(tmp_path: Path) -> None:
    path = tmp_path / "arm.json"
    path.write_text(json.dumps([1, 2, 3]))
    result = validate_arm_file(path, approved=_APPROVED, now=_NOW)
    assert result.armed is False


def test_armed_not_literal_true_disables_live_execution(tmp_path: Path) -> None:
    path = tmp_path / "arm.json"
    path.write_text(json.dumps(_valid_arm_payload(armed="true")))
    result = validate_arm_file(path, approved=_APPROVED, now=_NOW)
    assert result.armed is False


def test_expired_arm_file_disables_live_execution(tmp_path: Path) -> None:
    path = tmp_path / "arm.json"
    payload = _valid_arm_payload(expires_at=(_NOW - timedelta(seconds=1)).isoformat())
    path.write_text(json.dumps(payload))
    result = validate_arm_file(path, approved=_APPROVED, now=_NOW)
    assert result.armed is False
    assert "expired" in (result.reason or "").lower()


def test_naive_expires_at_disables_live_execution(tmp_path: Path) -> None:
    path = tmp_path / "arm.json"
    payload = _valid_arm_payload(expires_at="2099-01-01T00:00:00")
    path.write_text(json.dumps(payload))
    result = validate_arm_file(path, approved=_APPROVED, now=_NOW)
    assert result.armed is False


def test_git_commit_hash_mismatch_disables_live_execution(tmp_path: Path) -> None:
    path = tmp_path / "arm.json"
    payload = _valid_arm_payload(approved_git_commit="d" * 40)
    path.write_text(json.dumps(payload))
    result = validate_arm_file(path, approved=_APPROVED, now=_NOW)
    assert result.armed is False
    assert "git_commit" in (result.reason or "")


def test_build_hash_mismatch_disables_live_execution(tmp_path: Path) -> None:
    path = tmp_path / "arm.json"
    payload = _valid_arm_payload(approved_executor_build_hash="e" * 64)
    path.write_text(json.dumps(payload))
    result = validate_arm_file(path, approved=_APPROVED, now=_NOW)
    assert result.armed is False
    assert "build_hash" in (result.reason or "")


def test_risk_config_hash_mismatch_disables_live_execution(tmp_path: Path) -> None:
    path = tmp_path / "arm.json"
    payload = _valid_arm_payload(approved_risk_config_hash="f" * 64)
    path.write_text(json.dumps(payload))
    result = validate_arm_file(path, approved=_APPROVED, now=_NOW)
    assert result.armed is False
    assert "risk_config_hash" in (result.reason or "")


def test_strategy_version_not_in_approved_set_disables_live_execution(tmp_path: Path) -> None:
    path = tmp_path / "arm.json"
    payload = _valid_arm_payload(approved_strategy_versions=["strategy_v2"])
    path.write_text(json.dumps(payload))
    result = validate_arm_file(path, approved=_APPROVED, now=_NOW)
    assert result.armed is False


def test_negative_capital_field_disables_live_execution(tmp_path: Path) -> None:
    path = tmp_path / "arm.json"
    payload = _valid_arm_payload(max_single_trade_sol="-1")
    path.write_text(json.dumps(payload))
    result = validate_arm_file(path, approved=_APPROVED, now=_NOW)
    assert result.armed is False


def test_missing_required_field_disables_live_execution(tmp_path: Path) -> None:
    path = tmp_path / "arm.json"
    payload = _valid_arm_payload()
    del payload["max_daily_loss_sol"]
    path.write_text(json.dumps(payload))
    result = validate_arm_file(path, approved=_APPROVED, now=_NOW)
    assert result.armed is False


def test_fully_valid_arm_file_arms_with_evidenced_capital(tmp_path: Path) -> None:
    """The positive control: proves the fail-closed tests above are
    actually exercising a validator capable of returning armed=True, not
    one that always fails regardless of input."""
    path = tmp_path / "arm.json"
    path.write_text(json.dumps(_valid_arm_payload()))
    result = validate_arm_file(path, approved=_APPROVED, now=_NOW)
    assert result.armed is True
    assert result.max_single_trade_sol == Decimal("0.5")
    assert result.max_total_exposure_sol == Decimal("2")
    assert result.max_daily_loss_sol == Decimal("1")


def test_arm_file_never_written_by_validator(tmp_path: Path) -> None:
    """validate_arm_file is read-only -- proves it never creates the file
    it was asked to validate."""
    path = tmp_path / "never_created.json"
    validate_arm_file(path, approved=_APPROVED, now=_NOW)
    assert not path.exists()
