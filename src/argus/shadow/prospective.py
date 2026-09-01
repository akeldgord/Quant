"""Prospective event creation (MASTER_SPEC.md section 44).

Consumes the real, already-persisted ``swaps`` rows Phase 1's fast/truth
path produced for wallets ARGUS actively tracks (``wallets.current_tier``
in the same ``wallet_tier_allowed`` set that already governs live
eligibility elsewhere in this project -- ``config/signals_v1.yaml``) --
never a test-only fixture, never a re-observation of the chain. This
module is a separate consumer over that already-durable evidence (the
same "scan for new work, create the derived row idempotently" shape
already proven by Phase 2's archaeology-trigger consumer), not an inline
step of Phase 1's own ingestion transaction -- keeping this addition
fully decoupled from Phase 1/3's already-audited transactional code,
matching this instruction's "no rework of prior phases" scope.

Honest limitation, disclosed here and in the Phase 4 checkpoint: the
persisted ``swaps`` row does not carry
``ParsedTransaction.matched_swap_program_id``/``matched_semantic_label``/
``matched_discriminator_hex``/``input_decimals``/``output_decimals`` (Phase
1 never persists them), so this module's own "sufficiently interesting"
gate (``classification == SWAP_SIMPLE`` and ``confidence`` at or above the
same numeric floor ``ParsedTransaction.is_copy_eligible`` uses) is a
disclosed approximation of that property, not a reproduction of it --
widening the ``swaps`` schema to carry the missing fields is out of this
instruction's scope (no rework of Phase 1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from sqlalchemy import select

from argus.domain.commitment import COMMITMENT_CONFIRMED, CommitmentObservation
from argus.domain.prospective_events import ProspectiveEvent
from argus.domain.swaps import Swap
from argus.domain.token_market_snapshots import TokenMarketSnapshot
from argus.domain.tokens import Token
from argus.domain.wallet_cluster_links import WalletClusterLink
from argus.domain.wallet_positions import WalletPosition
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallets import Wallet
from argus.parsing.generic_parser import NATIVE_SOL_ASSET, WRAPPED_SOL_MINT
from argus.wallets.clustering import ClusterLinkEvidence, assess_wallet_cluster_risk

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

ALGORITHM_VERSION: Final[str] = "prospective_monitoring_v1"

# See module docstring's "Honest limitation" -- mirrors, but does not
# reproduce, ``argus.parsing.generic_parser`` module-private
# ``_MIN_COPY_ELIGIBLE_CONFIDENCE`` (also Decimal("0.500")).
_MIN_INTERESTING_CONFIDENCE: Final[Decimal] = Decimal("0.500")
_INTERESTING_CLASSIFICATIONS: Final[frozenset[str]] = frozenset({"SWAP_SIMPLE"})

QUOTE_ASSETS: Final[frozenset[str]] = frozenset({NATIVE_SOL_ASSET, WRAPPED_SOL_MINT})

GRAPH_STATE_UNAVAILABLE: Final[dict] = {
    "available": False,
    "reason": "Phase 7 (ALPHA ANCESTRY) not yet implemented",
}


def is_buy(swap: Swap) -> bool:
    """A quote-asset-in, non-quote-asset-out swap -- the "wallet buys"
    direction section 46's delay probes require. Neither classification
    nor persisted evidence records "buy"/"sell" directly; this is the
    same mint-set heuristic the rest of this module already relies on."""
    return swap.input_mint in QUOTE_ASSETS and swap.output_mint not in QUOTE_ASSETS


def _non_quote_mint(swap: Swap) -> str | None:
    if swap.output_mint is not None and swap.output_mint not in QUOTE_ASSETS:
        return swap.output_mint
    if swap.input_mint is not None and swap.input_mint not in QUOTE_ASSETS:
        return swap.input_mint
    return None


async def _token_state_snapshot(session: AsyncSession, *, token: Token | None) -> dict:
    if token is None:
        return {"available": False, "reason": "mint is not a tracked tokens row"}
    latest = (
        await session.execute(
            select(TokenMarketSnapshot)
            .where(TokenMarketSnapshot.token_id == token.token_id)
            .order_by(TokenMarketSnapshot.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None:
        return {
            "available": True,
            "token_id": str(token.token_id),
            "mint": token.mint,
            "lifecycle_stage": token.current_lifecycle_stage,
            "market_snapshot_available": False,
        }
    return {
        "available": True,
        "token_id": str(token.token_id),
        "mint": token.mint,
        "lifecycle_stage": latest.lifecycle_stage,
        "market_snapshot_available": True,
        "price_usd": str(latest.price_usd) if latest.price_usd is not None else None,
        "liquidity_usd": str(latest.liquidity_usd) if latest.liquidity_usd is not None else None,
        "market_state_confidence": latest.market_state_confidence,
        "observed_at": latest.observed_at.isoformat(),
    }


async def _position_size_context(session: AsyncSession, *, wallet_id: uuid.UUID) -> dict:
    open_positions = (
        (
            await session.execute(
                select(WalletPosition).where(
                    WalletPosition.wallet_id == wallet_id, WalletPosition.status == "OPEN"
                )
            )
        )
        .scalars()
        .all()
    )
    distinct_tokens = {p.token_id for p in open_positions}
    quote_assets = {p.quote_asset_mint for p in open_positions}
    aggregate_entry_value_quote: str | None = None
    if len(quote_assets) == 1 and open_positions:
        total = sum(
            (p.entry_value_quote for p in open_positions if p.entry_value_quote is not None),
            start=Decimal(0),
        )
        aggregate_entry_value_quote = str(total)
    return {
        "open_position_count": len(open_positions),
        "distinct_open_token_count": len(distinct_tokens),
        "quote_assets": sorted(quote_assets),
        "mixed_quote_assets": len(quote_assets) > 1,
        "aggregate_entry_value_quote": aggregate_entry_value_quote,
    }


async def _cluster_state_snapshot(
    session: AsyncSession, *, wallet_id: uuid.UUID, now: datetime
) -> dict:
    links = (
        (
            await session.execute(
                select(WalletClusterLink).where(
                    (
                        (WalletClusterLink.wallet_a_id == wallet_id)
                        | (WalletClusterLink.wallet_b_id == wallet_id)
                    ),
                    WalletClusterLink.as_of <= now,
                    WalletClusterLink.created_at <= now,
                )
            )
        )
        .scalars()
        .all()
    )
    evidence = [
        ClusterLinkEvidence(
            other_wallet_id=str(
                link.wallet_b_id if link.wallet_a_id == wallet_id else link.wallet_a_id
            ),
            evidence_type=link.evidence_type,
            probability=link.probability,
        )
        for link in links
    ]
    assessment = assess_wallet_cluster_risk(evidence)
    return {
        "cluster_risk": str(assessment.cluster_risk)
        if assessment.cluster_risk is not None
        else None,
        "independence_probability": (
            str(assessment.independence_probability)
            if assessment.independence_probability is not None
            else None
        ),
        "highest_linked_wallet_id": assessment.highest_linked_wallet_id,
        "highest_probability": (
            str(assessment.highest_probability)
            if assessment.highest_probability is not None
            else None
        ),
        "link_count": len(links),
    }


async def _create_prospective_event(
    session: AsyncSession, *, wallet: Wallet, swap: Swap, now: datetime
) -> ProspectiveEvent:
    token: Token | None = None
    mint = _non_quote_mint(swap)
    if mint is not None:
        token = (
            await session.execute(select(Token).where(Token.mint == mint))
        ).scalar_one_or_none()

    latest_score = (
        await session.execute(
            select(WalletScoreSnapshot)
            .where(WalletScoreSnapshot.wallet_id == wallet.wallet_id)
            .order_by(WalletScoreSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    confirmed_at = (
        await session.execute(
            select(CommitmentObservation.observed_at)
            .where(
                CommitmentObservation.event_id == swap.event_id,
                CommitmentObservation.commitment_level == COMMITMENT_CONFIRMED,
            )
            .order_by(CommitmentObservation.observed_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    event = ProspectiveEvent(
        prospective_event_id=uuid.uuid4(),
        wallet_id=wallet.wallet_id,
        swap_id=swap.swap_id,
        token_id=token.token_id if token is not None else None,
        leader_transaction_time=swap.block_time,
        first_seen_at=swap.first_seen_at,
        confirmation_time=confirmed_at,
        wallet_score_snapshot=(
            latest_score.qualification_score if latest_score is not None else None
        ),
        wallet_tier_snapshot=wallet.current_tier or "DISCOVERED",
        token_state_snapshot=await _token_state_snapshot(session, token=token),
        position_size_context=await _position_size_context(session, wallet_id=wallet.wallet_id),
        cluster_state_snapshot=await _cluster_state_snapshot(
            session, wallet_id=wallet.wallet_id, now=now
        ),
        graph_state_snapshot=dict(GRAPH_STATE_UNAVAILABLE),
        algorithm_version=ALGORITHM_VERSION,
        created_at=now,
    )
    session.add(event)
    await session.flush()
    return event


async def scan_for_new_prospective_events(
    session: AsyncSession, *, tier_allowed: Sequence[str], now: datetime, limit: int = 100
) -> list[ProspectiveEvent]:
    """Finds real, already-persisted ``swaps`` rows for tracked wallets
    that have no ``prospective_events`` row yet, and creates one for
    each (idempotent: a swap already claimed by one is never revisited,
    enforced by ``prospective_events``'s own unique ``swap_id``
    constraint as the final defense-in-depth backstop)."""
    tracked_wallets = (
        (await session.execute(select(Wallet).where(Wallet.current_tier.in_(tuple(tier_allowed)))))
        .scalars()
        .all()
    )
    wallet_by_address = {w.wallet_address: w for w in tracked_wallets}
    if not wallet_by_address:
        return []

    existing_swap_ids = (await session.execute(select(ProspectiveEvent.swap_id))).scalars().all()
    existing = set(existing_swap_ids)

    candidate_swaps = (
        (
            await session.execute(
                select(Swap)
                .where(
                    Swap.wallet_address.in_(tuple(wallet_by_address.keys())),
                    Swap.classification.in_(tuple(_INTERESTING_CLASSIFICATIONS)),
                    Swap.confidence >= _MIN_INTERESTING_CONFIDENCE,
                )
                .order_by(Swap.created_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    created: list[ProspectiveEvent] = []
    for swap in candidate_swaps:
        if swap.swap_id in existing:
            continue
        wallet = wallet_by_address[swap.wallet_address]
        created.append(await _create_prospective_event(session, wallet=wallet, swap=swap, now=now))
    return created
