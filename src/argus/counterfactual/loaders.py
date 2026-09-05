"""argus.counterfactual.loaders -- MASTER_SPEC.md Phase 9 production data
loaders: point-in-time token market-state lookups, a raw-swap-derived
tracked-wallet exit event population (mirroring how Phase 4 itself
derived entry events from ``swaps``, but for the sell side, which no
prior phase persisted as its own observational ledger), and read-through
reuse of Phase 3's already-computed exit-skill component.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.copyability.identity import known_by_cutoff
from argus.domain.swaps import Swap
from argus.domain.token_market_snapshots import TokenMarketSnapshot
from argus.domain.tokens import Token
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallets import Wallet
from argus.graph.lead_follow import WalletTokenEntry
from argus.shadow.prospective import QUOTE_ASSETS

_INTERESTING_CLASSIFICATIONS = ("SWAP_SIMPLE",)


def is_sell(swap: Swap) -> bool:
    """The mirror of ``argus.shadow.prospective.is_buy`` for the exit
    side: input is the tracked token, output returns to a quote asset."""
    return (
        swap.input_mint is not None
        and swap.input_mint not in QUOTE_ASSETS
        and swap.output_mint in QUOTE_ASSETS
    )


async def load_token_market_snapshot_at_or_before(
    session: AsyncSession, *, token_id: uuid.UUID, at: datetime
) -> TokenMarketSnapshot | None:
    """The point-in-time pattern ``argus.tokens.reference_prices.
    latest_price_at_or_before`` established, applied to
    ``token_market_snapshots``."""
    return (
        await session.execute(
            select(TokenMarketSnapshot)
            .where(TokenMarketSnapshot.token_id == token_id, TokenMarketSnapshot.observed_at <= at)
            .order_by(TokenMarketSnapshot.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def load_nearest_token_market_snapshot(
    session: AsyncSession, *, token_id: uuid.UUID, target: datetime, max_staleness_seconds: float
) -> TokenMarketSnapshot | None:
    """The snapshot whose ``observed_at`` is closest to ``target`` (before
    OR after), within ``max_staleness_seconds`` -- for a *forward*-return
    horizon price, reusing the last known price from long before the
    target time would misrepresent a future price as known; ``None`` is
    the honest answer when nothing sufficiently close exists."""
    before = (
        await session.execute(
            select(TokenMarketSnapshot)
            .where(
                TokenMarketSnapshot.token_id == token_id,
                TokenMarketSnapshot.observed_at <= target,
            )
            .order_by(TokenMarketSnapshot.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    after = (
        await session.execute(
            select(TokenMarketSnapshot)
            .where(
                TokenMarketSnapshot.token_id == token_id, TokenMarketSnapshot.observed_at > target
            )
            .order_by(TokenMarketSnapshot.observed_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    candidates = [c for c in (before, after) if c is not None]
    within_tolerance = [
        c
        for c in candidates
        if abs((c.observed_at - target).total_seconds()) <= max_staleness_seconds
    ]
    if not within_tolerance:
        return None
    return min(within_tolerance, key=lambda c: abs((c.observed_at - target).total_seconds()))


async def load_candidate_tokens(session: AsyncSession, *, cutoff: datetime) -> list[Token]:
    """Every token known by ``cutoff`` -- the broad opportunity-set
    universe section 55's matched-control search draws from (not merely
    tokens tracked wallets happened to enter)."""
    rows = (
        (await session.execute(select(Token).where(Token.first_observed_at <= cutoff)))
        .scalars()
        .all()
    )
    return [
        t
        for t in rows
        if known_by_cutoff(created_at=t.created_at, effective_at=t.first_observed_at, cutoff=cutoff)
    ]


async def load_wallet_token_exits(
    session: AsyncSession, *, cutoff: datetime
) -> list[WalletTokenEntry]:
    """Every tracked-wallet token EXIT (sell-back-to-quote-asset swap)
    known by ``cutoff`` -- derived directly from the raw ``swaps`` ledger
    (Phase 1), mirroring how Phase 4 itself derived BUY-side
    ``prospective_events`` from the same ledger. No prior phase persisted
    a per-wallet-per-token "sold" observational unit; going straight to
    the raw swap evidence here is the same architectural move Phase 4
    made for entries, not new fabricated evidence."""
    wallets = (await session.execute(select(Wallet))).scalars().all()
    wallet_by_address = {w.wallet_address: w for w in wallets}
    if not wallet_by_address:
        return []

    tokens = (await session.execute(select(Token))).scalars().all()
    token_by_mint = {t.mint: t for t in tokens}
    if not token_by_mint:
        return []

    swaps = (
        (
            await session.execute(
                select(Swap).where(
                    Swap.wallet_address.in_(wallet_by_address.keys()),
                    Swap.classification.in_(_INTERESTING_CLASSIFICATIONS),
                )
            )
        )
        .scalars()
        .all()
    )

    exits: list[WalletTokenEntry] = []
    for swap in swaps:
        if not is_sell(swap):
            continue
        if swap.input_mint is None or swap.input_mint not in token_by_mint:
            continue
        if not known_by_cutoff(
            created_at=swap.created_at, effective_at=swap.first_seen_at, cutoff=cutoff
        ):
            continue
        wallet = wallet_by_address[swap.wallet_address]
        token = token_by_mint[swap.input_mint]
        exits.append(
            WalletTokenEntry(
                wallet_id=wallet.wallet_id,
                token_id=token.token_id,
                entered_at=swap.first_seen_at,
                source_id=swap.swap_id,
            )
        )
    return exits


async def load_latest_exit_skill(
    session: AsyncSession, *, wallet_id: uuid.UUID, cutoff: datetime
) -> tuple[Decimal, datetime] | None:
    """This wallet's own latest Phase 3 ``exit_capture`` component
    (``wallet_score_snapshots.component_values``) known by ``cutoff`` --
    reused unchanged, not recomputed. Returns ``(value, snapshot.created_at)``
    so a caller building R2-02 source-knowledge provenance can fold this
    row's own creation time into its bound; ``None`` when no eligible
    snapshot exists.

    Clarification-001 section 3 fix: previously bounded only by
    ``as_of <= cutoff``, never also ``created_at <= cutoff`` -- the same
    ``known_by_cutoff(created_at, effective_at, cutoff)`` invariant this
    table's OTHER consumer (``argus.prediction.loaders.
    wallet_fingerprint_at``) already applied correctly. A snapshot
    labeled ``as_of<=cutoff`` but not physically created until after
    cutoff was previously acceptable here -- a knowledge-time leak in the
    same family R2-02 already fixed for ``DirectionalEdge``/
    ``ExpectedConfirmationEvent``."""
    candidates = (
        (
            await session.execute(
                select(WalletScoreSnapshot)
                .where(WalletScoreSnapshot.wallet_id == wallet_id)
                .order_by(WalletScoreSnapshot.as_of.desc())
            )
        )
        .scalars()
        .all()
    )
    snapshot: WalletScoreSnapshot | None = None
    for candidate in candidates:
        if known_by_cutoff(
            created_at=candidate.created_at, effective_at=candidate.as_of, cutoff=cutoff
        ):
            snapshot = candidate
            break
    if snapshot is None:
        return None
    value = snapshot.component_values.get("exit_capture")
    if value is None:
        return None
    return Decimal(str(value)), snapshot.created_at
