"""argus.prediction.persistence -- MASTER_SPEC.md Phase 11: append-only,
idempotent persistence for ``order_flow_prediction_runs``. Follows the
same ``INSERT ... ON CONFLICT DO NOTHING`` + re-select-within-transaction
pattern F5-05 established for Phase 5 snapshots and reused unchanged by
every phase since.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.order_flow_prediction_runs import OrderFlowPredictionRun


def _row_values(row: object, table) -> dict:
    return {column.name: getattr(row, column.name) for column in table.columns}


async def get_or_create_order_flow_prediction_run(
    session: AsyncSession,
    *,
    horizon_seconds: int,
    model_family: str,
    status: str,
    train_sample_size: int,
    test_sample_size: int,
    positive_rate_train: Decimal | None,
    positive_rate_test: Decimal | None,
    auc_roc: Decimal | None,
    log_loss: Decimal | None,
    brier_score: Decimal | None,
    accuracy_at_threshold: Decimal | None,
    feature_set: list[str],
    as_of: datetime,
    algorithm_version: str,
    config_hash: str,
    now: datetime,
) -> tuple[OrderFlowPredictionRun, bool]:
    identity = (
        OrderFlowPredictionRun.horizon_seconds == horizon_seconds,
        OrderFlowPredictionRun.model_family == model_family,
        OrderFlowPredictionRun.as_of == as_of,
        OrderFlowPredictionRun.algorithm_version == algorithm_version,
        OrderFlowPredictionRun.config_hash == config_hash,
    )
    existing = (
        await session.execute(select(OrderFlowPredictionRun).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = OrderFlowPredictionRun(
        run_id=uuid.uuid4(),
        horizon_seconds=horizon_seconds,
        model_family=model_family,
        status=status,
        train_sample_size=train_sample_size,
        test_sample_size=test_sample_size,
        positive_rate_train=positive_rate_train,
        positive_rate_test=positive_rate_test,
        auc_roc=auc_roc,
        log_loss=log_loss,
        brier_score=brier_score,
        accuracy_at_threshold=accuracy_at_threshold,
        feature_set=feature_set,
        as_of=as_of,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        created_at=now,
    )
    stmt = (
        pg_insert(OrderFlowPredictionRun)
        .values(**_row_values(row, OrderFlowPredictionRun.__table__))
        .on_conflict_do_nothing(constraint="uq_order_flow_prediction_runs_identity")
        .returning(OrderFlowPredictionRun.run_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True
    return (
        await session.execute(select(OrderFlowPredictionRun).where(*identity))
    ).scalar_one(), False
