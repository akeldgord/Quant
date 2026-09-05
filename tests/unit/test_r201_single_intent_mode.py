"""Clarification-001 section 2 (``argus-final-spec-recovery-002-
clarification-001``): ``argus.executor.main``'s single-intent mode must
be a no-op under repository defaults, and must fail CLOSED (never
silently proceed with an incomplete/spoofed configuration) whenever it
is explicitly configured but something required is missing. No database
is needed for any of these -- they all short-circuit before ever
touching a session."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from argus.clock import Clock
from argus.executor.arm import ApprovedIdentity, ArmValidationResult
from argus.executor.live_signing import ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR
from argus.executor.main import (
    ARGUS_EXECUTOR_CANARY_AUTHORIZATION_PATH_ENV_VAR,
    ARGUS_EXECUTOR_INTENT_PARAMS_PATH_ENV_VAR,
    ARGUS_EXECUTOR_SINGLE_INTENT_ID_ENV_VAR,
    SingleIntentConfigurationError,
    build_live_risk_inputs_from_params_file,
    run_single_intent_if_configured,
)
from argus.executor.singleton import LeaseHandle
from argus.providers.helius.client import HELIUS_API_KEY_ENV_VAR

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

_FULL_RISK_PARAMS: dict[str, object] = {
    "wallet_tier": "S",
    "wallet_qualification_score": "90",
    "min_qualification_score": "50",
    "signal_age_seconds": "1",
    "max_signal_age_seconds": "60",
    "token_mint_validated": True,
    "token_safety_status": "SAFE",
    "liquidity_usd": "100000",
    "minimum_liquidity_usd": "1000",
    "price_movement_since_leader_fraction": "0.01",
    "max_price_movement_fraction": "0.5",
    "quote_price_impact_fraction": "0.01",
    "max_price_impact_fraction": "0.5",
    "requested_slippage_bps": 50,
    "approved_slippage_ceiling_bps": 100,
    "existing_open_position_for_mint": False,
    "allow_automatic_scale_in": False,
    "current_total_exposure_sol": "0",
    "proposed_notional_sol": "1",
    "max_total_exposure_sol": "10",
    "current_daily_loss_sol": "0",
    "max_daily_loss_sol": "10",
    "duplicate_intent_exists": False,
    "conflicting_position_exists": False,
    "wallet_balance_sol": "5",
    "required_balance_sol": "1",
    "quote_age_seconds": "1",
    "max_quote_age_seconds": "30",
    "chain_freshness_lag_seconds": "1",
    "max_chain_freshness_lag_seconds": "30",
    "clock_healthy": True,
    "stream_reconciliation_healthy": True,
    "slippage_bps": 50,
    "max_total_fee_raw": 100_000,
}


class _PoisonSessionmaker:
    """Raises if ever called -- proves a code path never even attempted
    to open a database session."""

    def __call__(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("sessionmaker must never be called on this path")


def _approved() -> ApprovedIdentity:
    return ApprovedIdentity(
        git_commit="a" * 40,
        executor_build_hash="buildhash",
        risk_config_hash="confighash",
        strategy_versions=frozenset({"v1"}),
    )


def _unarmed() -> ArmValidationResult:
    return ArmValidationResult(armed=False, reason="ARGUS_LIVE_ARM_FILE_PATH not set")


@pytest.mark.asyncio
async def test_env_var_unset_is_a_complete_noop() -> None:
    """The repository default: ARGUS_EXECUTOR_SINGLE_INTENT_ID absent ->
    returns None without ever touching the sessionmaker/DB."""
    outcome = await run_single_intent_if_configured(
        env={},
        sessionmaker=_PoisonSessionmaker(),
        lease=LeaseHandle(owner_id=uuid.uuid4(), fencing_token=1, expires_at=_NOW),
        approved=_approved(),
        arm=_unarmed(),
        clock=Clock(),
        http_client=None,  # type: ignore[arg-type]
        signer=None,
        helius_api_key=None,
    )
    assert outcome is None


@pytest.mark.asyncio
async def test_intent_id_set_but_params_path_missing_fails_closed() -> None:
    with pytest.raises(SingleIntentConfigurationError):
        await run_single_intent_if_configured(
            env={ARGUS_EXECUTOR_SINGLE_INTENT_ID_ENV_VAR: str(uuid.uuid4())},
            sessionmaker=_PoisonSessionmaker(),
            lease=LeaseHandle(owner_id=uuid.uuid4(), fencing_token=1, expires_at=_NOW),
            approved=_approved(),
            arm=_unarmed(),
            clock=Clock(),
            http_client=None,  # type: ignore[arg-type]
            signer=None,
            helius_api_key=None,
        )


@pytest.mark.asyncio
async def test_invalid_intent_id_fails_closed() -> None:
    with pytest.raises(SingleIntentConfigurationError):
        await run_single_intent_if_configured(
            env={
                ARGUS_EXECUTOR_SINGLE_INTENT_ID_ENV_VAR: "not-a-uuid",
                ARGUS_EXECUTOR_INTENT_PARAMS_PATH_ENV_VAR: "/dev/null",
            },
            sessionmaker=_PoisonSessionmaker(),
            lease=LeaseHandle(owner_id=uuid.uuid4(), fencing_token=1, expires_at=_NOW),
            approved=_approved(),
            arm=_unarmed(),
            clock=Clock(),
            http_client=None,  # type: ignore[arg-type]
            signer=None,
            helius_api_key=None,
        )


@pytest.mark.asyncio
async def test_no_signer_configured_fails_closed_before_touching_db(tmp_path: Path) -> None:
    params_path = tmp_path / "params.json"
    params_path.write_text(json.dumps(_FULL_RISK_PARAMS))
    with pytest.raises(
        SingleIntentConfigurationError, match=ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR
    ):
        await run_single_intent_if_configured(
            env={
                ARGUS_EXECUTOR_SINGLE_INTENT_ID_ENV_VAR: str(uuid.uuid4()),
                ARGUS_EXECUTOR_INTENT_PARAMS_PATH_ENV_VAR: str(params_path),
            },
            sessionmaker=_PoisonSessionmaker(),
            lease=LeaseHandle(owner_id=uuid.uuid4(), fencing_token=1, expires_at=_NOW),
            approved=_approved(),
            arm=_unarmed(),
            clock=Clock(),
            http_client=None,  # type: ignore[arg-type]
            signer=None,
            helius_api_key=None,
        )


@pytest.mark.asyncio
async def test_no_helius_api_key_fails_closed_before_touching_db(tmp_path: Path) -> None:
    from argus.executor.signing import FakeSigner

    params_path = tmp_path / "params.json"
    params_path.write_text(json.dumps(_FULL_RISK_PARAMS))
    with pytest.raises(SingleIntentConfigurationError, match=HELIUS_API_KEY_ENV_VAR):
        await run_single_intent_if_configured(
            env={
                ARGUS_EXECUTOR_SINGLE_INTENT_ID_ENV_VAR: str(uuid.uuid4()),
                ARGUS_EXECUTOR_INTENT_PARAMS_PATH_ENV_VAR: str(params_path),
            },
            sessionmaker=_PoisonSessionmaker(),
            lease=LeaseHandle(owner_id=uuid.uuid4(), fencing_token=1, expires_at=_NOW),
            approved=_approved(),
            arm=_unarmed(),
            clock=Clock(),
            http_client=None,  # type: ignore[arg-type]
            signer=FakeSigner(public_key="fake-pubkey"),  # type: ignore[arg-type]
            helius_api_key=None,
        )


def test_params_file_missing_required_field_fails_closed(tmp_path: Path) -> None:
    incomplete = dict(_FULL_RISK_PARAMS)
    del incomplete["wallet_tier"]
    params_path = tmp_path / "params.json"
    params_path.write_text(json.dumps(incomplete))
    with pytest.raises(SingleIntentConfigurationError, match="wallet_tier"):
        build_live_risk_inputs_from_params_file(
            params_path=params_path, approved=_approved(), arm=_unarmed(), canary_passed=False
        )


def test_params_file_cannot_spoof_identity_arm_or_canary(tmp_path: Path) -> None:
    """Even if an operator's params file tries to smuggle in
    canary_passed=True or a forged arm_result/identity, those keys are
    never read -- only the real, structurally-computed values (here the
    caller's own honestly-computed ``canary_passed=False``, matching
    "ordinary execution with no prior canary PASS") are ever used for
    those fields."""
    spoofed = dict(_FULL_RISK_PARAMS)
    spoofed["canary_passed"] = True
    spoofed["arm_result"] = {"armed": True}
    spoofed["running_git_commit"] = "z" * 40
    params_path = tmp_path / "params.json"
    params_path.write_text(json.dumps(spoofed))

    risk_inputs = build_live_risk_inputs_from_params_file(
        params_path=params_path, approved=_approved(), arm=_unarmed(), canary_passed=False
    )
    assert risk_inputs.canary_passed is False
    assert risk_inputs.arm_result.armed is False
    assert risk_inputs.running_git_commit == _approved().git_commit


def test_ordinary_execution_with_no_prior_canary_pass_is_rejected(tmp_path: Path) -> None:
    """Clarification-002 section 2's own named scenario: ordinary
    single-intent mode (no canary-authorization env var) with no prior
    persisted canary PASS must construct ``canary_passed=False`` -- the
    ``canary_status`` gate then fails, rejecting the intent, exactly as
    before this mechanism existed."""
    from argus.executor.risk_gates import build_gates, evaluate_live_risk

    params_path = tmp_path / "params.json"
    params_path.write_text(json.dumps(_FULL_RISK_PARAMS))
    risk_inputs = build_live_risk_inputs_from_params_file(
        params_path=params_path, approved=_approved(), arm=_unarmed(), canary_passed=False
    )
    result = evaluate_live_risk(build_gates(risk_inputs))
    assert result.approved is False
    assert "canary_status" in result.reason_codes


def test_valid_canary_authorization_constructs_canary_passed_true_but_other_gates_still_apply(
    tmp_path: Path,
) -> None:
    """Section 2 requirement 3: the canary-authorized path still remains
    subject to every other existing risk gate -- here, no valid arm file
    means ``human_arm_validity`` still fails even though
    ``canary_passed=True`` was honestly constructed from a validated
    authorization."""
    from argus.executor.risk_gates import build_gates, evaluate_live_risk

    params_path = tmp_path / "params.json"
    params_path.write_text(json.dumps(_FULL_RISK_PARAMS))
    risk_inputs = build_live_risk_inputs_from_params_file(
        params_path=params_path, approved=_approved(), arm=_unarmed(), canary_passed=True
    )
    assert risk_inputs.canary_passed is True
    result = evaluate_live_risk(build_gates(risk_inputs))
    assert result.approved is False
    assert "canary_status" not in result.reason_codes
    assert "human_arm_validity" in result.reason_codes


@pytest.mark.asyncio
async def test_canary_attempt_with_missing_authorization_file_fails_closed_before_db(
    tmp_path: Path,
) -> None:
    """Clarification-002 section 2's own mandatory scenario: missing/
    expired/mismatched canary authorization fails closed before signing/
    submission -- proven here even before the DB is ever touched
    (``_PoisonSessionmaker`` would raise if it were)."""
    from argus.executor.signing import FakeSigner

    params_path = tmp_path / "params.json"
    params_path.write_text(json.dumps(_FULL_RISK_PARAMS))
    with pytest.raises(SingleIntentConfigurationError, match="canary authorization"):
        await run_single_intent_if_configured(
            env={
                ARGUS_EXECUTOR_SINGLE_INTENT_ID_ENV_VAR: str(uuid.uuid4()),
                ARGUS_EXECUTOR_INTENT_PARAMS_PATH_ENV_VAR: str(params_path),
                ARGUS_EXECUTOR_CANARY_AUTHORIZATION_PATH_ENV_VAR: str(
                    tmp_path / "does-not-exist.json"
                ),
            },
            sessionmaker=_PoisonSessionmaker(),
            lease=LeaseHandle(owner_id=uuid.uuid4(), fencing_token=1, expires_at=_NOW),
            approved=_approved(),
            arm=_unarmed(),
            clock=Clock(),
            http_client=None,  # type: ignore[arg-type]
            signer=FakeSigner(public_key="fake-pubkey"),  # type: ignore[arg-type]
            helius_api_key="fake-helius-key",
        )


@pytest.mark.asyncio
async def test_canary_attempt_with_expired_authorization_fails_closed_before_db(
    tmp_path: Path,
) -> None:
    intent_id = uuid.uuid4()
    canary_path = tmp_path / "canary.json"
    canary_path.write_text(
        json.dumps(
            {
                "canary_authorized": True,
                "intent_id": str(intent_id),
                "expires_at": (_NOW - timedelta(seconds=1)).isoformat(),
                "approved_git_commit": _approved().git_commit,
                "approved_executor_build_hash": _approved().executor_build_hash,
                "approved_risk_config_hash": _approved().risk_config_hash,
            }
        )
    )
    from argus.executor.signing import FakeSigner

    params_path = tmp_path / "params.json"
    params_path.write_text(json.dumps(_FULL_RISK_PARAMS))
    with pytest.raises(SingleIntentConfigurationError, match="canary authorization"):
        await run_single_intent_if_configured(
            env={
                ARGUS_EXECUTOR_SINGLE_INTENT_ID_ENV_VAR: str(intent_id),
                ARGUS_EXECUTOR_INTENT_PARAMS_PATH_ENV_VAR: str(params_path),
                ARGUS_EXECUTOR_CANARY_AUTHORIZATION_PATH_ENV_VAR: str(canary_path),
            },
            sessionmaker=_PoisonSessionmaker(),
            lease=LeaseHandle(owner_id=uuid.uuid4(), fencing_token=1, expires_at=_NOW),
            approved=_approved(),
            arm=_unarmed(),
            clock=Clock(),
            http_client=None,  # type: ignore[arg-type]
            signer=FakeSigner(public_key="fake-pubkey"),  # type: ignore[arg-type]
            helius_api_key="fake-helius-key",
        )


@pytest.mark.asyncio
async def test_canary_attempt_authorized_for_a_different_intent_fails_closed_before_db(
    tmp_path: Path,
) -> None:
    """An authorization bound to one intent must never be reusable for a
    different, later intent."""
    canary_path = tmp_path / "canary.json"
    canary_path.write_text(
        json.dumps(
            {
                "canary_authorized": True,
                "intent_id": str(uuid.uuid4()),  # a DIFFERENT intent
                "expires_at": (_NOW + timedelta(hours=1)).isoformat(),
                "approved_git_commit": _approved().git_commit,
                "approved_executor_build_hash": _approved().executor_build_hash,
                "approved_risk_config_hash": _approved().risk_config_hash,
            }
        )
    )
    from argus.executor.signing import FakeSigner

    params_path = tmp_path / "params.json"
    params_path.write_text(json.dumps(_FULL_RISK_PARAMS))
    with pytest.raises(SingleIntentConfigurationError, match="canary authorization"):
        await run_single_intent_if_configured(
            env={
                ARGUS_EXECUTOR_SINGLE_INTENT_ID_ENV_VAR: str(uuid.uuid4()),
                ARGUS_EXECUTOR_INTENT_PARAMS_PATH_ENV_VAR: str(params_path),
                ARGUS_EXECUTOR_CANARY_AUTHORIZATION_PATH_ENV_VAR: str(canary_path),
            },
            sessionmaker=_PoisonSessionmaker(),
            lease=LeaseHandle(owner_id=uuid.uuid4(), fencing_token=1, expires_at=_NOW),
            approved=_approved(),
            arm=_unarmed(),
            clock=Clock(),
            http_client=None,  # type: ignore[arg-type]
            signer=FakeSigner(public_key="fake-pubkey"),  # type: ignore[arg-type]
            helius_api_key="fake-helius-key",
        )
