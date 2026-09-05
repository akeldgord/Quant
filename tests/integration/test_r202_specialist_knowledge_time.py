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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from argus.config import load_config
from argus.counterfactual.loaders import load_latest_exit_skill
from argus.counterfactual.service import (
    ALGORITHM_VERSION,
    Phase9RunConfig,
    _compute_and_persist_specialist_scores,
)
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.directional_edges import DirectionalEdge
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_specialist_scores import WalletSpecialistScore
from argus.domain.wallets import Wallet
from argus.graph.lead_follow import WalletTokenEntry
from argus.graph.service import ALGORITHM_VERSION as GRAPH_ALGORITHM_VERSION
from argus.graph.service import GraphRunConfig
from argus.prediction.loaders import load_discovery_effect_size_by_wallet, wallet_fingerprint_at
from argus.synthetic.loaders import load_specialist_scores_as_of

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("isolated_database")]

_CUTOFF = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_BEFORE_CUTOFF = _CUTOFF - timedelta(hours=1)
_AFTER_CUTOFF = _CUTOFF + timedelta(hours=1)  # only "recorded" after cutoff -- must be excluded

_TEST_GIT_COMMIT = "TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB"


def _make_score_snapshot(
    *, wallet_id: uuid.UUID, as_of: datetime, created_at: datetime, component_values: dict
) -> WalletScoreSnapshot:
    return WalletScoreSnapshot(
        score_id=uuid.uuid4(),
        wallet_id=wallet_id,
        as_of=as_of,
        score_version="r202-clarification-test-v1",
        descriptive_score=None,
        qualification_score=None,
        component_values=component_values,
        penalties={},
        confidence="HIGH",
        excluded_discovery_token_ids=[],
        eligible_for_qualification=False,
        sample_gate_reason="r202-clarification-test",
        build_hash="test-build",
        config_hash="test-config",
        master_spec_hash="test-spec",
        git_commit=_TEST_GIT_COMMIT,
        created_at=created_at,
    )


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


async def test_schema_rejects_source_knowledge_after_as_of(admin_engine: AsyncEngine) -> None:
    """Clarification-001 section 3's own direct loader requirement, enforced
    at the strongest possible layer: a row whose ``source_knowledge_max_at``
    is AFTER its own ``as_of`` -- i.e. sources only knowable strictly after
    the very decision time the row claims to represent -- can never even be
    WRITTEN to ``wallet_specialist_scores``, let alone read back by
    ``load_specialist_scores_as_of``/``load_discovery_effect_size_by_
    wallet``. This is a stronger guarantee than a read-side filter alone:
    the ``ck_wallet_specialist_scores_source_knowledge_not_after_as_of``
    CHECK constraint (migration 0041) makes the contaminated shape the
    audit named structurally impossible to persist in the first place."""
    engine, sessionmaker = _ingest_sessionmaker()
    try:
        wallet_id = uuid.uuid4()
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=wallet_id,
                    wallet_address=f"R202BADPROV{uuid.uuid4().hex[:33]}",
                    first_discovered_at=_BEFORE_CUTOFF,
                    current_tier=None,
                    created_at=_BEFORE_CUTOFF,
                )
            )
            await session.flush()
            session.add(
                WalletSpecialistScore(
                    score_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    as_of=_CUTOFF,
                    entry_specialist_score=None,
                    entry_specialist_sample_size=0,
                    discovery_specialist_score=Decimal("7.0"),
                    discovery_specialist_sample_size=1,
                    validation_specialist_score=None,
                    validation_specialist_sample_size=0,
                    exit_specialist_score=None,
                    entry_percentile=None,
                    discovery_percentile=None,
                    validation_percentile=None,
                    exit_percentile=None,
                    dominant_specialty=None,
                    # Sources only knowable AFTER the row's own as_of --
                    # must be structurally impossible to persist.
                    source_knowledge_max_at=_AFTER_CUTOFF,
                    algorithm_version="r202-loader-test",
                    config_hash="r202-loader-test-config",
                    created_at=_CUTOFF + timedelta(days=30),
                )
            )
            with pytest.raises(IntegrityError, match="source_knowledge_not_after_as_of"):
                await session.flush()
    finally:
        await engine.dispose()


async def test_loaders_accept_row_reconstructed_later_with_valid_provenance(
    admin_engine: AsyncEngine,
) -> None:
    """The mirror-image control the clarification explicitly requires:
    "historical reconstruction performed later is allowed when its sources
    prove they were known by T" -- never weakened to "the score row must
    have been created before T". A row labeled ``as_of=T``, physically
    written 30 DAYS later, whose ``source_knowledge_max_at`` is genuinely
    at-or-before T, must be accepted by both Phase 10's and Phase 11's own
    loaders exactly like any other in-time row."""
    engine, sessionmaker = _ingest_sessionmaker()
    try:
        wallet_id = uuid.uuid4()
        reconstructed_much_later = _CUTOFF + timedelta(days=30)
        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=wallet_id,
                    wallet_address=f"R202GOODPROV{uuid.uuid4().hex[:32]}",
                    first_discovered_at=_BEFORE_CUTOFF,
                    current_tier=None,
                    created_at=_BEFORE_CUTOFF,
                )
            )
            await session.flush()
            session.add(
                WalletSpecialistScore(
                    score_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    as_of=_CUTOFF,
                    entry_specialist_score=None,
                    entry_specialist_sample_size=0,
                    discovery_specialist_score=Decimal("3.0"),
                    discovery_specialist_sample_size=1,
                    validation_specialist_score=None,
                    validation_specialist_sample_size=0,
                    exit_specialist_score=None,
                    entry_percentile=None,
                    discovery_percentile=None,
                    validation_percentile=None,
                    exit_percentile=None,
                    dominant_specialty=None,
                    # Reconstructed 30 days after T, but its sources
                    # genuinely were all known by T (exactly T, the
                    # boundary case) -- must be accepted regardless of
                    # the late physical write.
                    source_knowledge_max_at=_CUTOFF,
                    algorithm_version="r202-loader-test",
                    config_hash="r202-loader-test-config",
                    created_at=reconstructed_much_later,
                )
            )

        async with sessionmaker() as session:
            phase10_rows = await load_specialist_scores_as_of(
                session,
                decision_time=_CUTOFF,
                algorithm_version="r202-loader-test",
                config_hash="r202-loader-test-config",
            )
            assert wallet_id in {r.wallet_id for r in phase10_rows}

            phase11_map = await load_discovery_effect_size_by_wallet(
                session,
                cutoff=_CUTOFF,
                algorithm_version="r202-loader-test",
                config_hash="r202-loader-test-config",
            )
            assert phase11_map[wallet_id] == Decimal("3.0")
    finally:
        await engine.dispose()


async def test_full_mutation_end_to_end_knowledge_time_provenance(
    admin_engine: AsyncEngine,
) -> None:
    """Clarification-001 section 3.4.3's full end-to-end mutation test,
    run against a real evidence source that supports genuine point-in-time
    (<=, not merely ==) re-selection: ``wallet_score_snapshots``, reused
    unchanged by BOTH Phase 9's exit-specialist dimension
    (``load_latest_exit_skill``) and Phase 11's own wallet fingerprint
    feature (``wallet_fingerprint_at``) -- so a single appended source row
    exercises the exact same provenance guarantee across both consumers.

    1. Seed E1 (a wallet-score snapshot) known by T.
    2. Reconstruct Phase 9 for T.
    3. Capture the Phase 10 decision input (``load_specialist_scores_as_of``)
       and Phase 11 feature (``wallet_fingerprint_at``) at T.
    4. Append E2: effective (``as_of``) before T, but only knowable
       (``created_at``) strictly after T.
    5. Rebuild Phase 9 for T again, under a fresh invocation (a distinct
       ``computed_at``, proving no reliance on cached process state).
    6. Prove the T decision input/feature are semantically IDENTICAL to
       step 3 -- E2 must never leak into T's own reconstruction.
    7. Move the cutoff forward past E2's own knowledge time and prove it
       can THEN legitimately affect the result.
    """
    engine, sessionmaker = _ingest_sessionmaker()
    try:
        wallet_id = uuid.uuid4()
        token_id = uuid.uuid4()
        t = _CUTOFF
        e1_as_of = t - timedelta(hours=2)
        e2_as_of = t - timedelta(hours=1)  # effective BEFORE T
        e2_created_at = t + timedelta(hours=2)  # only knowable AFTER T
        t2 = t + timedelta(hours=3)  # past E2's own knowledge time

        async with sessionmaker() as session, session.begin():
            session.add(
                Wallet(
                    wallet_id=wallet_id,
                    wallet_address=f"R202MUTATION{uuid.uuid4().hex[:32]}",
                    first_discovered_at=e1_as_of,
                    current_tier=None,
                    created_at=e1_as_of,
                )
            )
            await session.flush()
            # Step 1: E1, known by T.
            session.add(
                _make_score_snapshot(
                    wallet_id=wallet_id,
                    as_of=e1_as_of,
                    created_at=e1_as_of,
                    component_values={
                        "exit_capture": "0.30",
                        "selection_alpha": "0.10",
                        "consistency": "0.20",
                        "forward_information": "0.05",
                    },
                )
            )

        entries = [
            WalletTokenEntry(
                wallet_id=wallet_id, token_id=token_id, entered_at=e1_as_of, source_id=uuid.uuid4()
            )
        ]

        # Step 2: reconstruct Phase 9 for T.
        async with sessionmaker() as session, session.begin():
            await _compute_and_persist_specialist_scores(
                session,
                entries=entries,
                entry_alpha_by_wallet_horizon={},
                cutoff=t,
                graph_config=_GRAPH_CONFIG,
                config=_PHASE9_CONFIG,
                computed_at=t,
            )

        # Step 3: capture the Phase 10 decision input and Phase 11 feature
        # at T, before E2 exists at all.
        async with sessionmaker() as session:
            baseline_rows = await load_specialist_scores_as_of(
                session,
                decision_time=t,
                algorithm_version=ALGORITHM_VERSION,
                config_hash=_PHASE9_CONFIG.config_hash(),
            )
            baseline_row = next(r for r in baseline_rows if r.wallet_id == wallet_id)
            assert baseline_row.exit_specialist_score == Decimal("0.30")
            assert baseline_row.source_knowledge_max_at == e1_as_of

            baseline_exit_skill = await load_latest_exit_skill(
                session, wallet_id=wallet_id, cutoff=t
            )
            assert baseline_exit_skill == (Decimal("0.30"), e1_as_of)

            baseline_snapshots = (
                (
                    await session.execute(
                        select(WalletScoreSnapshot).where(
                            WalletScoreSnapshot.wallet_id == wallet_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            baseline_fingerprint = wallet_fingerprint_at(list(baseline_snapshots), at=t)
            assert baseline_fingerprint == (Decimal("0.10"), Decimal("0.20"), Decimal("0.05"))

        # Step 4: append E2 -- effective before T, only knowable after T.
        async with sessionmaker() as session, session.begin():
            session.add(
                _make_score_snapshot(
                    wallet_id=wallet_id,
                    as_of=e2_as_of,
                    created_at=e2_created_at,
                    component_values={
                        "exit_capture": "0.99",
                        "selection_alpha": "0.99",
                        "consistency": "0.99",
                        "forward_information": "0.99",
                    },
                )
            )

        # Step 5: rebuild Phase 9 for T again, fresh invocation (distinct
        # computed_at -- proves no reliance on any cached prior state).
        async with sessionmaker() as session, session.begin():
            await _compute_and_persist_specialist_scores(
                session,
                entries=entries,
                entry_alpha_by_wallet_horizon={},
                cutoff=t,
                graph_config=_GRAPH_CONFIG,
                config=_PHASE9_CONFIG,
                computed_at=t2,
            )

        # Step 6: T's own decision input/feature must remain semantically
        # identical -- E2 must never leak into T's reconstruction despite
        # now existing in the database.
        async with sessionmaker() as session:
            rebuilt_rows = await load_specialist_scores_as_of(
                session,
                decision_time=t,
                algorithm_version=ALGORITHM_VERSION,
                config_hash=_PHASE9_CONFIG.config_hash(),
            )
            rebuilt_row = next(r for r in rebuilt_rows if r.wallet_id == wallet_id)
            assert rebuilt_row.exit_specialist_score == Decimal("0.30")
            assert rebuilt_row.source_knowledge_max_at == e1_as_of

            rebuilt_exit_skill = await load_latest_exit_skill(
                session, wallet_id=wallet_id, cutoff=t
            )
            assert rebuilt_exit_skill == (Decimal("0.30"), e1_as_of)

            all_snapshots = (
                (
                    await session.execute(
                        select(WalletScoreSnapshot).where(
                            WalletScoreSnapshot.wallet_id == wallet_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            rebuilt_fingerprint = wallet_fingerprint_at(list(all_snapshots), at=t)
            assert rebuilt_fingerprint == (Decimal("0.10"), Decimal("0.20"), Decimal("0.05"))

        # Step 7: move the cutoff forward past E2's own knowledge time --
        # it can NOW legitimately affect the result.
        async with sessionmaker() as session, session.begin():
            await _compute_and_persist_specialist_scores(
                session,
                entries=[
                    WalletTokenEntry(
                        wallet_id=wallet_id,
                        token_id=token_id,
                        entered_at=e1_as_of,
                        source_id=uuid.uuid4(),
                    )
                ],
                entry_alpha_by_wallet_horizon={},
                cutoff=t2,
                graph_config=_GRAPH_CONFIG,
                config=_PHASE9_CONFIG,
                computed_at=t2,
            )

        async with sessionmaker() as session:
            t2_rows = await load_specialist_scores_as_of(
                session,
                decision_time=t2,
                algorithm_version=ALGORITHM_VERSION,
                config_hash=_PHASE9_CONFIG.config_hash(),
            )
            t2_row = next(r for r in t2_rows if r.wallet_id == wallet_id)
            assert t2_row.exit_specialist_score == Decimal("0.99")
            assert t2_row.source_knowledge_max_at == e2_created_at

            t2_exit_skill = await load_latest_exit_skill(session, wallet_id=wallet_id, cutoff=t2)
            assert t2_exit_skill == (Decimal("0.99"), e2_created_at)

            all_snapshots = (
                (
                    await session.execute(
                        select(WalletScoreSnapshot).where(
                            WalletScoreSnapshot.wallet_id == wallet_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            t2_fingerprint = wallet_fingerprint_at(list(all_snapshots), at=t2)
            assert t2_fingerprint == (Decimal("0.99"), Decimal("0.99"), Decimal("0.99"))
    finally:
        await engine.dispose()
