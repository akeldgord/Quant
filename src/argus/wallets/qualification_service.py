"""Phase 3 orchestration: wires history reconstruction, position
reconstruction, the discovery-contamination firewall, scoring,
clustering, and tier lifecycle together into one real service, callable
from a CLI command (`argus wallets reconstruct-and-score`) -- not a
test-only helper (MASTER_SPEC.md Phase 3, `argus-phase-3-001`,
remediated by `argus-phase-3-remediation-001`).

Restart/replay idempotency (this instruction's required test 9): running
this service twice from identical evidence must never insert a duplicate
``wallet_positions``/``wallet_score_snapshots`` row. Each write path here
compares the freshly computed content against the wallet's own latest
existing row of that kind and skips the insert when they match exactly --
``wallet_tier_history`` gets the same property "for free" from
``argus.wallets.tier_lifecycle.determine_tier_transition`` already
returning ``None`` on no change.

**Point-in-time knowledge cutoff (P3-R1)**: ``now`` is this run's
immutable ``as_of``. Every evidence query below is bounded to rows
genuinely knowable by that instant -- ``Swap.first_seen_at <= now``,
``WalletDiscoveryEvent.created_at <= now``, ``EarlyBuyer.created_at <=
now``, ``WalletClusterLink.as_of <= now AND WalletClusterLink.created_at
<= now`` -- so an earlier score snapshot can never be influenced by
evidence ARGUS had not yet observed at that snapshot's own logical
instant. ``reconstruct_positions_for_wallet`` applies its own additional
``as_of`` guard against a malformed/future-dated chain timestamp on an
otherwise-already-known swap (see that module's docstring).
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
from argus.domain.wallet_metrics_snapshots import WalletMetricsSnapshot
from argus.domain.wallet_positions import WalletPosition
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
from argus.domain.wallet_tier_history import WalletTierTransition
from argus.domain.wallets import Wallet
from argus.wallets.acquisition import load_verified_acquisition_manifest
from argus.wallets.clustering import ClusterLinkEvidence, assess_wallet_cluster_risk
from argus.wallets.history_reconstruction import (
    EVIDENCE_OUTCOME_ALREADY_KNOWN_VERIFIED,
    EVIDENCE_OUTCOME_PARSED,
    EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
    assess_wallet_history,
    manifest_as_dict,
)
from argus.wallets.position_reconstruction import (
    ReconstructedPosition,
    reconstruct_positions_for_wallet,
)
from argus.wallets.scoring import (
    WINDOW_DAYS,
    PositionForScoring,
    compute_feature_fingerprint,
    compute_position_stats,
    filter_positions_for_window,
    score_wallet,
)
from argus.wallets.tier_lifecycle import determine_tier_transition

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from argus.config import ArgusConfig
    from argus.wallets.history_reconstruction import (
        AcquisitionManifest,
        EvidenceSource,
        HistoryAssessment,
    )

ALGORITHM_VERSION: Final[str] = "wallet_qualification_service_v2"

# P3-R6: the audit-critical BUILD_HASH must cover every Phase 3 artifact
# whose code can change the decision, not merely this orchestration
# module -- a change to scoring.py's formulas or position_reconstruction.
# py's ledger math is exactly the kind of change this identity exists to
# detect, and a hash of only this file could never see it.
_PHASE3_ARTIFACT_FILENAMES: Final[tuple[str, ...]] = (
    "qualification_service.py",
    "scoring.py",
    "position_reconstruction.py",
    "history_reconstruction.py",
    "tier_lifecycle.py",
    "clustering.py",
    "acquisition.py",
)

_EXCLUSION_REASON_FUTURE_ECONOMIC_TIMESTAMP: Final[str] = "FUTURE_ECONOMIC_TIMESTAMP"

# Matches wallet_score_snapshots.{descriptive_score,qualification_score}'s
# own Numeric(20, 15) column precision exactly (P3-R6b remediation round
# 2) -- see the quantize() call site below for why this must happen
# before persistence, not merely be tolerated by it.
_SCORE_STORAGE_QUANTUM: Final[Decimal] = Decimal("1.000000000000000")

# P3-R2 remediation round 4 (`argus-phase-3-remediation-004`, closing
# audit `argus-phase-3-remediation-audit-003`'s P3-R2a): the set of
# acquired_evidence outcomes that name real, verified, usable derived
# swap rows -- see ``argus.wallets.acquisition.load_verified_acquisition_
# manifest``, which independently re-verifies every entry with one of
# these outcomes against the real chain_events/swaps rows before this
# service ever sees the manifest.
_GENUINE_EVIDENCE_OUTCOMES: Final[frozenset[str]] = frozenset(
    {EVIDENCE_OUTCOME_PARSED, EVIDENCE_OUTCOME_ALREADY_KNOWN_VERIFIED}
)


def _filter_swaps_by_as_of(
    swaps: list[Swap], *, as_of: datetime
) -> tuple[list[Swap], list[dict[str, str]]]:
    """P3-R1 remediation round 2: the ONE shared future-economic-time
    filter applied before history assessment, position reconstruction,
    AND scoring all see the same usable-evidence set -- previously this
    filtering existed only inside ``reconstruct_positions_for_wallet``,
    invisible to ``assess_wallet_history``, and left no persisted
    rejection reason. A swap whose own chain timestamp (``block_time``)
    is later than ``as_of`` is excluded from the usable set (never
    counted as history, never given recency credit) but its raw row is
    never touched -- only recorded here with an explicit reason."""
    usable: list[Swap] = []
    excluded: list[dict[str, str]] = []
    for swap in swaps:
        if swap.block_time is not None and swap.block_time > as_of:
            excluded.append(
                {
                    "swap_id": str(swap.swap_id),
                    "reason": _EXCLUSION_REASON_FUTURE_ECONOMIC_TIMESTAMP,
                }
            )
        else:
            usable.append(swap)
    return usable, excluded


def _compute_build_hash() -> str:
    digest = hashlib.sha256()
    module_dir = Path(__file__).parent
    for filename in _PHASE3_ARTIFACT_FILENAMES:
        digest.update((module_dir / filename).read_bytes())
    return digest.hexdigest()


BUILD_HASH: Final[str] = _compute_build_hash()


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
    runs even when the derived numbers are unchanged. Includes
    ``input_manifest_digest`` (P3-R1/P3-R3): a changed raw-evidence set
    that happens to produce the same totals is still a different
    snapshot, never silently treated as unchanged."""
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
        and a.input_manifest_digest == r.input_manifest_digest
    )


def _history_rows_equal(
    a: WalletHistoryQuality,
    assessment: HistoryAssessment,
    *,
    excluded_evidence: list[dict[str, str]],
) -> bool:
    manifest_dict = (
        manifest_as_dict(assessment.acquisition_manifest)
        if assessment.acquisition_manifest
        else None
    )
    return (
        a.history_start == assessment.history_start
        and a.history_end == assessment.history_end
        and a.history_completeness == assessment.history_completeness
        and a.history_provider_set == assessment.history_provider_set
        and a.history_completeness_reason == assessment.history_completeness_reason
        and a.acquisition_manifest == manifest_dict
        and a.excluded_evidence == excluded_evidence
    )


def _score_equal(
    a: WalletScoreSnapshot,
    *,
    qualification_score: Decimal,
    descriptive_score: Decimal,
    eligible: bool,
    component_values: dict,
    penalties: dict,
    confidence: str | None,
    excluded_discovery_token_ids: list[str],
    sample_gate_reason: str,
    as_of: datetime,
    input_manifest_digest: str,
    history_id: uuid.UUID,
    build_hash: str,
    config_hash: str,
    master_spec_hash: str,
    git_commit: str,
) -> bool:
    """P3-R6: full semantic decision equality -- two runs landing on the
    same final numbers from a genuinely different evidence set, penalty
    mix, confidence, exclusion set, sample-gate reason, as_of, history/
    acquisition identity, or algorithm/build/config/spec/git identity are
    never treated as the same snapshot. ``history_id`` (P3-R6 remediation
    round 2) binds this comparison to the exact, append-only history-
    quality row (and therefore its acquisition manifest/reason/provider/
    boundary/coverage) that justified this score -- a changed history
    reason or manifest always produces a different history_id, so it is
    always caught here even when every other field happens to match."""
    return (
        a.qualification_score == qualification_score
        and a.descriptive_score == descriptive_score
        and a.eligible_for_qualification == eligible
        and a.component_values == component_values
        and a.penalties == penalties
        and a.confidence == confidence
        and a.excluded_discovery_token_ids == excluded_discovery_token_ids
        and a.sample_gate_reason == sample_gate_reason
        and a.as_of == as_of
        and a.input_manifest_digest == input_manifest_digest
        and a.history_id == history_id
        and a.build_hash == build_hash
        and a.config_hash == config_hash
        and a.master_spec_hash == master_spec_hash
        and a.git_commit == git_commit
    )


def _manifest_digest(
    *,
    as_of: datetime,
    swap_ids: list[uuid.UUID],
    excluded_swap_ids: list[str],
    discovery_event_ids: list[uuid.UUID],
    early_buyer_ids: list[uuid.UUID],
    cluster_link_ids: list[uuid.UUID],
) -> str:
    """A stable SHA-256 hex digest binding ``as_of`` to the exact, sorted
    set of raw evidence row identities visible at that knowledge-time
    cutoff (P3-R1/P3-R6) -- "enough stable input references/counts to
    reproduce the score," independent of the derived numbers themselves.
    ``excluded_swap_ids`` (P3-R1 remediation round 2) is part of this
    identity too: a swap newly excluded (or no longer excluded) as
    FUTURE_ECONOMIC_TIMESTAMP is a genuinely different evidence manifest
    even when the usable set's own totals happen to match."""
    parts = [
        as_of.isoformat(),
        ",".join(sorted(str(i) for i in swap_ids)),
        ",".join(sorted(excluded_swap_ids)),
        ",".join(sorted(str(i) for i in discovery_event_ids)),
        ",".join(sorted(str(i) for i in early_buyer_ids)),
        ",".join(sorted(str(i) for i in cluster_link_ids)),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


async def reconstruct_and_score_wallet(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    wallet_address: str,
    evidence_source: EvidenceSource,
    acquisition_run_id: uuid.UUID | None,
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

        # --- 0. real, verified acquisition manifest (P3-R2) -------------
        # Loaded BEFORE the swap query below (P3-R2 remediation round 4,
        # closing audit `argus-phase-3-remediation-audit-003`'s P3-R2a) so
        # LIVE_ACQUISITION_WALK evidence_source can bind the swap set
        # itself to this run's own verified derived evidence, never to
        # every Swap row the wallet happens to have accumulated from any
        # source.
        acquisition_manifest: AcquisitionManifest | None = None
        if evidence_source == EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK:
            if acquisition_run_id is None:
                raise ValueError(
                    "acquisition_run_id is required when evidence_source is "
                    "LIVE_ACQUISITION_WALK -- a real acquisition walk must actually be "
                    "executed and persisted (see 'argus wallets acquire-history') and "
                    "loaded by its verified run_id; an arbitrary caller-supplied manifest "
                    "is never accepted"
                )
            acquisition_manifest = await load_verified_acquisition_manifest(
                session,
                run_id=acquisition_run_id,
                wallet_id=wallet_id,
                wallet_address=wallet_address,
                as_of=now,
            )

        # --- 0b. point-in-time-bounded evidence (P3-R1), bound to this
        # run's own verified evidence for LIVE_ACQUISITION_WALK ----------
        if evidence_source == EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK:
            assert acquisition_manifest is not None  # established above
            # P3-R2 remediation round 4 (required implementation item 2):
            # the exact raw/parser input set USED for reconstruction is
            # this run's own named genuine (PARSED/ALREADY_KNOWN_VERIFIED)
            # derived_swap_id set -- never every Swap row this wallet_
            # address happens to have, which would let an unrelated or
            # differently-scoped run's rows silently enter this run's
            # history/positions/score. A genuinely empty bound set (the
            # wallet legitimately had no usable evidence) still correctly
            # falls through to the zero-evidence UNKNOWN behavior below --
            # it must never be widened back out to "every row."
            bound_swap_ids = {
                uuid.UUID(ev.derived_swap_id)
                for ev in acquisition_manifest.acquired_evidence
                if ev.parser_outcome in _GENUINE_EVIDENCE_OUTCOMES
                and ev.derived_swap_id is not None
            }
            swap_rows: Sequence[Swap] = (
                (
                    (
                        await session.execute(
                            select(Swap).where(
                                Swap.wallet_address == wallet_address,
                                Swap.first_seen_at <= now,
                                Swap.swap_id.in_(bound_swap_ids),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if bound_swap_ids
                else []
            )
        else:
            swap_rows = (
                (
                    await session.execute(
                        select(Swap).where(
                            Swap.wallet_address == wallet_address, Swap.first_seen_at <= now
                        )
                    )
                )
                .scalars()
                .all()
            )
        # ONE shared future-economic-time filter (P3-R1 remediation round
        # 2): history assessment, position reconstruction, and scoring all
        # see the exact same usable-evidence set -- never independently
        # re-filtered, never silently dropped with no persisted reason.
        usable_swaps, excluded_evidence = _filter_swaps_by_as_of(list(swap_rows), as_of=now)

        # --- 1. history completeness -----------------------------------
        assessment = assess_wallet_history(
            usable_swaps,
            wallet_address=wallet_address,
            evidence_source=evidence_source,
            acquisition_manifest=acquisition_manifest,
        )
        # P3-R6b remediation round 2: search ALL of this wallet's history
        # rows for a full content match, never just "the latest row" --
        # the same class of bug the score/position searches had. A
        # wallet's assessed history content is a function of its usable
        # evidence set alone, not of `now` -- so an earlier `now`
        # replayed after a later `now` already ran can legitimately
        # reproduce content identical to an EARLIER row than the most
        # recently created one; comparing only against "latest" would
        # wrongly call that a mismatch, minting a spurious new
        # history_id and, through the history_id binding above,
        # cascading into a spurious duplicate score row too.
        candidate_history_rows = (
            (
                await session.execute(
                    select(WalletHistoryQuality).where(WalletHistoryQuality.wallet_id == wallet_id)
                )
            )
            .scalars()
            .all()
        )
        matching_history = next(
            (
                candidate
                for candidate in candidate_history_rows
                if _history_rows_equal(candidate, assessment, excluded_evidence=excluded_evidence)
            ),
            None,
        )
        if matching_history is not None:
            history_row = matching_history
        else:
            history_row = WalletHistoryQuality(
                history_id=uuid.uuid4(),
                wallet_id=wallet_id,
                history_start=assessment.history_start,
                history_end=assessment.history_end,
                history_provider_set=assessment.history_provider_set,
                history_completeness=assessment.history_completeness,
                history_completeness_reason=assessment.history_completeness_reason,
                acquisition_manifest=(
                    manifest_as_dict(assessment.acquisition_manifest)
                    if assessment.acquisition_manifest
                    else None
                ),
                excluded_evidence=excluded_evidence,
                algorithm_version="history_reconstruction_v2",
                created_at=now,
            )
            session.add(history_row)
            await session.flush()

        # --- 2. discovery-contamination provenance (P3-R1-bounded) ------
        discovery_rows = (
            (
                await session.execute(
                    select(WalletDiscoveryEvent).where(
                        WalletDiscoveryEvent.wallet_id == wallet_id,
                        WalletDiscoveryEvent.created_at <= now,
                    )
                )
            )
            .scalars()
            .all()
        )
        contaminated_token_ids = frozenset(
            str(row.trigger_token_id) for row in discovery_rows if row.trigger_token_id is not None
        )

        # --- 3. position reconstruction ----------------------------------
        reconstructed = reconstruct_positions_for_wallet(usable_swaps, as_of=now)
        early_buyer_rows = (
            (
                await session.execute(
                    select(EarlyBuyer).where(
                        EarlyBuyer.wallet_id == wallet_id, EarlyBuyer.created_at <= now
                    )
                )
            )
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

            # P3-R6b remediation round 2: search ALL rows sharing this
            # (wallet_id, token_id, round_trip_index) key for a full
            # content match, never just "the latest row" -- the same
            # class of bug as the score search above. wallet_positions
            # has no as_of column of its own, so an out-of-order replay
            # (a later, more-complete `now` reconstructed and persisted
            # before an earlier, partial `now` is replayed) can leave the
            # single latest row holding content for a DIFFERENT `now`
            # than the one currently being replayed; comparing only
            # against that row would spuriously insert a THIRD,
            # duplicate row on a subsequent exact re-replay of either
            # `now` instead of finding the row that already matches.
            candidate_positions = (
                (
                    await session.execute(
                        select(WalletPosition).where(
                            WalletPosition.wallet_id == wallet_id,
                            WalletPosition.token_id == token.token_id,
                            WalletPosition.round_trip_index == recon.round_trip_index,
                        )
                    )
                )
                .scalars()
                .all()
            )
            matching_position = next(
                (
                    candidate
                    for candidate in candidate_positions
                    if _positions_equal(candidate, recon)
                ),
                None,
            )

            if matching_position is not None:
                positions_unchanged += 1
            else:
                session.add(
                    WalletPosition(
                        position_id=uuid.uuid4(),
                        wallet_id=wallet_id,
                        token_id=token.token_id,
                        history_id=history_row.history_id,
                        quote_asset_mint=recon.quote_asset_mint or "UNKNOWN",
                        round_trip_index=recon.round_trip_index,
                        input_manifest_digest=recon.input_manifest_digest,
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
                        algorithm_version="position_reconstruction_v2",
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
                    final_exit_at=recon.final_exit_at,
                    quote_asset_mint=recon.quote_asset_mint,
                    round_trip_index=recon.round_trip_index,
                    early_buyer_sequence_number=(
                        early_buyer.sequence_number if early_buyer is not None else None
                    ),
                    possible_deployer=(
                        early_buyer.possible_deployer if early_buyer is not None else False
                    ),
                )
            )
        await session.flush()

        # --- 4. clustering (P3-R1-bounded) ----------------------------
        link_rows = (
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
        raw_result = score_wallet(
            all_positions=positions_for_scoring,
            discovery_contaminated_token_ids=contaminated_token_ids,
            history_completeness=history_row.history_completeness,
            as_of=now,
        )
        # P3-R6: fold every penalty, including cluster uncertainty, into
        # ONE final ScoringResult before persistence and tier evaluation
        # -- the score stored, the score printed, and the score the tier
        # decision reads must be byte-identical, never a locally-adjusted
        # variable the tier logic never sees.
        penalties = dict(raw_result.penalties)
        penalties["cluster_uncertainty_penalty"] = cluster_assessment.cluster_uncertainty_penalty
        adjusted_qualification_score = max(
            Decimal(0),
            raw_result.qualification_score - cluster_assessment.cluster_uncertainty_penalty,
        )
        result = dataclasses.replace(
            raw_result, qualification_score=adjusted_qualification_score, penalties=penalties
        )
        # P3-R6b remediation round 2: quantize to Numeric(20, 15)'s own
        # 15 fractional digits BEFORE this value is used for anything --
        # persistence, the returned QualificationRunResult, or the tier
        # decision. Decimal division's default context computes up to 28
        # significant digits, which can genuinely exceed the column's
        # own precision; Postgres itself quietly rounds to 15 fractional
        # digits on INSERT, so an in-memory value left unrounded would
        # silently diverge from what a later read of the very same row
        # returns -- "stored/returned/tier-used exactly" requires this
        # value to be identical everywhere it is used, not merely
        # internally self-consistent within this one run.
        result = dataclasses.replace(
            result,
            qualification_score=result.qualification_score.quantize(_SCORE_STORAGE_QUANTUM),
            descriptive_score=result.descriptive_score.quantize(_SCORE_STORAGE_QUANTUM),
        )

        component_values_json = {
            k: (str(v) if v is not None else None) for k, v in result.component_values.items()
        }
        penalties_json = {k: str(v) for k, v in result.penalties.items()}
        excluded_ids_sorted = sorted(contaminated_token_ids)
        input_manifest_digest = _manifest_digest(
            as_of=now,
            swap_ids=[s.swap_id for s in usable_swaps],
            excluded_swap_ids=[e["swap_id"] for e in excluded_evidence],
            discovery_event_ids=[r.discovery_event_id for r in discovery_rows],
            early_buyer_ids=[r.early_buyer_id for r in early_buyer_rows],
            cluster_link_ids=[link.link_id for link in link_rows],
        )

        # P3-R6b remediation round 2: search for an EXISTING row with the
        # full semantic decision identity, never just "the latest row" --
        # the latest row can belong to a chronologically later as_of (a
        # score computed for T after T+delta already exists), which must
        # never be mistaken for -- or overwritten by -- a replay of T.
        # Scoped to this exact as_of since as_of is itself part of the
        # semantic identity; two rows can never be a full match across
        # different as_of values.
        candidate_scores = (
            (
                await session.execute(
                    select(WalletScoreSnapshot).where(
                        WalletScoreSnapshot.wallet_id == wallet_id,
                        WalletScoreSnapshot.as_of == now,
                    )
                )
            )
            .scalars()
            .all()
        )
        matching_score = next(
            (
                candidate
                for candidate in candidate_scores
                if _score_equal(
                    candidate,
                    qualification_score=result.qualification_score,
                    descriptive_score=result.descriptive_score,
                    eligible=result.eligible_for_qualification,
                    component_values=component_values_json,
                    penalties=penalties_json,
                    confidence=result.confidence,
                    excluded_discovery_token_ids=excluded_ids_sorted,
                    sample_gate_reason=result.sample_gate_reason,
                    as_of=now,
                    input_manifest_digest=input_manifest_digest,
                    history_id=history_row.history_id,
                    build_hash=BUILD_HASH,
                    config_hash=config.config_hash,
                    master_spec_hash=config.spec_hash,
                    git_commit=git_commit,
                )
            ),
            None,
        )

        score_written = False
        if matching_score is not None:
            score_row = matching_score
        else:
            score_row = WalletScoreSnapshot(
                score_id=uuid.uuid4(),
                wallet_id=wallet_id,
                as_of=now,
                score_version="qualification_score_v1",
                descriptive_score=result.descriptive_score,
                qualification_score=result.qualification_score,
                component_values=component_values_json,
                penalties=penalties_json,
                confidence=result.confidence,
                excluded_discovery_token_ids=excluded_ids_sorted,
                eligible_for_qualification=result.eligible_for_qualification,
                sample_gate_reason=result.sample_gate_reason,
                input_manifest_digest=input_manifest_digest,
                history_id=history_row.history_id,
                build_hash=BUILD_HASH,
                config_hash=config.config_hash,
                master_spec_hash=config.spec_hash,
                git_commit=git_commit,
                created_at=now,
            )
            session.add(score_row)
            await session.flush()
            score_written = True

        # --- 5b. all five recency-window metric snapshots (P3-R4) -------
        qualifying_for_windows = [
            p
            for p in positions_for_scoring
            if p.token_id not in contaminated_token_ids and p.confidence in ("HIGH", "MEDIUM")
        ]
        for window_name, window_days in WINDOW_DAYS.items():
            if window_days is None:
                window_stats = result.stats
                window_fingerprint = result.fingerprint
            else:
                windowed_positions = filter_positions_for_window(
                    qualifying_for_windows, as_of=now, window_days=window_days
                )
                window_stats = compute_position_stats(windowed_positions)
                window_fingerprint = compute_feature_fingerprint(
                    windowed_positions, window_stats, as_of=now, robust=True
                )
            session.add(
                WalletMetricsSnapshot(
                    snapshot_id=uuid.uuid4(),
                    wallet_id=wallet_id,
                    as_of=now,
                    metrics_window=window_name,
                    selection_skill=window_fingerprint.selection_skill,
                    early_discovery_skill=window_fingerprint.early_discovery_skill,
                    entry_timing_skill=window_fingerprint.entry_timing_skill,
                    exit_skill=window_fingerprint.exit_skill,
                    risk_control_skill=window_fingerprint.risk_control_skill,
                    consistency=window_fingerprint.consistency,
                    copyability=window_fingerprint.copyability,
                    forward_information_value=window_fingerprint.forward_information_value,
                    recency=window_fingerprint.recency,
                    data_confidence=window_fingerprint.data_confidence,
                    insider_risk=window_fingerprint.insider_risk,
                    cluster_risk=cluster_assessment.cluster_risk,
                    independence_probability=cluster_assessment.independence_probability,
                    predation_risk=None,
                    automation_probability=None,
                    median_return=window_stats.median_return,
                    trimmed_mean_return=window_stats.trimmed_mean_return,
                    winsorized_return=window_stats.winsorized_return,
                    profit_factor=window_stats.profit_factor,
                    hit_rate=window_stats.hit_rate,
                    largest_trade_contribution_pct=window_stats.largest_trade_contribution_pct,
                    top_three_trade_contribution_pct=window_stats.top_three_trade_contribution_pct,
                    max_drawdown=window_stats.max_drawdown,
                    distinct_profitable_token_count=window_stats.distinct_profitable_token_count,
                    lottery_dominated=window_stats.lottery_dominated,
                    usable_closed_positions_count=window_stats.closed_count,
                    distinct_tokens_with_usable_outcomes_count=window_stats.distinct_tokens,
                    algorithm_version="wallet_scoring_v1",
                    git_commit=git_commit,
                    created_at=now,
                )
            )

        # --- 6. tier lifecycle -----------------------------------------
        # P3-R6b remediation round 2: the FROM tier for this decision is
        # the tier that was actually in effect AS OF `now` -- the latest
        # transition with transitioned_at <= now -- never
        # wallet.current_tier, which is the wallet's global latest state
        # and can belong to a chronologically LATER as_of than this run's
        # own `now` (a historical replay after a later decision already
        # exists must never read the future as if it were the past).
        tier_as_of_now_row = (
            await session.execute(
                select(WalletTierTransition)
                .where(
                    WalletTierTransition.wallet_id == wallet_id,
                    WalletTierTransition.transitioned_at <= now,
                )
                .order_by(WalletTierTransition.transitioned_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        current_tier_as_of_now = (
            tier_as_of_now_row.to_tier if tier_as_of_now_row is not None else None
        )
        latest_transitioned_at = (
            await session.execute(
                select(WalletTierTransition.transitioned_at)
                .where(WalletTierTransition.wallet_id == wallet_id)
                .order_by(WalletTierTransition.transitioned_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        transition = determine_tier_transition(
            current_tier=current_tier_as_of_now,
            scoring=result,
            insider_risk=result.fingerprint.insider_risk,
            cluster_risk=cluster_assessment.cluster_risk,
        )
        resolved_tier = current_tier_as_of_now or "DISCOVERED"
        if transition is not None:
            new_tier, reason = transition
            resolved_tier = new_tier
            # Exact-replay guard: a transition already recorded for this
            # exact score row means this exact decision was already made
            # -- never append a second transition or re-touch the
            # denormalized cache for an identical replay.
            existing_transition_for_score = (
                await session.execute(
                    select(WalletTierTransition.transition_id)
                    .where(WalletTierTransition.source_score_id == score_row.score_id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing_transition_for_score is not None:
                transition = None
            else:
                session.add(
                    WalletTierTransition(
                        transition_id=uuid.uuid4(),
                        wallet_id=wallet_id,
                        source_score_id=score_row.score_id,
                        from_tier=current_tier_as_of_now,
                        to_tier=new_tier,
                        reason=reason,
                        transitioned_at=now,
                        created_at=now,
                    )
                )
                # Only advance the denormalized "current" cache when this
                # decision is not chronologically superseded by an
                # already-recorded later transition -- a historical
                # analysis may append its own immutable transition row,
                # but must never overwrite a later current-tier state.
                if latest_transitioned_at is None or now >= latest_transitioned_at:
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
            qualification_score=result.qualification_score,
            descriptive_score=result.descriptive_score,
            eligible_for_qualification=result.eligible_for_qualification,
            tier_transition=transition,
            current_tier=resolved_tier,
        )
