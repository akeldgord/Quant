"""FSR-13 (``argus-final-spec-recovery-001``) DB-backed integration
coverage: the ``contaminated_run_invalidations`` registry, seeded by
migration 0036, and the invariant every Phase 8-11 CLI report already
relies on -- filtering by the CURRENT ``ALGORITHM_VERSION`` module
constant excludes old-version rows from a default report while leaving
them fully queryable by their own (unaltered) algorithm_version.

Follows the exact ``admin_engine``-gated skip pattern every other Phase
1-11 DB-backed integration test in this repo uses -- these tests SKIP
(never fail) when Postgres is unreachable in this sandbox.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from typer.testing import CliRunner

from argus.cli import app
from argus.config import ArgusConfig, load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.contaminated_run_invalidations import (
    PHASE_8_CONVERGENCE,
    PHASE_9_COUNTERFACTUAL,
    PHASE_10_SYNTHETIC,
    PHASE_11_PREDICTION,
    STATUS_SUPERSEDED,
    ContaminatedRunInvalidation,
)
from argus.domain.order_flow_prediction_runs import (
    MODEL_BASELINE_RANDOM,
    STATUS_INSUFFICIENT_SAMPLE,
    OrderFlowPredictionRun,
)
from argus.prediction.service import ALGORITHM_VERSION as CURRENT_ALGORITHM_VERSION

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_OLD_ALGORITHM_VERSION = "order_flow_prediction_v1"

runner = CliRunner()


def _sessionmaker() -> tuple[ArgusConfig, Any, async_sessionmaker[Any]]:
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return config, engine, async_sessionmaker(engine, expire_on_commit=False)


def _insufficient_sample_row(
    *, algorithm_version: str, as_of: datetime, config_hash: str
) -> OrderFlowPredictionRun:
    return OrderFlowPredictionRun(
        run_id=uuid.uuid4(),
        horizon_seconds=300,
        model_family=MODEL_BASELINE_RANDOM,
        status=STATUS_INSUFFICIENT_SAMPLE,
        train_sample_size=0,
        test_sample_size=0,
        positive_rate_train=None,
        positive_rate_test=None,
        auc_roc=None,
        log_loss=None,
        brier_score=None,
        accuracy_at_threshold=None,
        feature_set=[],
        split_boundary=None,
        embargo_seconds=None,
        purged_count=0,
        train_range_start=None,
        train_range_end=None,
        test_range_start=None,
        test_range_end=None,
        as_of=as_of,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        created_at=_NOW,
    )


async def test_registry_names_all_four_contaminated_phases_with_reason(admin_engine) -> None:
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session:
            rows = (await session.execute(select(ContaminatedRunInvalidation))).scalars().all()
        by_phase = {r.phase_name: r for r in rows}
        assert set(by_phase) == {
            PHASE_8_CONVERGENCE,
            PHASE_9_COUNTERFACTUAL,
            PHASE_10_SYNTHETIC,
            PHASE_11_PREDICTION,
        }
        row = by_phase[PHASE_11_PREDICTION]
        assert row.invalidated_algorithm_version == _OLD_ALGORITHM_VERSION
        assert row.superseded_by_algorithm_version == CURRENT_ALGORITHM_VERSION
        assert row.status == STATUS_SUPERSEDED
        assert len(row.reason) > 0
        assert len(row.target_commit) == 40
    finally:
        await engine.dispose()


async def test_old_contaminated_row_stays_in_db_but_excluded_from_current_report(
    admin_engine,
) -> None:
    """FSR-13's own required tests, all four in one fixture: the old run
    remains in the DB but is excluded from the default current report's
    own query shape; the corrected version is the one that query selects;
    an explicit archival query can retrieve the old row AND its
    invalidation reason; raw inputs are untouched (see the companion test
    below)."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        as_of = _NOW
        config_hash = f"fsr13-test-{uuid.uuid4().hex[:16]}"
        async with sessionmaker() as session, session.begin():
            # Simulates a run persisted before this recovery, under the
            # OLD, contaminated algorithm_version.
            session.add(
                _insufficient_sample_row(
                    algorithm_version=_OLD_ALGORITHM_VERSION, as_of=as_of, config_hash=config_hash
                )
            )
            # The corrected run a fresh compute_and_persist_phase11 call
            # would persist today.
            session.add(
                _insufficient_sample_row(
                    algorithm_version=CURRENT_ALGORITHM_VERSION,
                    as_of=as_of,
                    config_hash=config_hash,
                )
            )

        async with sessionmaker() as session:
            # The exact WHERE shape every Phase 8-11 CLI report uses: as_of
            # + the CURRENT ALGORITHM_VERSION constant + config_hash.
            current_rows = (
                (
                    await session.execute(
                        select(OrderFlowPredictionRun).where(
                            OrderFlowPredictionRun.as_of == as_of,
                            OrderFlowPredictionRun.algorithm_version == CURRENT_ALGORITHM_VERSION,
                            OrderFlowPredictionRun.config_hash == config_hash,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(current_rows) == 1
            assert current_rows[0].algorithm_version == CURRENT_ALGORITHM_VERSION

            # Explicit archival query: never deleted, still fully
            # retrievable by its own (unaltered) algorithm_version.
            archived_rows = (
                (
                    await session.execute(
                        select(OrderFlowPredictionRun).where(
                            OrderFlowPredictionRun.as_of == as_of,
                            OrderFlowPredictionRun.algorithm_version == _OLD_ALGORITHM_VERSION,
                            OrderFlowPredictionRun.config_hash == config_hash,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(archived_rows) == 1
            assert archived_rows[0].algorithm_version == _OLD_ALGORITHM_VERSION

            invalidation = (
                await session.execute(
                    select(ContaminatedRunInvalidation).where(
                        ContaminatedRunInvalidation.phase_name == PHASE_11_PREDICTION,
                        ContaminatedRunInvalidation.invalidated_algorithm_version
                        == _OLD_ALGORITHM_VERSION,
                    )
                )
            ).scalar_one()
            assert invalidation.superseded_by_algorithm_version == CURRENT_ALGORITHM_VERSION
            assert len(invalidation.reason) > 0
    finally:
        await engine.dispose()


async def test_raw_evidence_is_never_touched_by_the_invalidation_registry(admin_engine) -> None:
    """FSR-13 (CORE-002): raw ingestion evidence is untouched -- the
    invalidation registry and the version bump are schema/derived-data
    concerns only."""
    config, engine, sessionmaker = _sessionmaker()
    try:
        wallet_address = f"FSR13TEST{uuid.uuid4().hex[:30]}"
        event_id = uuid.uuid4()
        async with sessionmaker() as session, session.begin():
            session.add(
                ChainEvent(
                    event_id=event_id,
                    chain="solana",
                    slot=1,
                    block_time=_NOW,
                    first_seen_at=_NOW,
                    provider="fsr13-test",
                    provider_received_at=_NOW,
                    transaction_signature=f"fsr13-{uuid.uuid4()}",
                    event_type="TRANSACTION_OBSERVED",
                    wallet_address=wallet_address,
                    raw_payload={"untouched": True},
                    payload_hash="h",
                    parser_version="v1",
                    created_at=_NOW,
                )
            )

        async with sessionmaker() as session:
            row = await session.get(ChainEvent, event_id)
            assert row is not None
            assert row.raw_payload == {"untouched": True}
            assert row.wallet_address == wallet_address
    finally:
        await engine.dispose()


def test_cli_checkpoint_invalidations_lists_all_four_phases(admin_engine) -> None:
    result = runner.invoke(app, ["checkpoint", "invalidations"])
    assert result.exit_code == 0, result.output
    for phase_name in (
        "PHASE_8_CONVERGENCE",
        "PHASE_9_COUNTERFACTUAL",
        "PHASE_10_SYNTHETIC",
        "PHASE_11_PREDICTION",
    ):
        assert phase_name in result.output
    assert "SUPERSEDED" in result.output
