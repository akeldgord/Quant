"""P4-R6 remediation acceptance tests (argus-phase-4-remediation-001)
against real Postgres.

Proves, against the real production functions (never a duplicated
test-only reimplementation):

1. ``_build_discovery``'s tier-transition direction is computed from
   ``from_tier``/``to_tier`` rank comparison, never ``to_tier`` alone --
   reproducing the audit's own worked example (S->A, DISCOVERED->WATCH,
   PROBATION->B => 2 promotions, 1 demotion, not the old bug's "1
   promotion, 2 demotions").
2. ``new_wallets`` counts distinct wallet identities
   (``wallets.first_discovered_at``), never repeated
   ``wallet_discovery_events`` rows for the same wallet.
3. ``data_quality["low_completeness_wallets"]`` reflects real
   ``WalletHistoryQuality`` LOW/UNKNOWN rows, never a placeholder.
4. ``shadow["mfe_mae"]``/``research["sample_counts"]``/
   ``data_quality["provider_gaps"]``/``shadow["matured_*_in_window"]``
   reflect real persisted evidence, never
   ``NOT_IMPLEMENTED``/``INSUFFICIENT_SAMPLE`` when real sample data
   exists.
5. An ordinary, real ``run_due_entry_probes`` call -- never a manual
   ``.notify()`` in the test -- delivers exactly one ``SHADOW_EVENT``
   Telegram notification referencing the actual just-committed
   ``ShadowPosition``'s own facts.
6. An ordinary, real ``build_daily_report`` call delivers exactly one
   ``DAILY_SUMMARY`` notification referencing the report's own real
   computed figures.
7. A notifier whose transport always raises never loses/rewrites the
   underlying committed record, in either producer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from argus.clock import Clock
from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.domain.chain_events import ChainEvent
from argus.domain.commitment import COMMITMENT_CONFIRMED, CommitmentObservation
from argus.domain.shadow_intents import ShadowIntent
from argus.domain.shadow_mark_outcomes import (
    OUTCOME_PRICE_UNAVAILABLE,
    OUTCOME_RECORDED,
    ShadowMarkOutcome,
)
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    OUTCOME_NO_ROUTE,
    OUTCOME_PENDING,
    OUTCOME_PROVIDER_CAPACITY_MISS,
    OUTCOME_SUCCESS,
    PROBE_KIND_REVERSE_EXECUTABLE,
    ShadowQuoteProbe,
)
from argus.domain.swaps import Swap
from argus.domain.tokens import Token
from argus.domain.wallet_discovery_events import (
    DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
    DISCOVERY_CHANNEL_PROSPECTIVE_WINNER_ARCHAEOLOGY,
    WalletDiscoveryEvent,
)
from argus.domain.wallet_history_quality import (
    COMPLETENESS_HIGH,
    COMPLETENESS_LOW,
    COMPLETENESS_UNKNOWN,
    WalletHistoryQuality,
)
from argus.domain.wallet_positions import CONFIDENCE_HIGH, STATUS_CLOSED, WalletPosition
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_tier_history import WalletTierTransition
from argus.domain.wallets import Wallet
from argus.reports.daily import build_daily_report
from argus.shadow.monitor import run_prospective_monitoring_pass
from argus.shadow.quote_jobs import run_due_entry_probes
from argus.telegram.notifier import FakeTelegramTransport, TelegramNotifier

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 6, 15, tzinfo=UTC)
_TEST_GIT_COMMIT = "TEST_GIT_COMMIT_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEFAB"
SOL_MINT = "So11111111111111111111111111111111111111112"


def _unique_wallet() -> str:
    return f"P4RD{uuid.uuid4().hex[:36]}"


def _unique_mint() -> str:
    return f"P4RDMint{uuid.uuid4().hex[:24]}"


def _sessionmaker():
    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    return config, engine, async_sessionmaker(engine, expire_on_commit=False)


async def _cleanup_wallet(admin_engine: Any, wallet_address: str) -> None:
    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT wallet_id FROM wallets WHERE wallet_address = :w"),
                {"w": wallet_address},
            )
        ).fetchone()
        if row is not None:
            wid = row[0]
            await conn.execute(
                text(
                    "DELETE FROM shadow_mark_outcomes WHERE shadow_position_id IN "
                    "(SELECT shadow_position_id FROM shadow_positions WHERE wallet_id = :w)"
                ),
                {"w": wid},
            )
            await conn.execute(
                text(
                    "DELETE FROM shadow_quote_probes WHERE shadow_position_id IN "
                    "(SELECT shadow_position_id FROM shadow_positions WHERE wallet_id = :w) "
                    "OR shadow_intent_id IN "
                    "(SELECT shadow_intent_id FROM shadow_intents WHERE wallet_id = :w)"
                ),
                {"w": wid},
            )
            await conn.execute(
                text("DELETE FROM shadow_positions WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(text("DELETE FROM shadow_intents WHERE wallet_id = :w"), {"w": wid})
            await conn.execute(
                text("DELETE FROM prospective_events WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text("DELETE FROM wallet_positions WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text("DELETE FROM wallet_history_quality WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text(
                    "DELETE FROM wallet_discovery_events WHERE wallet_id = :w "
                    "OR trigger_wallet_id = :w"
                ),
                {"w": wid},
            )
            await conn.execute(
                text("DELETE FROM wallet_tier_history WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text("DELETE FROM wallet_score_snapshots WHERE wallet_id = :w"), {"w": wid}
            )
            await conn.execute(
                text("DELETE FROM swaps WHERE wallet_address = :addr"), {"addr": wallet_address}
            )
            await conn.execute(
                text(
                    "DELETE FROM commitment_observations WHERE event_id IN "
                    "(SELECT event_id FROM chain_events WHERE wallet_address = :addr)"
                ),
                {"addr": wallet_address},
            )
            await conn.execute(
                text("DELETE FROM chain_events WHERE wallet_address = :addr"),
                {"addr": wallet_address},
            )
            await conn.execute(text("DELETE FROM wallets WHERE wallet_id = :w"), {"w": wid})
        await conn.commit()


async def _cleanup_wallets(admin_engine: Any, wallet_addresses: list[str]) -> None:
    for address in wallet_addresses:
        await _cleanup_wallet(admin_engine, address)


async def _cleanup_token(admin_engine: Any, mint: str) -> None:
    async with admin_engine.connect() as conn:
        await conn.execute(text("DELETE FROM tokens WHERE mint = :m"), {"m": mint})
        await conn.commit()


async def _seed_wallet_only(session, *, wallet_address: str, at: datetime) -> uuid.UUID:
    wallet_id = uuid.uuid4()
    session.add(
        Wallet(
            wallet_id=wallet_id,
            wallet_address=wallet_address,
            first_discovered_at=at,
            current_tier=None,
            created_at=at,
        )
    )
    await session.flush()
    return wallet_id


async def _seed_transition(
    session, *, wallet_address: str, from_tier: str | None, to_tier: str, at: datetime
) -> uuid.UUID:
    wallet_id = await _seed_wallet_only(session, wallet_address=wallet_address, at=at)
    session.add(
        WalletTierTransition(
            transition_id=uuid.uuid4(),
            wallet_id=wallet_id,
            source_score_id=None,
            from_tier=from_tier,
            to_tier=to_tier,
            reason="test transition",
            transitioned_at=at,
            created_at=at,
        )
    )
    await session.flush()
    return wallet_id


async def _seed_tracked_wallet_with_buy_swap(
    session,
    *,
    wallet_address: str,
    mint: str,
    at: datetime,
    tier: str = "A",
    score: Decimal = Decimal("90.000"),
) -> uuid.UUID:
    """Matches the pattern in tests/integration/test_daily_report.py and
    tests/integration/test_shadow_phase4.py -- a real tracked wallet with
    a genuine SWAP_SIMPLE buy."""
    wallet_id = uuid.uuid4()
    session.add(
        Wallet(
            wallet_id=wallet_id,
            wallet_address=wallet_address,
            first_discovered_at=at,
            current_tier=tier,
            created_at=at,
        )
    )
    await session.flush()
    score_id = uuid.uuid4()
    session.add(
        WalletScoreSnapshot(
            score_id=score_id,
            wallet_id=wallet_id,
            as_of=at,
            score_version="test-v1",
            descriptive_score=score,
            qualification_score=score,
            component_values={},
            penalties={},
            confidence="HIGH",
            excluded_discovery_token_ids=[],
            eligible_for_qualification=True,
            sample_gate_reason="test",
            build_hash="test-build",
            config_hash="test-config",
            master_spec_hash="test-spec",
            git_commit=_TEST_GIT_COMMIT,
            created_at=at,
        )
    )
    session.add(
        WalletTierTransition(
            transition_id=uuid.uuid4(),
            wallet_id=wallet_id,
            source_score_id=score_id,
            from_tier=None,
            to_tier=tier,
            reason="test",
            transitioned_at=at,
            created_at=at,
        )
    )
    event_id = uuid.uuid4()
    session.add(
        ChainEvent(
            event_id=event_id,
            chain="solana",
            slot=1,
            block_time=at,
            first_seen_at=at,
            provider="helius",
            provider_received_at=at,
            transaction_signature=f"p4rd-buy-{uuid.uuid4()}",
            event_type="TRANSACTION_OBSERVED",
            wallet_address=wallet_address,
            raw_payload={},
            payload_hash="h",
            parser_version="v1",
            created_at=at,
        )
    )
    await session.flush()
    session.add(
        CommitmentObservation(
            observation_id=uuid.uuid4(),
            event_id=event_id,
            commitment_level=COMMITMENT_CONFIRMED,
            transaction_succeeded=True,
            observed_at=at,
            provider="helius",
            provider_received_at=at,
            created_at=at,
        )
    )
    session.add(
        Swap(
            swap_id=uuid.uuid4(),
            event_id=event_id,
            wallet_address=wallet_address,
            classification="SWAP_SIMPLE",
            input_mint=SOL_MINT,
            input_amount_raw=100_000_000,
            input_amount_ui=Decimal("0.1"),
            output_mint=mint,
            output_amount_raw=1_000_000,
            output_amount_ui=Decimal("1"),
            network_fee_raw=5000,
            slot=1,
            block_time=at,
            first_seen_at=at,
            confidence=Decimal("1.000"),
            parser_version="v1",
            build_hash="test-build",
            created_at=at,
        )
    )
    await session.flush()
    return wallet_id


class _FailingTransport:
    """A transport whose send_message always raises -- proves the
    notifier's best-effort ``contextlib.suppress(Exception)`` guard
    actually holds in both real producers."""

    async def send_message(self, *, chat_id: str, text: str) -> None:
        raise RuntimeError("simulated Telegram outage")


# ---------------------------------------------------------------------
# 1. Tier-transition direction -- audit's own worked example.
# ---------------------------------------------------------------------


async def test_tier_transition_direction_matches_audit_worked_example(admin_engine) -> None:
    """The audit's own worked example: S->A, DISCOVERED->WATCH,
    PROBATION->B used to produce "1 promotion, 2 demotions" under the old
    to_tier-only logic. The correct answer is 2 promotions, 1 demotion --
    S->A is a demotion (S outranks A), DISCOVERED->WATCH and
    PROBATION->B are both promotions (WATCH/B outrank DISCOVERED/PROBATION)."""
    addresses = [_unique_wallet() for _ in range(3)]
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            await _seed_transition(
                session, wallet_address=addresses[0], from_tier="S", to_tier="A", at=_NOW
            )
            await _seed_transition(
                session,
                wallet_address=addresses[1],
                from_tier="DISCOVERED",
                to_tier="WATCH",
                at=_NOW,
            )
            await _seed_transition(
                session,
                wallet_address=addresses[2],
                from_tier="PROBATION",
                to_tier="B",
                at=_NOW,
            )

        report_now = _NOW + timedelta(minutes=1)
        report = await build_daily_report(
            sessionmaker,
            now=report_now,
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
        )

        assert report.discovery["promotions"] == 2
        assert report.discovery["demotions"] == 1
        assert report.discovery["quarantines"] == 0
    finally:
        await _cleanup_wallets(admin_engine, addresses)
        await engine.dispose()


async def test_tier_transition_direction_covers_demotion_quarantine_and_exit_cases(
    admin_engine,
) -> None:
    """Further direction coverage beyond the audit's own three
    transitions: a genuine within-progression demotion (B->WATCH), a
    QUARANTINE entry counted only as a quarantine (never also a
    demotion), and a DORMANT/RETIRED exit-or-recovery counted as
    NEITHER a promotion nor a demotion (per ``_EXIT_TIERS`` handling)."""
    addresses = [_unique_wallet() for _ in range(4)]
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            # A real within-progression demotion.
            await _seed_transition(
                session, wallet_address=addresses[0], from_tier="B", to_tier="WATCH", at=_NOW
            )
            # A quarantine entry -- counted only as a quarantine, even
            # though A outranks QUARANTINE's tuple position.
            await _seed_transition(
                session,
                wallet_address=addresses[1],
                from_tier="A",
                to_tier="QUARANTINE",
                at=_NOW,
            )
            # An exit to RETIRED -- neither a promotion nor a demotion.
            await _seed_transition(
                session, wallet_address=addresses[2], from_tier="WATCH", to_tier="RETIRED", at=_NOW
            )
            # A recovery FROM a DORMANT hold -- neither a promotion nor a
            # demotion, even though WATCH outranks DISCOVERED's tuple
            # position.
            await _seed_transition(
                session,
                wallet_address=addresses[3],
                from_tier="DORMANT",
                to_tier="WATCH",
                at=_NOW,
            )

        report_now = _NOW + timedelta(minutes=1)
        report = await build_daily_report(
            sessionmaker,
            now=report_now,
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
        )

        assert report.discovery["promotions"] == 0
        assert report.discovery["demotions"] == 1
        assert report.discovery["quarantines"] == 1
    finally:
        await _cleanup_wallets(admin_engine, addresses)
        await engine.dispose()


# ---------------------------------------------------------------------
# 2. new_wallets counts distinct wallet identities, never discovery events.
# ---------------------------------------------------------------------


async def test_new_wallets_counts_distinct_wallets_not_discovery_events(admin_engine) -> None:
    wallet_address = _unique_wallet()
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet_only(session, wallet_address=wallet_address, at=_NOW)
            # Multiple discovery-event rows for the SAME already-known
            # wallet -- distinguished by discovery_channel to satisfy the
            # table's own (wallet_id, discovery_channel, trigger_token_id)
            # uniqueness constraint, both inside the report window.
            session.add(
                WalletDiscoveryEvent(
                    discovery_event_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    discovered_at=_NOW,
                    discovery_channel=DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
                    trigger_token_id=None,
                    trigger_wallet_id=None,
                    trigger_event=None,
                    trigger_reason="test discovery event one",
                    algorithm_version="test-v1",
                    created_at=_NOW,
                )
            )
            session.add(
                WalletDiscoveryEvent(
                    discovery_event_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    discovered_at=_NOW + timedelta(seconds=1),
                    discovery_channel=DISCOVERY_CHANNEL_PROSPECTIVE_WINNER_ARCHAEOLOGY,
                    trigger_token_id=None,
                    trigger_wallet_id=None,
                    trigger_event=None,
                    trigger_reason="test discovery event two",
                    algorithm_version="test-v1",
                    created_at=_NOW + timedelta(seconds=1),
                )
            )

        report_now = _NOW + timedelta(minutes=1)
        report = await build_daily_report(
            sessionmaker,
            now=report_now,
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
        )

        # Exactly one wallet IDENTITY was newly discovered in the window,
        # even though two discovery-event rows exist for it.
        assert report.discovery["new_wallets"] == 1
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 3. low_completeness_wallets counts distinct wallets by their CURRENT
#    (latest) WalletHistoryQuality assessment only -- a wallet reassessed
#    LOW -> LOW -> HIGH must count 0, not every historical LOW row
#    (P4-remediation-002 R6). The oracle below is deliberately a
#    DIFFERENT query shape than production's own DISTINCT ON (a
#    correlated NOT EXISTS "no later row for this wallet" query), so a
#    bug in production's own subquery would not be silently mirrored
#    into the test's expectation.
# ---------------------------------------------------------------------


async def _independent_current_low_completeness_count(
    admin_engine, *, wallet_ids: list[Any] | None = None, cutoff: datetime | None = None
) -> int:
    """Independent oracle: a wallet's CURRENT assessment is the row with
    no later row for that same wallet (a correlated NOT EXISTS), a
    deliberately different query shape from production's own DISTINCT ON
    subquery. ``wallet_ids=None`` computes the unrestricted global count
    (used as a same-semantics baseline).

    P4-REC-05: ``cutoff``, when supplied, bounds BOTH the candidate row
    itself (``whq1.created_at <= cutoff``) and the "no later row" check
    (``whq2.created_at > whq1.created_at AND whq2.created_at <= cutoff``)
    -- a history row created after ``cutoff`` must never count as
    "current," and must never make an earlier, genuinely-current-at-
    cutoff row look superseded. This stays a genuinely independent query
    shape (correlated NOT EXISTS) from production's own DISTINCT ON, per
    the audit's own "never duplicate production's formula in the test"
    finding."""
    if wallet_ids is not None and not wallet_ids:
        return 0
    where_scope = "whq1.wallet_id = ANY(:wallet_ids) AND " if wallet_ids is not None else ""
    cutoff_clause_1 = "AND whq1.created_at <= :cutoff " if cutoff is not None else ""
    cutoff_clause_2 = "AND whq2.created_at <= :cutoff " if cutoff is not None else ""
    params: dict[str, Any] = {}
    if wallet_ids is not None:
        params["wallet_ids"] = wallet_ids
    if cutoff is not None:
        params["cutoff"] = cutoff
    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM wallet_history_quality whq1 "
                    f"WHERE {where_scope}"
                    "whq1.history_completeness IN ('LOW', 'UNKNOWN') "
                    f"{cutoff_clause_1}"
                    "AND NOT EXISTS ("
                    "  SELECT 1 FROM wallet_history_quality whq2 "
                    "  WHERE whq2.wallet_id = whq1.wallet_id "
                    "  AND whq2.created_at > whq1.created_at "
                    f"  {cutoff_clause_2}"
                    ")"
                ),
                params,
            )
        ).scalar_one()
    return row


async def test_low_completeness_wallets_reflects_current_state_not_every_low_row(
    admin_engine,
) -> None:
    addresses = [_unique_wallet() for _ in range(2)]
    config, engine, sessionmaker = _sessionmaker()
    try:
        baseline = await _independent_current_low_completeness_count(admin_engine)

        async with sessionmaker() as session, session.begin():
            # Wallet A: LOW -> LOW -> HIGH. Its CURRENT state is HIGH, so
            # it must contribute 0 to the count -- despite two historical
            # LOW rows, all three preserved.
            wallet_reassessed = await _seed_wallet_only(
                session, wallet_address=addresses[0], at=_NOW
            )
            session.add(
                WalletHistoryQuality(
                    history_id=uuid.uuid4(),
                    wallet_id=wallet_reassessed,
                    history_start=None,
                    history_end=None,
                    history_provider_set="helius",
                    history_completeness=COMPLETENESS_LOW,
                    history_completeness_reason="sparse evidence, first pass",
                    acquisition_manifest=None,
                    excluded_evidence=[],
                    algorithm_version="test-v1",
                    created_at=_NOW,
                )
            )
            session.add(
                WalletHistoryQuality(
                    history_id=uuid.uuid4(),
                    wallet_id=wallet_reassessed,
                    history_start=None,
                    history_end=None,
                    history_provider_set="helius",
                    history_completeness=COMPLETENESS_LOW,
                    history_completeness_reason="sparse evidence, second pass",
                    acquisition_manifest=None,
                    excluded_evidence=[],
                    algorithm_version="test-v1",
                    created_at=_NOW + timedelta(minutes=1),
                )
            )
            session.add(
                WalletHistoryQuality(
                    history_id=uuid.uuid4(),
                    wallet_id=wallet_reassessed,
                    history_start=_NOW - timedelta(days=30),
                    history_end=_NOW,
                    history_provider_set="helius",
                    history_completeness=COMPLETENESS_HIGH,
                    history_completeness_reason="full acquisition walk on third pass",
                    acquisition_manifest=None,
                    excluded_evidence=[],
                    algorithm_version="test-v1",
                    created_at=_NOW + timedelta(minutes=2),
                )
            )
            # Wallet B: a single current UNKNOWN assessment -- counts 1.
            wallet_unknown = await _seed_wallet_only(session, wallet_address=addresses[1], at=_NOW)
            session.add(
                WalletHistoryQuality(
                    history_id=uuid.uuid4(),
                    wallet_id=wallet_unknown,
                    history_start=None,
                    history_end=None,
                    history_provider_set="helius",
                    history_completeness=COMPLETENESS_UNKNOWN,
                    history_completeness_reason="no usable evidence found",
                    acquisition_manifest=None,
                    excluded_evidence=[],
                    algorithm_version="test-v1",
                    created_at=_NOW,
                )
            )

        independent_current_low = await _independent_current_low_completeness_count(
            admin_engine, wallet_ids=[wallet_reassessed, wallet_unknown]
        )
        assert independent_current_low == 1

        report = await build_daily_report(
            sessionmaker,
            now=_NOW + timedelta(minutes=5),
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
        )

        # Repeated reconstruction (3 rows for wallet A) must not multiply
        # the distinct-wallet count: exactly 1 new current-LOW/UNKNOWN
        # wallet (B), never 3 (every historical LOW/UNKNOWN row) or 2.
        assert report.data_quality["low_completeness_wallets"] == baseline + 1
    finally:
        await _cleanup_wallets(admin_engine, addresses)
        await engine.dispose()


# ---------------------------------------------------------------------
# 3b. P4-REC-05: low_completeness_wallets selects the latest wallet-
# history assessment KNOWN AT REPORT END, not a later assessment that
# merely happens to exist by the time the report query runs.
# ---------------------------------------------------------------------


async def test_report_uses_low_history_before_end_ignores_high_history_after_end(
    admin_engine,
) -> None:
    """P4-REC-05 test 1: a wallet has a LOW history row before the
    report's own end, and a LATER HIGH history row created after that
    end -- an earlier-ending report must use the LOW row only (the HIGH
    row was not yet known at that report's own cutoff)."""
    address = _unique_wallet()
    config, engine, sessionmaker = _sessionmaker()
    try:
        baseline_cutoff = _NOW + timedelta(minutes=1)
        baseline = await _independent_current_low_completeness_count(
            admin_engine, cutoff=baseline_cutoff
        )
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet_only(session, wallet_address=address, at=_NOW)
            session.add(
                WalletHistoryQuality(
                    history_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    history_start=None,
                    history_end=None,
                    history_provider_set="helius",
                    history_completeness=COMPLETENESS_LOW,
                    history_completeness_reason="sparse evidence before report end",
                    acquisition_manifest=None,
                    excluded_evidence=[],
                    algorithm_version="test-v1",
                    created_at=_NOW,
                )
            )
            # A later, HIGH assessment created AFTER the earlier report's
            # own end -- not yet known at that cutoff.
            session.add(
                WalletHistoryQuality(
                    history_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    history_start=_NOW - timedelta(days=30),
                    history_end=_NOW,
                    history_provider_set="helius",
                    history_completeness=COMPLETENESS_HIGH,
                    history_completeness_reason="full acquisition walk after report end",
                    acquisition_manifest=None,
                    excluded_evidence=[],
                    algorithm_version="test-v1",
                    created_at=_NOW + timedelta(hours=1),
                )
            )

        independent = await _independent_current_low_completeness_count(
            admin_engine, wallet_ids=[wallet_id], cutoff=baseline_cutoff
        )
        assert independent == 1

        earlier_report = await build_daily_report(
            sessionmaker,
            now=baseline_cutoff,
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
            window=timedelta(days=1),
        )
        assert earlier_report.data_quality["low_completeness_wallets"] == baseline + 1
    finally:
        await _cleanup_wallets(admin_engine, [address])
        await engine.dispose()


async def test_report_after_high_history_exists_uses_high_only(admin_engine) -> None:
    """P4-REC-05 test 2: a LATER report, run after the HIGH assessment
    now exists, must use the HIGH row only -- the same wallet contributes
    0 once its own report's end is past the HIGH row's created_at."""
    address = _unique_wallet()
    config, engine, sessionmaker = _sessionmaker()
    try:
        later_cutoff = _NOW + timedelta(hours=2)
        baseline = await _independent_current_low_completeness_count(
            admin_engine, cutoff=later_cutoff
        )
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet_only(session, wallet_address=address, at=_NOW)
            session.add(
                WalletHistoryQuality(
                    history_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    history_start=None,
                    history_end=None,
                    history_provider_set="helius",
                    history_completeness=COMPLETENESS_LOW,
                    history_completeness_reason="sparse evidence before report end",
                    acquisition_manifest=None,
                    excluded_evidence=[],
                    algorithm_version="test-v1",
                    created_at=_NOW,
                )
            )
            session.add(
                WalletHistoryQuality(
                    history_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    history_start=_NOW - timedelta(days=30),
                    history_end=_NOW,
                    history_provider_set="helius",
                    history_completeness=COMPLETENESS_HIGH,
                    history_completeness_reason="full acquisition walk after report end",
                    acquisition_manifest=None,
                    excluded_evidence=[],
                    algorithm_version="test-v1",
                    created_at=_NOW + timedelta(hours=1),
                )
            )

        independent = await _independent_current_low_completeness_count(
            admin_engine, wallet_ids=[wallet_id], cutoff=later_cutoff
        )
        assert independent == 0

        later_report = await build_daily_report(
            sessionmaker,
            now=later_cutoff,
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
            window=timedelta(days=1),
        )
        # The wallet's HIGH row is now the latest-known-as-of-cutoff row
        # -- contributes 0, never the earlier LOW row.
        assert later_report.data_quality["low_completeness_wallets"] == baseline
    finally:
        await _cleanup_wallets(admin_engine, [address])
        await engine.dispose()


async def test_multiple_pre_end_versions_count_exactly_one_latest_eligible(
    admin_engine,
) -> None:
    """P4-REC-05 test 3: three pre-cutoff versions (LOW -> LOW -> UNKNOWN,
    all created before the report's own end) must contribute exactly ONE
    qualifying wallet -- the latest ELIGIBLE (still <= cutoff) version,
    never one row per historical version."""
    address = _unique_wallet()
    config, engine, sessionmaker = _sessionmaker()
    try:
        cutoff = _NOW + timedelta(minutes=10)
        baseline = await _independent_current_low_completeness_count(admin_engine, cutoff=cutoff)
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet_only(session, wallet_address=address, at=_NOW)
            for offset, reason in (
                (0, "first pass"),
                (1, "second pass"),
                (2, "third pass -- still UNKNOWN"),
            ):
                session.add(
                    WalletHistoryQuality(
                        history_id=uuid.uuid4(),
                        wallet_id=wallet_id,
                        history_start=None,
                        history_end=None,
                        history_provider_set="helius",
                        history_completeness=(
                            COMPLETENESS_LOW if offset < 2 else COMPLETENESS_UNKNOWN
                        ),
                        history_completeness_reason=reason,
                        acquisition_manifest=None,
                        excluded_evidence=[],
                        algorithm_version="test-v1",
                        created_at=_NOW + timedelta(minutes=offset),
                    )
                )

        independent = await _independent_current_low_completeness_count(
            admin_engine, wallet_ids=[wallet_id], cutoff=cutoff
        )
        assert independent == 1

        report = await build_daily_report(
            sessionmaker,
            now=cutoff,
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
            window=timedelta(days=1),
        )
        assert report.data_quality["low_completeness_wallets"] == baseline + 1
    finally:
        await _cleanup_wallets(admin_engine, [address])
        await engine.dispose()


async def test_history_only_after_report_end_wallet_not_counted(admin_engine) -> None:
    """P4-REC-05 test 4: a wallet whose ONLY history row is created AFTER
    the report's own end must not be counted as having any history AT
    THAT end -- neither as LOW/UNKNOWN (falsely flagged) nor otherwise;
    it simply contributes 0, identical to a wallet with no history at
    all as of that cutoff."""
    address = _unique_wallet()
    config, engine, sessionmaker = _sessionmaker()
    try:
        earlier_cutoff = _NOW
        baseline = await _independent_current_low_completeness_count(
            admin_engine, cutoff=earlier_cutoff
        )
        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet_only(session, wallet_address=address, at=_NOW)
            session.add(
                WalletHistoryQuality(
                    history_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    history_start=None,
                    history_end=None,
                    history_provider_set="helius",
                    history_completeness=COMPLETENESS_LOW,
                    history_completeness_reason="only assessment, created after report end",
                    acquisition_manifest=None,
                    excluded_evidence=[],
                    algorithm_version="test-v1",
                    created_at=_NOW + timedelta(hours=1),
                )
            )

        independent = await _independent_current_low_completeness_count(
            admin_engine, wallet_ids=[wallet_id], cutoff=earlier_cutoff
        )
        assert independent == 0

        earlier_report = await build_daily_report(
            sessionmaker,
            now=earlier_cutoff,
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
            window=timedelta(days=1),
        )
        assert earlier_report.data_quality["low_completeness_wallets"] == baseline
    finally:
        await _cleanup_wallets(admin_engine, [address])
        await engine.dispose()


# ---------------------------------------------------------------------
# 4a. Shadow probe outcomes, provider gaps, and matured mark outcomes.
# ---------------------------------------------------------------------


async def test_shadow_probe_outcome_breakdown_and_overdue_distinguishable(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            await _seed_tracked_wallet_with_buy_swap(
                session, wallet_address=wallet_address, mint=mint, at=_NOW
            )
        result = await run_prospective_monitoring_pass(sessionmaker, config=config, now=_NOW)
        intent = result.shadow_intents[0]

        from tests.integration.test_shadow_phase4 import QueuedExecutionProvider, _quote

        entry_provider = QueuedExecutionProvider(
            queue=[
                _quote(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                )
            ]
        )
        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker, entry_provider, config=config, clock=Clock(), now=far_future, limit=1
        )
        assert processed[0].outcome == OUTCOME_SUCCESS

        async with sessionmaker() as session:
            position = (
                await session.execute(
                    select(ShadowPosition).where(
                        ShadowPosition.shadow_intent_id == intent.shadow_intent_id
                    )
                )
            ).scalar_one()

        marked_at = far_future + timedelta(seconds=5)
        async with sessionmaker() as session, session.begin():
            # Three real, distinct REVERSE_EXECUTABLE outcomes on the same
            # position -- success, a genuine unsellable NO_ROUTE, and an
            # honest PROVIDER_CAPACITY_MISS -- all matured inside the
            # report window.
            session.add(
                ShadowQuoteProbe(
                    probe_id=uuid.uuid4(),
                    probe_kind=PROBE_KIND_REVERSE_EXECUTABLE,
                    target_label="test-success",
                    target_seconds_from_observation=None,
                    shadow_intent_id=None,
                    shadow_position_id=position.shadow_position_id,
                    input_mint=position.output_mint,
                    output_mint=position.input_mint,
                    notional_input_amount_raw=position.entry_output_amount_raw,
                    target_due_at=marked_at,
                    claimed_at=marked_at,
                    claimed_by="test-worker",
                    claim_generation=1,
                    requested_at=marked_at,
                    responded_at=marked_at,
                    terminal_at=marked_at,
                    outcome=OUTCOME_SUCCESS,
                    route_present=True,
                    expected_output_amount_raw=90_000_000,
                    algorithm_version="test-v1",
                    created_at=marked_at,
                )
            )
            session.add(
                ShadowQuoteProbe(
                    probe_id=uuid.uuid4(),
                    probe_kind=PROBE_KIND_REVERSE_EXECUTABLE,
                    target_label="test-no-route",
                    target_seconds_from_observation=None,
                    shadow_intent_id=None,
                    shadow_position_id=position.shadow_position_id,
                    input_mint=position.output_mint,
                    output_mint=position.input_mint,
                    notional_input_amount_raw=position.entry_output_amount_raw,
                    target_due_at=marked_at,
                    claimed_at=marked_at,
                    claimed_by="test-worker",
                    claim_generation=1,
                    requested_at=marked_at,
                    responded_at=marked_at,
                    terminal_at=marked_at,
                    outcome=OUTCOME_NO_ROUTE,
                    route_present=False,
                    algorithm_version="test-v1",
                    created_at=marked_at,
                )
            )
            session.add(
                ShadowQuoteProbe(
                    probe_id=uuid.uuid4(),
                    probe_kind=PROBE_KIND_REVERSE_EXECUTABLE,
                    target_label="test-capmiss",
                    target_seconds_from_observation=None,
                    shadow_intent_id=None,
                    shadow_position_id=position.shadow_position_id,
                    input_mint=position.output_mint,
                    output_mint=position.input_mint,
                    notional_input_amount_raw=position.entry_output_amount_raw,
                    target_due_at=marked_at,
                    claimed_at=marked_at,
                    claimed_by="test-worker",
                    claim_generation=1,
                    # A genuine scheduler-level capacity drop never
                    # dispatches -- requested_at/responded_at stay
                    # honestly None; only terminal_at records the real
                    # decision time (P4-remediation-002 R4).
                    requested_at=None,
                    responded_at=None,
                    terminal_at=marked_at,
                    outcome=OUTCOME_PROVIDER_CAPACITY_MISS,
                    route_present=False,
                    algorithm_version="test-v1",
                    created_at=marked_at,
                )
            )
            # A fourth probe, due well before the report's own window
            # ends but never claimed/attempted at all -- overdue and
            # unattempted, a genuinely different state from the terminal
            # no-send capacity-miss probe above (which DID reach a
            # terminal decision, just declined to dispatch).
            session.add(
                ShadowQuoteProbe(
                    probe_id=uuid.uuid4(),
                    probe_kind=PROBE_KIND_REVERSE_EXECUTABLE,
                    target_label="test-overdue",
                    target_seconds_from_observation=None,
                    shadow_intent_id=None,
                    shadow_position_id=position.shadow_position_id,
                    input_mint=position.output_mint,
                    output_mint=position.input_mint,
                    notional_input_amount_raw=position.entry_output_amount_raw,
                    target_due_at=marked_at,
                    claimed_at=None,
                    claimed_by=None,
                    claim_generation=0,
                    requested_at=None,
                    responded_at=None,
                    terminal_at=None,
                    outcome=OUTCOME_PENDING,
                    route_present=None,
                    algorithm_version="test-v1",
                    created_at=marked_at,
                )
            )

            # Update two of the already-scheduled mark outcomes: one
            # genuinely RECORDED, one an honest PRICE_UNAVAILABLE -- the
            # latter must never be counted as a matured mark outcome.
            marks = (
                (
                    await session.execute(
                        select(ShadowMarkOutcome).where(
                            ShadowMarkOutcome.shadow_position_id == position.shadow_position_id,
                            ShadowMarkOutcome.horizon_label.in_(("5m", "30m")),
                        )
                    )
                )
                .scalars()
                .all()
            )
            by_label = {m.horizon_label: m for m in marks}
            by_label["5m"].actual_at = marked_at
            by_label["5m"].outcome = OUTCOME_RECORDED
            by_label["5m"].mark_price_usd = Decimal("1.50")
            by_label["5m"].mark_return_pct = Decimal("0.50")
            by_label["5m"].provider = "test-provider"
            by_label["30m"].actual_at = marked_at
            by_label["30m"].outcome = OUTCOME_PRICE_UNAVAILABLE

        report_now = marked_at + timedelta(minutes=1)
        report = await build_daily_report(
            sessionmaker,
            now=report_now,
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
        )

        assert report.shadow["shadow_trades_opened_in_window"] == 1
        outcomes = report.shadow["reverse_executable_outcomes_in_window"]
        assert outcomes["successful"] == 1
        assert outcomes["unsellable"] == 1
        assert outcomes["missing_capacity"] == 1
        # usable_sample excludes the missing-capacity terminal no-send
        # record -- 2 (success + unsellable), never 3.
        assert outcomes["usable_sample"] == 2
        assert outcomes["total_attempts_including_missing_capacity"] == 3
        # Overdue-unattempted (never reached ANY terminal decision) stays
        # a genuinely distinct count from the terminal no-send capacity
        # miss above -- both are real, neither zeroed against the other.
        assert report.shadow["reverse_executable_overdue_unattempted"] == 1
        assert report.shadow["matured_mark_outcomes_in_window"] == 1
        assert report.data_quality["provider_gaps"] == 1
        # This window's own real ShadowMarkOutcome return (+0.50, one
        # sample) now surfaces descriptively in shadow mfe/mae.
        mfe_mae = report.shadow["mfe_mae"]
        assert isinstance(mfe_mae, dict)
        assert mfe_mae["sample_count"] == 1
        assert Decimal(mfe_mae["sampled_max_return_pct"]) == Decimal("0.50")
        assert Decimal(mfe_mae["sampled_min_return_pct"]) == Decimal("0.50")
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 4b. Descriptive SHADOW mfe/mae is sampled from this window's own real
#     ShadowMarkOutcome returns -- no historical WalletPosition rows
#     needed at all (P4-remediation-002 R6, the instruction's own worked
#     example: +0.5/-0.2 => sampled max +0.5/min -0.2, count 2). A
#     late/out-of-window mark can never change an earlier report's
#     already-generated scope.
# ---------------------------------------------------------------------


async def test_shadow_mfe_mae_sampled_from_mark_outcomes_no_historical_rows_needed(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            await _seed_tracked_wallet_with_buy_swap(
                session, wallet_address=wallet_address, mint=mint, at=_NOW
            )
        result = await run_prospective_monitoring_pass(sessionmaker, config=config, now=_NOW)
        intent = result.shadow_intents[0]

        from tests.integration.test_shadow_phase4 import QueuedExecutionProvider, _quote

        entry_provider = QueuedExecutionProvider(
            queue=[
                _quote(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                )
            ]
        )
        far_future = _NOW + timedelta(seconds=400)
        processed = await run_due_entry_probes(
            sessionmaker, entry_provider, config=config, clock=Clock(), now=far_future, limit=1
        )
        assert processed[0].outcome == OUTCOME_SUCCESS

        async with sessionmaker() as session:
            position = (
                await session.execute(
                    select(ShadowPosition).where(
                        ShadowPosition.shadow_intent_id == intent.shadow_intent_id
                    )
                )
            ).scalar_one()

        marked_at = far_future + timedelta(seconds=5)
        report_now = marked_at + timedelta(minutes=1)
        out_of_window_at = report_now - timedelta(hours=25)  # older than the 24h window
        async with sessionmaker() as session, session.begin():
            marks = (
                (
                    await session.execute(
                        select(ShadowMarkOutcome).where(
                            ShadowMarkOutcome.shadow_position_id == position.shadow_position_id,
                            ShadowMarkOutcome.horizon_label.in_(("5m", "30m", "1h")),
                        )
                    )
                )
                .scalars()
                .all()
            )
            by_label = {m.horizon_label: m for m in marks}
            # Two in-window RECORDED returns -- the instruction's own
            # worked example.
            by_label["5m"].actual_at = marked_at
            by_label["5m"].outcome = OUTCOME_RECORDED
            by_label["5m"].mark_price_usd = Decimal("1.50")
            by_label["5m"].mark_return_pct = Decimal("0.50")
            by_label["5m"].provider = "test-provider"
            by_label["30m"].actual_at = marked_at + timedelta(seconds=1)
            by_label["30m"].outcome = OUTCOME_RECORDED
            by_label["30m"].mark_price_usd = Decimal("0.80")
            by_label["30m"].mark_return_pct = Decimal("-0.20")
            by_label["30m"].provider = "test-provider"
            # A third, genuinely RECORDED return -- but its actual_at is
            # OUTSIDE this report's window. It must never change this
            # report's own sampled max/min/count.
            by_label["1h"].actual_at = out_of_window_at
            by_label["1h"].outcome = OUTCOME_RECORDED
            by_label["1h"].mark_price_usd = Decimal("100.00")
            by_label["1h"].mark_return_pct = Decimal("99.00")
            by_label["1h"].provider = "test-provider"

        report = await build_daily_report(
            sessionmaker,
            now=report_now,
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
        )

        mfe_mae = report.shadow["mfe_mae"]
        assert isinstance(mfe_mae, dict)
        assert mfe_mae["sample_count"] == 2
        assert Decimal(mfe_mae["sampled_max_return_pct"]) == Decimal("0.50")
        assert Decimal(mfe_mae["sampled_min_return_pct"]) == Decimal("-0.20")
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 4c. Historical Phase 3 backtest mfe/mae, when retained, is grouped by
#     quote asset -- never averaged across e.g. SOL and USDC into a
#     meaningless unlabeled figure (P4-remediation-002 R6). The
#     ``historical_backtest`` figures are GLOBAL (current-state, not
#     window-scoped), so both tests below diff against an independently
#     computed baseline (a correlated NOT EXISTS "current reconstruction"
#     query -- a different shape than production's own DISTINCT ON)
#     rather than asserting a brittle absolute count.
# ---------------------------------------------------------------------


async def _independent_historical_mfe_sample(
    admin_engine, *, quote_asset_mint: str
) -> tuple[int, Decimal]:
    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT count(*), COALESCE(sum(wp.mfe_quote), 0) "
                    "FROM wallet_positions wp "
                    "JOIN wallet_history_quality whq ON whq.history_id = wp.history_id "
                    "WHERE wp.quote_asset_mint = :quote_asset_mint "
                    "AND wp.mfe_quote IS NOT NULL AND wp.mae_quote IS NOT NULL "
                    "AND NOT EXISTS ("
                    "  SELECT 1 FROM wallet_history_quality whq2 "
                    "  WHERE whq2.wallet_id = whq.wallet_id "
                    "  AND whq2.created_at > whq.created_at"
                    ")"
                ),
                {"quote_asset_mint": quote_asset_mint},
            )
        ).one()
    return row[0], row[1]


async def test_historical_backtest_grouped_by_quote_asset_never_averaged(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    usdc_mint = f"USDCTest{uuid.uuid4().hex[:24]}"
    config, engine, sessionmaker = _sessionmaker()
    try:
        sol_baseline_count, sol_baseline_sum = await _independent_historical_mfe_sample(
            admin_engine, quote_asset_mint=SOL_MINT
        )

        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet_only(session, wallet_address=wallet_address, at=_NOW)
            token_id = uuid.uuid4()
            session.add(
                Token(
                    token_id=token_id,
                    mint=mint,
                    chain="solana",
                    first_observed_at=_NOW,
                    mint_validated=False,
                    current_lifecycle_stage=None,
                    created_at=_NOW,
                )
            )
            history_id = uuid.uuid4()
            session.add(
                WalletHistoryQuality(
                    history_id=history_id,
                    wallet_id=wallet_id,
                    history_start=None,
                    history_end=None,
                    history_provider_set="helius",
                    history_completeness=COMPLETENESS_HIGH,
                    history_completeness_reason="full acquisition walk",
                    acquisition_manifest=None,
                    excluded_evidence=[],
                    algorithm_version="test-v1",
                    created_at=_NOW,
                )
            )
            await session.flush()
            # A SOL-quoted position (mfe=1.0) and a USDC-quoted position
            # (mfe=100.0) for the SAME wallet/history -- a naive
            # cross-unit average would silently produce an unlabeled
            # 50.5, which must never appear anywhere in the report.
            session.add(
                WalletPosition(
                    position_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    token_id=token_id,
                    history_id=history_id,
                    quote_asset_mint=SOL_MINT,
                    round_trip_index=0,
                    input_manifest_digest=None,
                    first_entry_at=_NOW,
                    last_entry_at=_NOW,
                    final_exit_at=_NOW,
                    entry_quantity=Decimal("1"),
                    entry_value_quote=Decimal("1"),
                    average_cost_quote=Decimal("1"),
                    partial_exit_count=0,
                    realized_pnl_quote=None,
                    unrealized_pnl_quote=None,
                    holding_duration_seconds=3600,
                    mfe_quote=Decimal("1.000000000000000000"),
                    mae_quote=Decimal("-0.500000000000000000"),
                    peak_value_quote=None,
                    peak_profit_capture=None,
                    confidence=CONFIDENCE_HIGH,
                    status=STATUS_CLOSED,
                    algorithm_version="test-v1",
                    git_commit=_TEST_GIT_COMMIT,
                    created_at=_NOW,
                )
            )
            session.add(
                WalletPosition(
                    position_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    token_id=token_id,
                    history_id=history_id,
                    quote_asset_mint=usdc_mint,
                    round_trip_index=1,
                    input_manifest_digest=None,
                    first_entry_at=_NOW,
                    last_entry_at=_NOW,
                    final_exit_at=_NOW,
                    entry_quantity=Decimal("1"),
                    entry_value_quote=Decimal("1"),
                    average_cost_quote=Decimal("1"),
                    partial_exit_count=0,
                    realized_pnl_quote=None,
                    unrealized_pnl_quote=None,
                    holding_duration_seconds=3600,
                    mfe_quote=Decimal("100.000000000000000000"),
                    mae_quote=Decimal("-50.000000000000000000"),
                    peak_value_quote=None,
                    peak_profit_capture=None,
                    confidence=CONFIDENCE_HIGH,
                    status=STATUS_CLOSED,
                    algorithm_version="test-v1",
                    git_commit=_TEST_GIT_COMMIT,
                    created_at=_NOW,
                )
            )

        report = await build_daily_report(
            sessionmaker,
            now=_NOW + timedelta(minutes=1),
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
        )

        by_asset = report.research["historical_backtest"]["mfe_mae_by_quote_asset"]
        assert isinstance(by_asset, dict)
        # SOL_MINT is shared across this whole test suite -- diff against
        # the independently-measured baseline rather than an absolute
        # count.
        assert by_asset[SOL_MINT]["sample_count"] == sol_baseline_count + 1
        expected_sol_avg = (sol_baseline_sum + Decimal("1.000000000000000000")) / (
            sol_baseline_count + 1
        )
        assert Decimal(by_asset[SOL_MINT]["avg_mfe_quote"]) == expected_sol_avg
        # usdc_mint is a fresh, uniquely-random mint this test alone
        # created -- safe as an absolute assertion.
        assert by_asset[usdc_mint]["sample_count"] == 1
        assert Decimal(by_asset[usdc_mint]["avg_mfe_quote"]) == Decimal("100.000000000000000000")
        # No unlabeled cross-asset average anywhere in the payload.
        flattened_values = [v for entry in by_asset.values() for v in entry.values()]
        assert "50.5" not in [str(v) for v in flattened_values]
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# 4d. A repeated reconstruction (a superseded WalletHistoryQuality row
#     for the same wallet, with its own now-stale WalletPosition set)
#     must not multiply the historical backtest sample -- only the
#     wallet's CURRENT chosen history's positions are ever counted
#     (P4-remediation-002 R6).
# ---------------------------------------------------------------------


async def test_repeated_reconstruction_does_not_multiply_historical_samples(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        sol_baseline_count, sol_baseline_sum = await _independent_historical_mfe_sample(
            admin_engine, quote_asset_mint=SOL_MINT
        )

        async with sessionmaker() as session, session.begin():
            wallet_id = await _seed_wallet_only(session, wallet_address=wallet_address, at=_NOW)
            token_id = uuid.uuid4()
            session.add(
                Token(
                    token_id=token_id,
                    mint=mint,
                    chain="solana",
                    first_observed_at=_NOW,
                    mint_validated=False,
                    current_lifecycle_stage=None,
                    created_at=_NOW,
                )
            )
            # First (stale) reconstruction -- superseded below.
            stale_history_id = uuid.uuid4()
            session.add(
                WalletHistoryQuality(
                    history_id=stale_history_id,
                    wallet_id=wallet_id,
                    history_start=None,
                    history_end=None,
                    history_provider_set="helius",
                    history_completeness=COMPLETENESS_HIGH,
                    history_completeness_reason="first pass",
                    acquisition_manifest=None,
                    excluded_evidence=[],
                    algorithm_version="test-v1",
                    created_at=_NOW,
                )
            )
            # A later, CURRENT reconstruction for the same wallet.
            current_history_id = uuid.uuid4()
            session.add(
                WalletHistoryQuality(
                    history_id=current_history_id,
                    wallet_id=wallet_id,
                    history_start=None,
                    history_end=None,
                    history_provider_set="helius",
                    history_completeness=COMPLETENESS_HIGH,
                    history_completeness_reason="second, corrected pass",
                    acquisition_manifest=None,
                    excluded_evidence=[],
                    algorithm_version="test-v1",
                    created_at=_NOW + timedelta(minutes=1),
                )
            )
            await session.flush()
            # A stale position tied to the SUPERSEDED reconstruction --
            # must never be counted.
            session.add(
                WalletPosition(
                    position_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    token_id=token_id,
                    history_id=stale_history_id,
                    quote_asset_mint=SOL_MINT,
                    round_trip_index=0,
                    input_manifest_digest=None,
                    first_entry_at=_NOW,
                    last_entry_at=_NOW,
                    final_exit_at=_NOW,
                    entry_quantity=Decimal("1"),
                    entry_value_quote=Decimal("1"),
                    average_cost_quote=Decimal("1"),
                    partial_exit_count=0,
                    realized_pnl_quote=None,
                    unrealized_pnl_quote=None,
                    holding_duration_seconds=3600,
                    mfe_quote=Decimal("999.000000000000000000"),
                    mae_quote=Decimal("-999.000000000000000000"),
                    peak_value_quote=None,
                    peak_profit_capture=None,
                    confidence=CONFIDENCE_HIGH,
                    status=STATUS_CLOSED,
                    algorithm_version="test-v1",
                    git_commit=_TEST_GIT_COMMIT,
                    created_at=_NOW,
                )
            )
            # The CURRENT reconstruction's own position -- the only one
            # that should ever be counted.
            session.add(
                WalletPosition(
                    position_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    token_id=token_id,
                    history_id=current_history_id,
                    quote_asset_mint=SOL_MINT,
                    round_trip_index=0,
                    input_manifest_digest=None,
                    first_entry_at=_NOW,
                    last_entry_at=_NOW,
                    final_exit_at=_NOW,
                    entry_quantity=Decimal("1"),
                    entry_value_quote=Decimal("1"),
                    average_cost_quote=Decimal("1"),
                    partial_exit_count=0,
                    realized_pnl_quote=None,
                    unrealized_pnl_quote=None,
                    holding_duration_seconds=3600,
                    mfe_quote=Decimal("5.000000000000000000"),
                    mae_quote=Decimal("-2.000000000000000000"),
                    peak_value_quote=None,
                    peak_profit_capture=None,
                    confidence=CONFIDENCE_HIGH,
                    status=STATUS_CLOSED,
                    algorithm_version="test-v1",
                    git_commit=_TEST_GIT_COMMIT,
                    created_at=_NOW,
                )
            )

        report = await build_daily_report(
            sessionmaker,
            now=_NOW + timedelta(minutes=5),
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
        )

        by_asset = report.research["historical_backtest"]["mfe_mae_by_quote_asset"]
        assert isinstance(by_asset, dict)
        # Exactly +1 sample (the current reconstruction's own position),
        # never +2 (which would mean the stale reconstruction's position
        # was also counted) -- diffed against the independently-measured
        # baseline since SOL_MINT is shared across this whole suite.
        assert by_asset[SOL_MINT]["sample_count"] == sol_baseline_count + 1
        expected_sol_avg = (sol_baseline_sum + Decimal("5.000000000000000000")) / (
            sol_baseline_count + 1
        )
        assert Decimal(by_asset[SOL_MINT]["avg_mfe_quote"]) == expected_sol_avg
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await _cleanup_token(admin_engine, mint)
        await engine.dispose()


# ---------------------------------------------------------------------
# 5. Ordinary shadow-event notifier invocation via the real service path.
# ---------------------------------------------------------------------


async def test_run_due_entry_probes_notifies_real_shadow_event(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            await _seed_tracked_wallet_with_buy_swap(
                session, wallet_address=wallet_address, mint=mint, at=_NOW
            )
        result = await run_prospective_monitoring_pass(sessionmaker, config=config, now=_NOW)
        intent = result.shadow_intents[0]

        from tests.integration.test_shadow_phase4 import QueuedExecutionProvider, _quote

        provider = QueuedExecutionProvider(
            queue=[
                _quote(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                )
            ]
        )
        transport = FakeTelegramTransport()
        notifier = TelegramNotifier(transport, chat_id="test-chat")
        far_future = _NOW + timedelta(seconds=400)

        processed = await run_due_entry_probes(
            sessionmaker,
            provider,
            config=config,
            clock=Clock(),
            now=far_future,
            limit=1,
            notifier=notifier,
        )
        assert processed[0].outcome == OUTCOME_SUCCESS

        async with sessionmaker() as session:
            position = (
                await session.execute(
                    select(ShadowPosition).where(
                        ShadowPosition.shadow_intent_id == intent.shadow_intent_id
                    )
                )
            ).scalar_one()

        # Real production path -- never a manual .notify() call in this
        # test itself -- delivers exactly one SHADOW_EVENT notification
        # whose text references the real just-committed facts: the
        # shadow_intent_id (which 1:1-identifies the position just
        # created, via shadow_positions' own unique shadow_intent_id
        # constraint) and the real mints, never a hardcoded/generic
        # string.
        assert position.shadow_intent_id == intent.shadow_intent_id
        assert len(transport.sent) == 1
        sent_chat_id, sent_text = transport.sent[0]
        assert sent_chat_id == "test-chat"
        assert str(intent.shadow_intent_id) in sent_text
        assert intent.input_mint in sent_text
        assert intent.output_mint in sent_text
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 6. Ordinary daily-report notifier invocation via the real service path.
# ---------------------------------------------------------------------


async def test_build_daily_report_notifies_real_daily_summary(admin_engine) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            await _seed_tracked_wallet_with_buy_swap(
                session, wallet_address=wallet_address, mint=mint, at=_NOW
            )
        await run_prospective_monitoring_pass(sessionmaker, config=config, now=_NOW)

        transport = FakeTelegramTransport()
        notifier = TelegramNotifier(transport, chat_id="test-chat")
        report_now = _NOW + timedelta(minutes=1)

        report = await build_daily_report(
            sessionmaker,
            now=report_now,
            tier_allowed=config.get("thresholds.wallet_tier_allowed"),
            notifier=notifier,
        )

        assert len(transport.sent) == 1
        sent_chat_id, sent_text = transport.sent[0]
        assert sent_chat_id == "test-chat"
        assert str(report.discovery["new_wallets"]) in sent_text
        assert str(report.signals["signals"]) in sent_text
        assert str(report.shadow["shadow_trades_opened_in_window"]) in sent_text
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# ---------------------------------------------------------------------
# 7. A failing notifier never loses or rewrites the underlying record.
# ---------------------------------------------------------------------


async def test_daily_report_notifier_failure_never_affects_the_returned_report(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            await _seed_tracked_wallet_with_buy_swap(
                session, wallet_address=wallet_address, mint=mint, at=_NOW
            )
        await run_prospective_monitoring_pass(sessionmaker, config=config, now=_NOW)

        report_now = _NOW + timedelta(minutes=1)
        tier_allowed = config.get("thresholds.wallet_tier_allowed")

        failing_notifier = TelegramNotifier(_FailingTransport(), chat_id="test-chat")
        # Must not raise, despite the transport always raising.
        report_with_failing_notifier = await build_daily_report(
            sessionmaker, now=report_now, tier_allowed=tier_allowed, notifier=failing_notifier
        )

        report_without_notifier = await build_daily_report(
            sessionmaker, now=report_now, tier_allowed=tier_allowed
        )

        assert report_with_failing_notifier.discovery == report_without_notifier.discovery
        assert report_with_failing_notifier.tracking == report_without_notifier.tracking
        assert report_with_failing_notifier.signals == report_without_notifier.signals
        assert report_with_failing_notifier.shadow == report_without_notifier.shadow
        assert report_with_failing_notifier.data_quality == report_without_notifier.data_quality
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


async def test_shadow_probe_notifier_failure_never_affects_the_committed_position(
    admin_engine,
) -> None:
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    config, engine, sessionmaker = _sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            await _seed_tracked_wallet_with_buy_swap(
                session, wallet_address=wallet_address, mint=mint, at=_NOW
            )
        result = await run_prospective_monitoring_pass(sessionmaker, config=config, now=_NOW)
        intent = result.shadow_intents[0]

        from tests.integration.test_shadow_phase4 import QueuedExecutionProvider, _quote

        provider = QueuedExecutionProvider(
            queue=[
                _quote(
                    input_mint=intent.input_mint,
                    output_mint=intent.output_mint,
                    in_amount=intent.notional_input_amount_raw,
                    out_amount=500_000,
                )
            ]
        )
        failing_notifier = TelegramNotifier(_FailingTransport(), chat_id="test-chat")
        far_future = _NOW + timedelta(seconds=400)

        # Must not raise, despite the transport always raising.
        processed = await run_due_entry_probes(
            sessionmaker,
            provider,
            config=config,
            clock=Clock(),
            now=far_future,
            limit=1,
            notifier=failing_notifier,
        )
        assert len(processed) == 1
        assert processed[0].outcome == OUTCOME_SUCCESS

        async with sessionmaker() as session:
            position = (
                await session.execute(
                    select(ShadowPosition).where(
                        ShadowPosition.shadow_intent_id == intent.shadow_intent_id
                    )
                )
            ).scalar_one()
            assert position.entry_output_amount_raw == 500_000
            assert position.input_mint == intent.input_mint
            assert position.output_mint == intent.output_mint

            reloaded_intent = await session.get(ShadowIntent, intent.shadow_intent_id)
            assert reloaded_intent.status == "FILLED"
    finally:
        await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()
