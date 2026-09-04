"""argus.executor.main — MASTER_SPEC.md section 70 (LIVE EXECUTION
SECURITY MODEL) / section 75 (EXECUTOR SINGLETON), FSR-01
(``argus-final-spec-recovery-001``).

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
distinct least-privilege deployment identity. It deliberately does NOT
run a live trading/copy-signal loop: ``LIVE_ARMED`` stays unconditionally
``False`` here exactly as it does in ``argus.executor.report`` regardless
of whether a real signer loaded or an arm file validated, because the
mainnet canary this build's own governance requires (Phase 6.5,
explicitly human-only, never self-executed -- see
``orchestration/ORCHESTRATOR_INSTRUCTIONS.md``) has not run. A future,
separately-approved change wires this boundary into an actual execution
loop; this module's job is only to prove the boundary itself is real and
isolated.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import httpx

from argus.clock import Clock
from argus.config import ArgusConfig, load_config, resolve_production_git_commit
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.executor.arm import ApprovedIdentity, ArmValidationResult, validate_arm_file
from argus.executor.live_signing import (
    ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR,
    FileKeypairSigner,
    SignerKeyLoadError,
)
from argus.executor.live_submission import SolanaSubmissionClient
from argus.executor.service import BUILD_HASH, build_phase6_disposition
from argus.executor.singleton import LeaseHandle, LeaseStore, PostgresLeaseStore, acquire_or_refuse
from argus.logging import get_logger
from argus.providers.helius.client import HELIUS_API_KEY_ENV_VAR

_logger = get_logger(component="argus.executor.main")

ARGUS_LIVE_ARM_FILE_PATH_ENV_VAR = "ARGUS_LIVE_ARM_FILE_PATH"
_DEFAULT_LEASE_TTL = timedelta(seconds=30)


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


async def _main_async() -> ExecutorStartupReport:
    from sqlalchemy.ext.asyncio import create_async_engine

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
            report = await run_executor_startup(
                env=dict(config.env),
                lease_store=lease_store,
                owner_id=uuid.uuid4(),
                approved=approved,
                clock=Clock(),
                http_client=http_client,
            )
            await conn.commit()
            return report
    finally:
        await engine.dispose()


def main() -> None:
    """Real process entry point -- ``python -m argus.executor.main``. Runs
    the startup sequence once and exits; see module docstring for why
    this deliberately does not loop into a live trading cycle."""
    try:
        report = asyncio.run(_main_async())
    except SignerKeyLoadError as exc:
        _logger.error("executor_startup_failed_signer_key", error=str(exc))
        raise SystemExit(1) from exc
    _logger.info(
        "executor_startup_complete",
        fencing_token=report.lease.fencing_token,
        signer_loaded=report.signer_public_key is not None,
        submission_adapter_constructed=report.submission_adapter_constructed,
        armed=report.arm.armed,
        live_armed=report.live_armed,
    )


if __name__ == "__main__":  # pragma: no cover - process entry point
    main()
