"""argus.executor.main — MASTER_SPEC.md section 70 (LIVE EXECUTION
SECURITY MODEL) / section 75 (EXECUTOR SINGLETON), FSR-01
(``argus-final-spec-recovery-001``), single-intent wiring per
``argus-final-spec-recovery-002-clarification-001`` section 2.

The distinct executor PROCESS entry point (``python -m argus.executor.main``,
the ``executor`` service in ``compose.yaml``) -- structurally separate from
``argus.cli``/``argus.api`` (neither of which import this module, or
``argus.executor.live_signing``/``argus.executor.live_submission``, proven
by ``tests/unit/test_fsr01_live_signer_isolation_boundary.py``). This is
the ONLY process identity in this codebase that ever constructs a real
:class:`~argus.executor.live_signing.FileKeypairSigner` or a real
:class:`~argus.executor.live_submission.SolanaSubmissionClient`.

Scope (FSR-01): proves the BOUNDARY -- singleton-fenced process
separation, fail-closed real-key loading from an external
operator-controlled path, a production-capable submission adapter, and a
distinct least-privilege deployment identity.

Clarification-001 section 2: the boundary above is now also WIRED to
:func:`~argus.executor.pipeline.execute_intent_pipeline` via a safe
single-intent mode (:func:`run_single_intent_if_configured`) -- no
automatic trading daemon, signal-consumer loop, scheduler, or live
strategy engine exists, and none is added here. Under repository
defaults (``ARGUS_EXECUTOR_SINGLE_INTENT_ID`` unset) this module's
behavior is byte-for-byte unchanged from before: startup/readiness only,
never touching the pipeline. Even when single-intent mode IS configured,
the risk gates the pipeline itself evaluates make live dispatch
structurally impossible without separate, external authorization: this
module can never construct ``canary_passed=True`` (there is no persisted
"Phase 6.5 canary passed" record anywhere in this codebase -- Phase 6.5
is explicitly human-only and never self-executed, so no code path here
has a way to produce that value), and ``arm_result.armed`` can only be
``True`` if an external, human-authored, hash/expiry-validated arm file
exists at ``ARGUS_LIVE_ARM_FILE_PATH`` (see ``argus.executor.arm``, which
this module never writes). ``LIVE_ARMED`` in :class:`ExecutorStartupReport`
is therefore still unconditionally ``False`` -- it describes this
module's own top-level disposition, never the pipeline's own internal
(and separately gated) risk evaluation.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, fields
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from argus.clock import Clock
from argus.config import ArgusConfig, load_config, resolve_production_git_commit
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.execution_intents import ExecutionIntent
from argus.domain.tokens import Token
from argus.executor.arm import ApprovedIdentity, ArmValidationResult, validate_arm_file
from argus.executor.dispatch import DispatchGuard
from argus.executor.live_signing import (
    ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR,
    FileKeypairSigner,
    SignerKeyLoadError,
)
from argus.executor.live_submission import SolanaSubmissionClient
from argus.executor.pipeline import PipelineDependencies, PipelineOutcome, execute_intent_pipeline
from argus.executor.risk_gates import LiveRiskInputs
from argus.executor.service import BUILD_HASH, build_phase6_disposition
from argus.executor.simulation import SolanaTransactionSimulationClient
from argus.executor.singleton import LeaseHandle, LeaseStore, PostgresLeaseStore, acquire_or_refuse
from argus.logging import get_logger
from argus.providers.helius.client import HELIUS_API_KEY_ENV_VAR, HeliusRpcClient
from argus.providers.jupiter.client import JupiterClient

_logger = get_logger(component="argus.executor.main")

ARGUS_LIVE_ARM_FILE_PATH_ENV_VAR = "ARGUS_LIVE_ARM_FILE_PATH"
_DEFAULT_LEASE_TTL = timedelta(seconds=30)

# Clarification-001 section 2: single-intent mode is entirely opt-in via
# these two env vars. Absent (the repository default), main() behaves
# exactly as it always has -- see run_single_intent_if_configured's own
# docstring.
ARGUS_EXECUTOR_SINGLE_INTENT_ID_ENV_VAR = "ARGUS_EXECUTOR_SINGLE_INTENT_ID"
ARGUS_EXECUTOR_INTENT_PARAMS_PATH_ENV_VAR = "ARGUS_EXECUTOR_INTENT_PARAMS_PATH"

# LiveRiskInputs fields this module NEVER takes from the operator-supplied
# params file -- always the real, structurally-computed identity/arm/
# canary values, so a params file can never spoof software readiness, arm
# validity, or canary status.
_LIVE_RISK_INPUTS_REAL_ONLY_FIELDS = frozenset(
    {
        "software_readiness",
        "canary_passed",
        "arm_result",
        "running_git_commit",
        "running_executor_build_hash",
        "running_risk_config_hash",
        "approved_git_commit",
        "approved_executor_build_hash",
        "approved_risk_config_hash",
    }
)


class SingleIntentConfigurationError(RuntimeError):
    """Single-intent mode was requested (``ARGUS_EXECUTOR_SINGLE_INTENT_ID``
    set) but its required configuration is missing/invalid -- fails
    closed (no pipeline call) rather than silently guessing a default."""


def _decode_risk_input_field(field_type: Any, raw: Any) -> Any:
    """Best-effort JSON->dataclass-field decode for the handful of
    non-JSON-native types :class:`LiveRiskInputs` uses (``Decimal``) --
    everything else (``bool``, ``str``, ``int``, ``None``) round-trips
    through JSON unchanged."""
    if raw is None:
        return None
    type_str = str(field_type)
    if "Decimal" in type_str:
        return Decimal(str(raw))
    return raw


def build_live_risk_inputs_from_params_file(
    *, params_path: Path, approved: ApprovedIdentity, arm: ArmValidationResult
) -> LiveRiskInputs:
    """Assembles a real :class:`LiveRiskInputs` for the single-intent
    path. The identity/arm/canary fields are ALWAYS the real values
    computed by this process -- never read from ``params_path`` (see
    ``_LIVE_RISK_INPUTS_REAL_ONLY_FIELDS``) -- so an operator-supplied
    params file can only ever describe market/wallet state this module
    has no other live data source for (wallet tier/qualification,
    exposure, liquidity, chain freshness, etc.), never the fields that
    gate whether live dispatch is even reachable at all.

    ``canary_passed`` is unconditionally ``False``: there is no persisted
    "Phase 6.5 canary passed" record anywhere in this codebase (Phase 6.5
    is explicitly human-only and never self-executed here), so no code
    path in this module can ever produce ``True`` for it."""
    try:
        raw = json.loads(params_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SingleIntentConfigurationError(
            f"could not read/parse intent params file {params_path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise SingleIntentConfigurationError(
            f"intent params file {params_path} must contain a JSON object"
        )

    overrides: dict[str, Any] = {}
    for f in fields(LiveRiskInputs):
        if f.name in _LIVE_RISK_INPUTS_REAL_ONLY_FIELDS:
            continue
        if f.name not in raw:
            raise SingleIntentConfigurationError(
                f"intent params file {params_path} is missing required field {f.name!r}"
            )
        overrides[f.name] = _decode_risk_input_field(f.type, raw[f.name])

    return LiveRiskInputs(
        software_readiness=True,
        canary_passed=False,
        arm_result=arm,
        running_git_commit=approved.git_commit,
        running_executor_build_hash=approved.executor_build_hash,
        running_risk_config_hash=approved.risk_config_hash,
        approved_git_commit=approved.git_commit,
        approved_executor_build_hash=approved.executor_build_hash,
        approved_risk_config_hash=approved.risk_config_hash,
        **overrides,
    )


@dataclass(frozen=True)
class ExecutorStartupReport:
    """What this process actually proved on this run -- never a claim of
    live readiness (see this module's own docstring)."""

    lease: LeaseHandle
    signer_public_key: str | None
    """Public key of the loaded real signer, or ``None`` if
    ``ARGUS_EXECUTOR_SIGNER_KEY_PATH`` was not set. Never the key
    material itself."""
    submission_adapter_constructed: bool
    arm: ArmValidationResult
    live_armed: bool
    """Unconditionally ``False`` -- see module docstring."""


async def run_executor_startup(
    *,
    env: dict[str, str],
    lease_store: LeaseStore,
    owner_id: uuid.UUID,
    approved: ApprovedIdentity,
    clock: Clock,
    http_client: httpx.AsyncClient | None = None,
) -> ExecutorStartupReport:
    """The testable core of the executor process's startup sequence --
    takes every external dependency (env, lease store, identity, clock,
    http client) as a parameter so this can be exercised without a real
    DB, a real key file, a real network, or a real process. ``main()`` is
    the thin real-dependency wiring around this function."""
    now = clock.utc_now()
    lease = await acquire_or_refuse(lease_store, owner_id=owner_id, ttl=_DEFAULT_LEASE_TTL, now=now)

    signer_public_key: str | None = None
    if env.get(ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR):
        # Fail closed: if the operator configured a key path, it must
        # load successfully -- never silently proceed key-less.
        signer = FileKeypairSigner.from_env(env)
        signer_public_key = signer.public_key
        _logger.info("executor_signer_loaded", public_key=signer_public_key)
    else:
        _logger.info("executor_signer_not_configured")

    # Constructing the client proves the production-capable submission
    # adapter is real and reachable from this process -- it is never
    # called (no .send_transaction() call exists anywhere in this
    # module), so this alone can never broadcast anything.
    submission_adapter_constructed = False
    helius_api_key = env.get(HELIUS_API_KEY_ENV_VAR)
    if helius_api_key and http_client is not None:
        SolanaSubmissionClient(http_client=http_client, api_key=helius_api_key, clock=clock)
        submission_adapter_constructed = True
        _logger.info("executor_submission_adapter_constructed")
    else:
        _logger.info("executor_submission_adapter_not_configured")

    arm_path_raw = env.get(ARGUS_LIVE_ARM_FILE_PATH_ENV_VAR)
    if arm_path_raw:
        arm = validate_arm_file(Path(arm_path_raw), approved=approved, now=now)
    else:
        arm = ArmValidationResult(armed=False, reason="ARGUS_LIVE_ARM_FILE_PATH not set")
    _logger.info("executor_arm_checked", armed=arm.armed, reason=arm.reason)

    return ExecutorStartupReport(
        lease=lease,
        signer_public_key=signer_public_key,
        submission_adapter_constructed=submission_adapter_constructed,
        arm=arm,
        live_armed=False,
    )


async def run_single_intent_if_configured(
    *,
    env: dict[str, str],
    sessionmaker: Any,
    lease: LeaseHandle,
    approved: ApprovedIdentity,
    arm: ArmValidationResult,
    clock: Clock,
    http_client: httpx.AsyncClient,
    signer: FileKeypairSigner | None,
    helius_api_key: str | None,
) -> PipelineOutcome | None:
    """Clarification-001 section 2's single-intent mode: the actual code
    path connecting ``main`` -> ``execute_intent_pipeline`` -> signer ->
    submission -> reconciliation, using the REAL production-capable
    adapters this process already constructed at startup. Returns
    ``None`` (no-op; ``main()``'s behavior is then byte-for-byte
    unchanged from before this function existed) whenever
    ``ARGUS_EXECUTOR_SINGLE_INTENT_ID`` is unset -- the repository
    default. When it IS set, every other requirement below still fails
    CLOSED (raises :class:`SingleIntentConfigurationError`, never
    silently skips or fabricates a default) rather than proceeding with
    an incomplete configuration."""
    intent_id_raw = env.get(ARGUS_EXECUTOR_SINGLE_INTENT_ID_ENV_VAR)
    if not intent_id_raw:
        return None

    try:
        intent_id = uuid.UUID(intent_id_raw)
    except ValueError as exc:
        raise SingleIntentConfigurationError(
            f"{ARGUS_EXECUTOR_SINGLE_INTENT_ID_ENV_VAR}={intent_id_raw!r} is not a valid UUID"
        ) from exc

    params_path_raw = env.get(ARGUS_EXECUTOR_INTENT_PARAMS_PATH_ENV_VAR)
    if not params_path_raw:
        raise SingleIntentConfigurationError(
            f"{ARGUS_EXECUTOR_SINGLE_INTENT_ID_ENV_VAR} is set but "
            f"{ARGUS_EXECUTOR_INTENT_PARAMS_PATH_ENV_VAR} is not"
        )
    params_path = Path(params_path_raw)
    try:
        params_raw = json.loads(params_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SingleIntentConfigurationError(
            f"could not read/parse intent params file {params_path}: {exc}"
        ) from exc
    if not isinstance(params_raw, dict):
        raise SingleIntentConfigurationError(
            f"intent params file {params_path} must be a JSON object"
        )
    slippage_bps = params_raw.get("slippage_bps")
    max_total_fee_raw = params_raw.get("max_total_fee_raw")
    if not isinstance(slippage_bps, int) or not isinstance(max_total_fee_raw, int):
        raise SingleIntentConfigurationError(
            f"intent params file {params_path} must include integer 'slippage_bps' and "
            "'max_total_fee_raw'"
        )

    if signer is None:
        raise SingleIntentConfigurationError(
            f"{ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR} must be set for single-intent mode"
        )
    if not helius_api_key:
        raise SingleIntentConfigurationError(
            f"{HELIUS_API_KEY_ENV_VAR} must be set for single-intent mode "
            "(quote/simulation/confirmation all need a real RPC endpoint)"
        )

    risk_inputs = build_live_risk_inputs_from_params_file(
        params_path=params_path, approved=approved, arm=arm
    )

    async with sessionmaker() as session:
        intent = await session.get(ExecutionIntent, intent_id)
        if intent is None:
            raise SingleIntentConfigurationError(f"no ExecutionIntent found for id {intent_id}")
        token = await session.get(Token, intent.token_id)
        if token is None:
            raise SingleIntentConfigurationError(
                f"no Token found for intent {intent_id}'s token_id {intent.token_id}"
            )

        deps = PipelineDependencies(
            quote_provider=JupiterClient(http_client=http_client, clock=clock),
            simulation_provider=SolanaTransactionSimulationClient(
                http_client=http_client, api_key=helius_api_key, clock=clock
            ),
            confirmation_provider=HeliusRpcClient(
                helius_api_key, http_client=http_client, clock=clock
            ),
            dispatch=DispatchGuard(
                signer=signer,
                submit=SolanaSubmissionClient(
                    http_client=http_client, api_key=helius_api_key, clock=clock
                ).send_transaction,
            ),
        )
        return await execute_intent_pipeline(
            session,
            intent=intent,
            lease=lease,
            now=clock.utc_now(),
            risk_inputs=risk_inputs,
            executor_wallet_public_key=signer.public_key,
            token_mint=token.mint,
            slippage_bps=slippage_bps,
            max_total_fee_raw=max_total_fee_raw,
            deps=deps,
        )


async def _main_async() -> tuple[ExecutorStartupReport, PipelineOutcome | None]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    config: ArgusConfig = load_config()
    connection = connection_for_role(config, DbRole.EXECUTOR)

    engine = create_async_engine(connection.as_asyncpg_url())
    try:
        async with engine.connect() as conn, httpx.AsyncClient() as http_client:
            lease_store = PostgresLeaseStore(conn)
            disposition = build_phase6_disposition()
            _logger.info("executor_startup_software_disposition", **disposition.as_dict())

            approved = ApprovedIdentity(
                git_commit=resolve_production_git_commit(allow_unverified=True),
                executor_build_hash=BUILD_HASH,
                risk_config_hash=config.config_hash,
                strategy_versions=frozenset({"executor_readiness_v1"}),
            )
            env = dict(config.env)
            clock = Clock()
            report = await run_executor_startup(
                env=env,
                lease_store=lease_store,
                owner_id=uuid.uuid4(),
                approved=approved,
                clock=clock,
                http_client=http_client,
            )
            await conn.commit()

            signer = FileKeypairSigner.from_env(env) if report.signer_public_key else None
            sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
            outcome = await run_single_intent_if_configured(
                env=env,
                sessionmaker=sessionmaker,
                lease=report.lease,
                approved=approved,
                arm=report.arm,
                clock=clock,
                http_client=http_client,
                signer=signer,
                helius_api_key=env.get(HELIUS_API_KEY_ENV_VAR),
            )
            return report, outcome
    finally:
        await engine.dispose()


def main() -> None:
    """Real process entry point -- ``python -m argus.executor.main``. Runs
    the startup sequence once, then -- ONLY if
    ``ARGUS_EXECUTOR_SINGLE_INTENT_ID`` is configured -- runs the single
    named intent through the real pipeline exactly once, then exits; see
    module docstring for why this deliberately does not loop into a live
    trading cycle."""
    try:
        report, outcome = asyncio.run(_main_async())
    except SignerKeyLoadError as exc:
        _logger.error("executor_startup_failed_signer_key", error=str(exc))
        raise SystemExit(1) from exc
    except SingleIntentConfigurationError as exc:
        _logger.error("executor_single_intent_configuration_failed", error=str(exc))
        raise SystemExit(1) from exc
    _logger.info(
        "executor_startup_complete",
        fencing_token=report.lease.fencing_token,
        signer_loaded=report.signer_public_key is not None,
        submission_adapter_constructed=report.submission_adapter_constructed,
        armed=report.arm.armed,
        live_armed=report.live_armed,
    )
    if outcome is not None:
        _logger.info(
            "executor_single_intent_outcome",
            intent_id=str(outcome.intent.intent_id),
            status=outcome.status,
            detail=outcome.detail,
        )


if __name__ == "__main__":  # pragma: no cover - process entry point
    main()
