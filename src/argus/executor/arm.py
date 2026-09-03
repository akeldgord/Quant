"""argus.executor.arm — MASTER_SPEC.md section 73 (LIVE ARMING), Phase 6
(``argus-phase-6-001``).

Reads and validates the EXTERNAL, human-controlled arm file. This
module NEVER creates or modifies that file -- it only opens it for
reading -- and always returns an explicit :class:`ArmValidationResult`;
a missing, malformed, expired, or hash-mismatched file always yields
``armed=False`` with a specific reason (fail closed, section 73's own
explicit rule: "Missing, malformed, expired, or hash-mismatched arm
file: LIVE_EXECUTION = DISABLED").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

_REQUIRED_STRING_FIELDS: tuple[str, ...] = (
    "expires_at",
    "approved_git_commit",
    "approved_executor_build_hash",
    "approved_risk_config_hash",
)
_REQUIRED_DECIMAL_FIELDS: tuple[str, ...] = (
    "max_single_trade_sol",
    "max_total_exposure_sol",
    "max_daily_loss_sol",
)


@dataclass(frozen=True)
class ApprovedIdentity:
    """The running build's own identity -- an arm file approved for a
    different git commit/executor build/risk config can never arm this
    running build."""

    git_commit: str
    executor_build_hash: str
    risk_config_hash: str
    strategy_versions: frozenset[str]


@dataclass(frozen=True)
class ArmValidationResult:
    armed: bool
    reason: str | None = None
    max_single_trade_sol: Decimal | None = None
    max_total_exposure_sol: Decimal | None = None
    max_daily_loss_sol: Decimal | None = None


def validate_arm_file(
    path: Path, *, approved: ApprovedIdentity, now: datetime
) -> ArmValidationResult:
    """Read-only -- never writes ``path``. Fails closed (``armed=False``)
    on any problem: missing file, unreadable file, malformed JSON,
    wrong shape, missing/invalid field, expiry, or any approved_*
    mismatch."""
    if not path.exists():
        return ArmValidationResult(armed=False, reason="arm file missing")
    try:
        raw = path.read_text()
    except OSError as exc:
        return ArmValidationResult(armed=False, reason=f"arm file unreadable: {exc}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ArmValidationResult(armed=False, reason=f"arm file malformed JSON: {exc}")
    if not isinstance(data, dict):
        return ArmValidationResult(armed=False, reason="arm file is not a JSON object")

    if data.get("armed") is not True:
        return ArmValidationResult(armed=False, reason="arm file 'armed' is not literal true")

    for field in _REQUIRED_STRING_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value:
            return ArmValidationResult(armed=False, reason=f"missing/invalid field: {field}")

    strategy_versions = data.get("approved_strategy_versions")
    if not isinstance(strategy_versions, list) or not strategy_versions:
        return ArmValidationResult(
            armed=False, reason="missing/invalid field: approved_strategy_versions"
        )
    if not all(isinstance(v, str) and v for v in strategy_versions):
        return ArmValidationResult(
            armed=False,
            reason="approved_strategy_versions contains a non-string/empty entry",
        )

    decimals: dict[str, Decimal] = {}
    for field in _REQUIRED_DECIMAL_FIELDS:
        raw_value = data.get(field)
        if raw_value is None or isinstance(raw_value, bool):
            return ArmValidationResult(armed=False, reason=f"missing/invalid field: {field}")
        try:
            value = Decimal(str(raw_value))
        except (InvalidOperation, ValueError):
            return ArmValidationResult(armed=False, reason=f"missing/invalid field: {field}")
        if not value.is_finite() or value < 0:
            return ArmValidationResult(armed=False, reason=f"missing/invalid field: {field}")
        decimals[field] = value

    try:
        expires_at = datetime.fromisoformat(str(data["expires_at"]))
    except ValueError:
        return ArmValidationResult(armed=False, reason="expires_at is not valid ISO-8601")
    if expires_at.tzinfo is None:
        return ArmValidationResult(armed=False, reason="expires_at is not timezone-aware")
    if expires_at <= now:
        return ArmValidationResult(armed=False, reason="arm file expired")

    if data["approved_git_commit"] != approved.git_commit:
        return ArmValidationResult(armed=False, reason="approved_git_commit mismatch")
    if data["approved_executor_build_hash"] != approved.executor_build_hash:
        return ArmValidationResult(armed=False, reason="approved_executor_build_hash mismatch")
    if data["approved_risk_config_hash"] != approved.risk_config_hash:
        return ArmValidationResult(armed=False, reason="approved_risk_config_hash mismatch")
    if not set(strategy_versions) & approved.strategy_versions:
        return ArmValidationResult(
            armed=False,
            reason="approved_strategy_versions does not include the running strategy",
        )

    return ArmValidationResult(
        armed=True,
        max_single_trade_sol=decimals["max_single_trade_sol"],
        max_total_exposure_sol=decimals["max_total_exposure_sol"],
        max_daily_loss_sol=decimals["max_daily_loss_sol"],
    )
