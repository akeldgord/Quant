"""argus.synthetic.persistence -- MASTER_SPEC.md Phase 10: append-only,
idempotent persistence for simulated trades and strategy summaries.
Follows the SAME ``INSERT ... ON CONFLICT DO NOTHING`` +
re-select-within-transaction pattern F5-05 established for Phase 5
snapshots and reused by Phases 7/8/9.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from argus.domain.synthetic_strategy_summaries import SyntheticStrategySummary
from argus.domain.synthetic_strategy_trades import SyntheticStrategyTrade
from argus.synthetic.matching import MatchedTrade


def _row_values(row: object, table) -> dict:
    return {column.name: getattr(row, column.name) for column in table.columns}


async def get_or_create_synthetic_strategy_trade(
    session: AsyncSession,
    *,
    strategy_code: str,
    matched: MatchedTrade,
    entry_price_usd: Decimal | None,
    exit_price_usd: Decimal | None,
    cost_bps_applied: Decimal,
    gross_return: Decimal | None,
    net_return: Decimal | None,
    executable_horizon_label: str | None,
    executable_status: str | None,
    executable_failure_class: str | None,
    mark_gross_return: Decimal | None,
    mark_net_return: Decimal | None,
    outcome: str,
    as_of: datetime,
    algorithm_version: str,
    config_hash: str,
    now: datetime,
) -> tuple[SyntheticStrategyTrade, bool]:
    identity = (
        SyntheticStrategyTrade.strategy_code == strategy_code,
        SyntheticStrategyTrade.token_id == matched.entry.token_id,
        SyntheticStrategyTrade.entry_at == matched.entry.at,
        SyntheticStrategyTrade.as_of == as_of,
        SyntheticStrategyTrade.algorithm_version == algorithm_version,
        SyntheticStrategyTrade.config_hash == config_hash,
    )
    existing = (
        await session.execute(select(SyntheticStrategyTrade).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = SyntheticStrategyTrade(
        trade_id=uuid.uuid4(),
        strategy_code=strategy_code,
        token_id=matched.entry.token_id,
        entry_wallet_id=matched.entry.wallet_id,
        entry_trigger_reference=matched.entry.reference,
        entry_at=matched.entry.at,
        entry_price_usd=entry_price_usd,
        exit_wallet_id=matched.exit.wallet_id if matched.exit is not None else None,
        exit_trigger_reference=matched.exit.reference if matched.exit is not None else None,
        exit_at=matched.exit.at if matched.exit is not None else None,
        exit_price_usd=exit_price_usd,
        cost_bps_applied=cost_bps_applied,
        gross_return=gross_return,
        net_return=net_return,
        executable_horizon_label=executable_horizon_label,
        executable_status=executable_status,
        executable_failure_class=executable_failure_class,
        mark_gross_return=mark_gross_return,
        mark_net_return=mark_net_return,
        outcome=outcome,
        as_of=as_of,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        created_at=now,
    )
    stmt = (
        pg_insert(SyntheticStrategyTrade)
        .values(**_row_values(row, SyntheticStrategyTrade.__table__))
        .on_conflict_do_nothing(constraint="uq_synthetic_strategy_trades_identity")
        .returning(SyntheticStrategyTrade.trade_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True
    return (
        await session.execute(select(SyntheticStrategyTrade).where(*identity))
    ).scalar_one(), False


async def get_or_create_synthetic_strategy_summary(
    session: AsyncSession,
    *,
    strategy_code: str,
    trade_count: int,
    resolved_count: int,
    failure_count: int,
    failure_rate: Decimal | None,
    win_rate: Decimal | None,
    profit_factor: Decimal | None,
    max_drawdown: Decimal | None,
    capital_utilization: Decimal | None,
    mean_net_return: Decimal | None,
    median_net_return: Decimal | None,
    insufficient_executable_sample: bool,
    as_of: datetime,
    algorithm_version: str,
    config_hash: str,
    now: datetime,
) -> tuple[SyntheticStrategySummary, bool]:
    identity = (
        SyntheticStrategySummary.strategy_code == strategy_code,
        SyntheticStrategySummary.as_of == as_of,
        SyntheticStrategySummary.algorithm_version == algorithm_version,
        SyntheticStrategySummary.config_hash == config_hash,
    )
    existing = (
        await session.execute(select(SyntheticStrategySummary).where(*identity))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = SyntheticStrategySummary(
        summary_id=uuid.uuid4(),
        strategy_code=strategy_code,
        as_of=as_of,
        trade_count=trade_count,
        resolved_count=resolved_count,
        failure_count=failure_count,
        failure_rate=failure_rate,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        capital_utilization=capital_utilization,
        mean_net_return=mean_net_return,
        median_net_return=median_net_return,
        insufficient_executable_sample=insufficient_executable_sample,
        algorithm_version=algorithm_version,
        config_hash=config_hash,
        created_at=now,
    )
    stmt = (
        pg_insert(SyntheticStrategySummary)
        .values(**_row_values(row, SyntheticStrategySummary.__table__))
        .on_conflict_do_nothing(constraint="uq_synthetic_strategy_summaries_identity")
        .returning(SyntheticStrategySummary.summary_id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return row, True
    return (
        await session.execute(select(SyntheticStrategySummary).where(*identity))
    ).scalar_one(), False
