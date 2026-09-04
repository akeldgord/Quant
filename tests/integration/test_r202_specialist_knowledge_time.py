"""R2-02 (``argus-final-spec-recovery-002``): Phase 9 discovery/validation
specialist scoring must respect the ``known_by_cutoff`` (M1) invariant --
not only ``as_of == cutoff`` (the row's own labeled effective time) but
also ``created_at <= cutoff`` (the row must actually have been RECORDED,
i.e. knowable, by that cutoff). Before this fix,
``_compute_and_persist_specialist_scores`` filtered contributing
``DirectionalEdge``/``ExpectedConfirmationEvent`` rows by ``as_of``
alone, so a row computed/persisted AFTER cutoff (using evidence only
knowable later) but mislabeled with an earlier ``as_of`` could still
silently contribute to a historical specialist score.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from argus.config import load_config
from argus.counterfactual.service import (
    ALGORITHM_VERSION,
    Phase9RunConfig,
    _compute_and_persist_specialist_scores,
)
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.directional_edges import DirectionalEdge
from argus.domain.wallet_specialist_scores import WalletSpecialistScore
from argus.domain.wallets import Wallet
from argus.graph.lead_follow import WalletTokenEntry
from argus.graph.service import ALGORITHM_VERSION as GRAPH_ALGORITHM_VERSION
from argus.graph.service import GraphRunConfig

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("isolated_database")]

_CUTOFF = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_BEFORE_CUTOFF = _CUTOFF - timedelta(hours=1)
_AFTER_CUTOFF = _CUTOFF + timedelta(hours=1)  # only "recorded" after cutoff -- must be excluded

_GRAPH_CONFIG = GraphRunConfig(
    max_lag=timedelta(hours=1), min_observations=1, q_value_threshold=Decimal("0.10")
)
_PHASE9_CONFIG = Phase9RunConfig(
    horizons=(timedelta(minutes=5),),
    max_price_staleness=timedelta(minutes=30),
    max_control_tokens=10,
    entry_specialist_horizon=timedelta(minutes=5),
    discovery_min_observations=1,
    discovery_q_value_threshold=Decimal("0.10"),
    follower_influx_window=timedelta(minutes=30),
    exit_after_influx_window=timedelta(hours=1),
    predation_influx_normalization_cap=Decimal("10"),
    exit_convergence_window=timedelta(hours=1),
    exit_convergence_unknown_independence_weight=Decimal("0.5"),
    min_exit_specialist_score=Decimal("0"),
)


def _ingest_sessionmaker() -> tuple[AsyncEngine, async_sessionmaker[Any]]:
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _make_edge(
    *, leader_wallet_id: uuid.UUID, follower_wallet_id: uuid.UUID, created_at: datetime
) -> DirectionalEdge:
    return DirectionalEdge(
        edge_id=uuid.uuid4(),
        leader_wallet_id=leader_wallet_id,
        follower_wallet_id=follower_wallet_id,
        as_of=_CUTOFF,
        algorithm_version=GRAPH_ALGORITHM_VERSION,
        config_hash=_GRAPH_CONFIG.config_hash(),
        observation_count=5,
        tokens_leader_entered=5,
        follower_base_rate=Decimal("0.1"),
        median_lag_seconds=Decimal("30"),
        expected_follows=Decimal("0.5"),
        lift=Decimal("2.0"),
        effect_size=Decimal("0.42"),
        p_value=Decimal("0.01"),
        q_value=Decimal("0.02"),
        created_at=created_at,
    )


async def test_specialist_edge_created_after_cutoff_is_excluded(admin_engine: AsyncEngine) -> None:
    """The exact leak the R2-02 audit named: a DirectionalEdge labeled
    ``as_of=cutoff`` but only RECORDED after cutoff must never contribute
    to a discovery-specialist score computed as-of that same cutoff."""
    engine, sessionmaker = _ingest_sessionmaker()
    try:
        leader_id = uuid.uuid4()
        follower_id = uuid.uuid4()
        async with sessionmaker() as session, session.begin():
            session.add_all(
                [
                    Wallet(
                        wallet_id=leader_id,
                        wallet_address=f"R202LEADER{uuid.uuid4().hex[:34]}",
                        first_discovered_at=_BEFORE_CUTOFF,
                        current_tier=None,
                        created_at=_BEFORE_CUTOFF,
                    ),
                    Wallet(
                        wallet_id=follower_id,
                        wallet_address=f"R202FOLLOWER{uuid.uuid4().hex[:32]}",
                        first_discovered_at=_BEFORE_CUTOFF,
                        current_tier=None,
                        created_at=_BEFORE_CUTOFF,
                    ),
                ]
            )
            await session.flush()
            # ONE edge, recorded (created_at) AFTER the cutoff it claims to
            # describe -- the exact contaminated shape the audit named.
            session.add(
                _make_edge(
                    leader_wallet_id=leader_id,
                    follower_wallet_id=follower_id,
                    created_at=_AFTER_CUTOFF,
                )
            )

        entries = [
            WalletTokenEntry(
                wallet_id=leader_id,
                token_id=uuid.uuid4(),
                entered_at=_BEFORE_CUTOFF,
                source_id=uuid.uuid4(),
            )
        ]
        async with sessionmaker() as session, session.begin():
            await _compute_and_persist_specialist_scores(
                session,
                entries=entries,
                entry_alpha_by_wallet_horizon={},
                cutoff=_CUTOFF,
                graph_config=_GRAPH_CONFIG,
                config=_PHASE9_CONFIG,
                computed_at=_CUTOFF,
            )

        async with sessionmaker() as session:
            row = (
                await session.execute(
                    select(WalletSpecialistScore).where(
                        WalletSpecialistScore.wallet_id == leader_id,
                        WalletSpecialistScore.as_of == _CUTOFF,
                        WalletSpecialistScore.algorithm_version == ALGORITHM_VERSION,
                    )
                )
            ).scalar_one()
        # The only contributing edge was recorded AFTER cutoff -- it must
        # NEVER count, so discovery ends up with zero sample, not a score
        # silently built from future-knowledge evidence.
        assert row.discovery_specialist_sample_size == 0
        assert row.discovery_specialist_score is None
    finally:
        await engine.dispose()


async def test_specialist_edge_created_before_cutoff_is_included(admin_engine: AsyncEngine) -> None:
    """The mirror-image control: an otherwise-identical edge recorded
    BEFORE cutoff must still contribute normally -- this fix must never
    become a blanket rejection."""
    engine, sessionmaker = _ingest_sessionmaker()
    try:
        leader_id = uuid.uuid4()
        follower_id = uuid.uuid4()
        async with sessionmaker() as session, session.begin():
            session.add_all(
                [
                    Wallet(
                        wallet_id=leader_id,
                        wallet_address=f"R202LEADEROK{uuid.uuid4().hex[:32]}",
                        first_discovered_at=_BEFORE_CUTOFF,
                        current_tier=None,
                        created_at=_BEFORE_CUTOFF,
                    ),
                    Wallet(
                        wallet_id=follower_id,
                        wallet_address=f"R202FOLLOWEROK{uuid.uuid4().hex[:30]}",
                        first_discovered_at=_BEFORE_CUTOFF,
                        current_tier=None,
                        created_at=_BEFORE_CUTOFF,
                    ),
                ]
            )
            await session.flush()
            session.add(
                _make_edge(
                    leader_wallet_id=leader_id,
                    follower_wallet_id=follower_id,
                    created_at=_BEFORE_CUTOFF,
                )
            )

        entries = [
            WalletTokenEntry(
                wallet_id=leader_id,
                token_id=uuid.uuid4(),
                entered_at=_BEFORE_CUTOFF,
                source_id=uuid.uuid4(),
            )
        ]
        async with sessionmaker() as session, session.begin():
            await _compute_and_persist_specialist_scores(
                session,
                entries=entries,
                entry_alpha_by_wallet_horizon={},
                cutoff=_CUTOFF,
                graph_config=_GRAPH_CONFIG,
                config=_PHASE9_CONFIG,
                computed_at=_CUTOFF,
            )

        async with sessionmaker() as session:
            row = (
                await session.execute(
                    select(WalletSpecialistScore).where(
                        WalletSpecialistScore.wallet_id == leader_id,
                        WalletSpecialistScore.as_of == _CUTOFF,
                        WalletSpecialistScore.algorithm_version == ALGORITHM_VERSION,
                    )
                )
            ).scalar_one()
        assert row.discovery_specialist_sample_size == 1
        assert row.discovery_specialist_score == Decimal("0.42")
    finally:
        await engine.dispose()
