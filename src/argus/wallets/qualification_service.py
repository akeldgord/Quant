"""Phase 3 orchestration: wires history reconstruction, position
reconstruction, the discovery-contamination firewall, scoring,
clustering, and tier lifecycle together into one real service, callable
from a CLI command (`argus wallets reconstruct-and-score`) -- not a
test-only helper (MASTER_SPEC.md Phase 3, `argus-phase-3-001`).

Restart/replay idempotency (this instruction's required test 9): running
this service twice from identical ``swaps`` evidence must never insert a
duplicate ``wallet_positions``/``wallet_score_snapshots`` row. Each write
path here compares the freshly computed content against the wallet's own
latest existing row of that kind and skips the insert when they match
exactly -- ``wallet_tier_history`` gets the same property "for free" from
``argus.wallets.tier_lifecycle.determine_tier_transition`` already
returning ``None`` on no change.
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sqlalchemy import select

from argus.domain.early_buyers import EarlyBuyer
from argus.domain.swaps import Swap
from argus.domain.tokens import Token
from argus.domain.wallet_cluster_links import WalletClusterLink
from argus.domain.wallet_discovery_events import WalletDiscoveryEvent
from argus.domain.wallet_history_quality import WalletHistoryQuality
from argus.domain.wallet_metrics_snapshots import WINDOW_LIFETIME, WalletMetricsSnapshot
from argus.domain.wallet_positions import WalletPosition
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_tier_history import WalletTierTransition
from argus.domain.wallets import Wallet
from argus.wallets.clustering import ClusterLinkEvidence, assess_wallet_cluster_risk
from argus.wallets.history_reconstruction import assess_wallet_history
from argus.wallets.position_reconstruction import (
    ReconstructedPosition,
    reconstruct_positions_for_wallet,
)
from argus.wallets.scoring import PositionForScoring, score_wallet
from argus.wallets.tier_lifecycle import determine_tier_transition

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from argus.config import ArgusConfig
    from argus.wallets.history_reconstruction import EvidenceSource

ALGORITHM_VERSION: Final[str] = "wallet_qualification_service_v1"
BUILD_HASH: Final[str] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclasses.dataclass(frozen=True, slots=True)
class QualificationRunResult:
    wallet_id: uuid.UUID
    history_completeness: str
    positions_reconstructed: int
    positions_unchanged: int
    positions_written: int
    positions_skipped_untracked_token: int
    score_written: bool
    qualification_score: Decimal
    descriptive_score: Decimal
    eligible_for_qualification: bool
    tier_transition: tuple[str, str] | None
    current_tier: str


def _positions_equal(a: WalletPosition, r: ReconstructedPosition) -> bool:
    """Content equality for restart/replay idempotency -- deliberately
    excludes identity/audit columns (position_id/history_id/created_at/
    algorithm_version/git_commit), which legitimately differ between
    runs even when the derived numbers are unchanged."""
    return (
        a.quote_asset_mint == r.quote_asset_mint
        and a.first_entry_at == r.first_entry_at
        and a.last_entry_at == r.last_entry_at
        and a.final_exit_at == r.final_exit_at
        and a.entry_quantity == r.entry_quantity
        and a.entry_value_quote == r.entry_value_quote
        and a.average_cost_quote == r.average_cost_quote
        and a.partial_exit_count == r.partial_exit_count
        and a.realized_pnl_quote == r.realized_pnl_quote
        and a.unrealized_pnl_quote == r.unrealized_pnl_quote
        and a.holding_duration_seconds == r.holding_duration_seconds
        and a.mfe_quote == r.mfe_quote
        and a.mae_quote == r.mae_quote
        and a.peak_value_quote == r.peak_value_quote
        and a.peak_profit_capture == r.peak_profit_capture
        and a.confidence == r.confidence
        and a.status == r.status
    )


def _score_equal(
    a: WalletScoreSnapshot,
    *,
    qualification_score: Decimal,
    descriptive_score: Decimal,
    eligible: bool,
) -> bool:
    return (
        a.qualification_score == qualification_score
        and a.descriptive_score == descriptive_score
        and a.eligible_for_qualification == eligible
    )


async def reconstruct_and_score_wallet(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    wallet_address: str,
    evidence_source: EvidenceSource,
    acquisition_status: str | None,
    acquisition_known_gaps: str | None,
    config: ArgusConfig,
    git_commit: str,
    now: datetime,
) -> QualificationRunResult:
    async with session_factory() as session, session.begin():
        wallet = (
            await session.execute(select(Wallet).where(Wallet.wallet_address == wallet_address))
        ).scalar_one_or_none()
        if wallet is None:
            raise ValueError(
                f"no wallets row for address {wallet_address!r} -- Phase 3 reconstructs/scores "
                "already-discovered wallets only; run Phase 2 discovery first"
            )
        wallet_id = wallet.wallet_id

        swaps: Sequence[Swap] = (
            (await session.execute(select(Swap).where(Swap.wallet_address == wallet_address)))
            .scalars()
            .all()
        )

        # --- 1. history completeness -----------------------------------
        assessment = assess_wallet_history(
            list(swaps),
            wallet_address=wallet_address,
            evidence_source=evidence_source,
            acquisition_status=acquisition_status,
            acquisition_known_gaps=acquisition_known_gaps,
        )
        latest_history = (
            await session.execute(
                select(WalletHistoryQuality)
                .where(WalletHistoryQuality.wallet_id == wallet_id)
                .order_by(WalletHistoryQuality.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if (
            latest_history is not None
            and latest_history.history_start == assessment.history_start
            and latest_history.history_end == assessment.history_end
            and latest_history.history_completeness == assessment.history_completeness
            and latest_history.history_provider_set == assessment.history_provider_set
        ):
            history_row = latest_history
        else:
            history_row = WalletHistoryQuality(
                history_id=uuid.uuid4(),
                wallet_id=wallet_id,
                history_start=assessment.history_start,
                history_end=assessment.history_end,
                history_provider_set=assessment.history_provider_set,
                history_completeness=assessment.history_completeness,
                history_completeness_reason=assessment.history_completeness_reason,
                algorithm_version="history_reconstruction_v1",
                created_at=now,
            )
            session.add(history_row)
            await session.flush()

        # --- 2. discovery-contamination provenance ----------------------
        contaminated_rows = (
            (
                await session.execute(
                    select(WalletDiscoveryEvent.trigger_token_id).where(
                        WalletDiscoveryEvent.wallet_id == wallet_id,
                        WalletDiscoveryEvent.trigger_token_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        contaminated_token_ids = frozenset(str(t) for t in contaminated_rows)

        # --- 3. position reconstruction ----------------------------------
        reconstructed = reconstruct_positions_for_wallet(list(swaps))
        early_buyer_rows = (
            (await session.execute(select(EarlyBuyer).where(EarlyBuyer.wallet_id == wallet_id)))
            .scalars()
            .all()
        )
        early_buyer_by_token: dict[uuid.UUID, EarlyBuyer] = {
            row.token_id: row for row in early_buyer_rows
        }

        positions_written = 0
        positions_unchanged = 0
        positions_skipped = 0
        positions_for_scoring: list[PositionForScoring] = []
        for recon in reconstructed:
            token = (
                await session.execute(select(Token).where(Token.mint == recon.token_mint))
            ).scalar_one_or_none()
            if token is None:
                positions_skipped += 1
                continue

            latest_position = (
                await session.execute(
                    select(WalletPosition)
                    .where(
                        WalletPosition.wallet_id == wallet_id,
                        WalletPosition.token_id == token.token_id,
                    )
                    .order_by(WalletPosition.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if latest_position is not None and _positions_equal(latest_position, recon):
                positions_unchanged += 1
            else:
                session.add(
                    WalletPosition(
                        position_id=uuid.uuid4(),
                        wallet_id=wallet_id,
                        token_id=token.token_id,
                        history_id=history_row.history_id,
                        quote_asset_mint=recon.quote_asset_mint or "UNKNOWN",
                        first_entry_at=recon.first_entry_at,
                        last_entry_at=recon.last_entry_at,
                        final_exit_at=recon.final_exit_at,
                        entry_quantity=recon.entry_quantity,
                        entry_value_quote=recon.entry_value_quote,
                        average_cost_quote=recon.average_cost_quote,
                        partial_exit_count=recon.partial_exit_count,
                        realized_pnl_quote=recon.realized_pnl_quote,
                        unrealized_pnl_quote=recon.unrealized_pnl_quote,
                        holding_duration_seconds=recon.holding_duration_seconds,
                        mfe_quote=recon.mfe_quote,
                        mae_quote=recon.mae_quote,
                        peak_value_quote=recon.peak_value_quote,
                        peak_profit_capture=recon.peak_profit_capture,
                        confidence=recon.confidence,
                        status=recon.status,
                        algorithm_version="position_reconstruction_v1",
                        git_commit=git_commit,
                        created_at=now,
                    )
                )
                positions_written += 1

            early_buyer = early_buyer_by_token.get(token.token_id)
            positions_for_scoring.append(
                PositionForScoring(
                    token_id=str(token.token_id),
                    confidence=recon.confidence,
                    status=recon.status,
                    realized_pnl_quote=recon.realized_pnl_quote,
                    entry_value_quote=recon.entry_value_quote,
                    peak_profit_capture=recon.peak_profit_capture,
                    first_entry_at=recon.first_entry_at,
                    last_entry_at=recon.last_entry_at,
                    early_buyer_sequence_number=(
                        early_buyer.sequence_number if early_buyer is not None else None
                    ),
                    possible_deployer=(
                        early_buyer.possible_deployer if early_buyer is not None else False
                    ),
                )
            )
        await session.flush()

        # --- 4. clustering -------------------------------------------------
        link_rows = (
            (
                await session.execute(
                    select(WalletClusterLink).where(
                        (WalletClusterLink.wallet_a_id == wallet_id)
                        | (WalletClusterLink.wallet_b_id == wallet_id)
                    )
                )
            )
            .scalars()
            .all()
        )
        link_evidence = [
            ClusterLinkEvidence(
                other_wallet_id=str(
                    link.wallet_b_id if link.wallet_a_id == wallet_id else link.wallet_a_id
                ),
                evidence_type=link.evidence_type,
                probability=link.probability,
            )
            for link in link_rows
        ]
        cluster_assessment = assess_wallet_cluster_risk(link_evidence)

        # --- 5. scoring -----------------------------------------------------
        result = score_wallet(
            all_positions=positions_for_scoring,
            discovery_contaminated_token_ids=contaminated_token_ids,
            history_completeness=history_row.history_completeness,
            as_of=now,
        )
        penalties = dict(result.penalties)
        penalties["cluster_uncertainty_penalty"] = cluster_assessment.cluster_uncertainty_penalty
        qualification_score = max(
            Decimal(0), result.qualification_score - cluster_assessment.cluster_uncertainty_penalty
        )

        latest_score = (
            await session.execute(
                select(WalletScoreSnapshot)
                .where(WalletScoreSnapshot.wallet_id == wallet_id)
                .order_by(WalletScoreSnapshot.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        score_written = False
        if latest_score is not None and _score_equal(
            latest_score,
            qualification_score=qualification_score,
            descriptive_score=result.descriptive_score,
            eligible=result.eligible_for_qualification,
        ):
            score_row = latest_score
        else:
            score_row = WalletScoreSnapshot(
                score_id=uuid.uuid4(),
                wallet_id=wallet_id,
                as_of=now,
                score_version="qualification_score_v1",
                descriptive_score=result.descriptive_score,
                qualification_score=qualification_score,
                component_values={
                    k: (str(v) if v is not None else None)
                    for k, v in result.component_values.items()
                },
                penalties={k: str(v) for k, v in penalties.items()},
                confidence=result.confidence,
                excluded_discovery_token_ids=sorted(contaminated_token_ids),
                eligible_for_qualification=result.eligible_for_qualification,
                sample_gate_reason=result.sample_gate_reason,
                build_hash=BUILD_HASH,
                config_hash=config.config_hash,
                master_spec_hash=config.spec_hash,
                git_commit=git_commit,
                created_at=now,
            )
            session.add(score_row)
            await session.flush()
            score_written = True

        session.add(
            WalletMetricsSnapshot(
                snapshot_id=uuid.uuid4(),
                wallet_id=wallet_id,
                as_of=now,
                metrics_window=WINDOW_LIFETIME,
                selection_skill=result.fingerprint.selection_skill,
                early_discovery_skill=result.fingerprint.early_discovery_skill,
                entry_timing_skill=result.fingerprint.entry_timing_skill,
                exit_skill=result.fingerprint.exit_skill,
                risk_control_skill=result.fingerprint.risk_control_skill,
                consistency=result.fingerprint.consistency,
                copyability=result.fingerprint.copyability,
                forward_information_value=result.fingerprint.forward_information_value,
                recency=result.fingerprint.recency,
                data_confidence=result.fingerprint.data_confidence,
                insider_risk=result.fingerprint.insider_risk,
                cluster_risk=cluster_assessment.cluster_risk,
                independence_probability=cluster_assessment.independence_probability,
                predation_risk=None,
                automation_probability=None,
                median_return=result.stats.median_return,
                trimmed_mean_return=result.stats.trimmed_mean_return,
                winsorized_return=result.stats.winsorized_return,
                profit_factor=result.stats.profit_factor,
                hit_rate=result.stats.hit_rate,
                largest_trade_contribution_pct=result.stats.largest_trade_contribution_pct,
                top_three_trade_contribution_pct=result.stats.top_three_trade_contribution_pct,
                max_drawdown=result.stats.max_drawdown,
                distinct_profitable_token_count=result.stats.distinct_profitable_token_count,
                lottery_dominated=result.stats.lottery_dominated,
                usable_closed_positions_count=result.stats.closed_count,
                distinct_tokens_with_usable_outcomes_count=result.stats.distinct_tokens,
                algorithm_version="wallet_scoring_v1",
                git_commit=git_commit,
                created_at=now,
            )
        )

        # --- 6. tier lifecycle -----------------------------------------
        transition = determine_tier_transition(
            current_tier=wallet.current_tier,
            scoring=result,
            insider_risk=result.fingerprint.insider_risk,
            cluster_risk=cluster_assessment.cluster_risk,
        )
        if transition is not None:
            new_tier, reason = transition
            session.add(
                WalletTierTransition(
                    transition_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    source_score_id=score_row.score_id,
                    from_tier=wallet.current_tier,
                    to_tier=new_tier,
                    reason=reason,
                    transitioned_at=now,
                    created_at=now,
                )
            )
            wallet.current_tier = new_tier

        await session.flush()

        return QualificationRunResult(
            wallet_id=wallet_id,
            history_completeness=history_row.history_completeness,
            positions_reconstructed=len(reconstructed),
            positions_unchanged=positions_unchanged,
            positions_written=positions_written,
            positions_skipped_untracked_token=positions_skipped,
            score_written=score_written,
            qualification_score=qualification_score,
            descriptive_score=result.descriptive_score,
            eligible_for_qualification=result.eligible_for_qualification,
            tier_transition=transition,
            current_tier=wallet.current_tier or "DISCOVERED",
        )
