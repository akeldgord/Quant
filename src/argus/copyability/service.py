"""Phase 5 orchestration: ties the M1-M7 pure mechanics and the production
loaders together into one wallet-level copyability computation, and
persists it idempotently (P5-09). This is the one place all of Phase 5's
per-wallet analytics are assembled -- ``argus copyability report`` (the
CLI command required by P5-10) calls this for each tracked wallet.

Interpretation note on the forward-information grid (section 51's nine
fixed horizons 5s/15s/30s/60s/5m/30m/1h/6h/24h, all measured from
``first_seen_at``): Phase 4's schema only ever produces two families of
delay-labeled evidence relative to ``first_seen_at`` -- ``ENTRY_DELAY``
probes at 1s/5s/15s/30s/60s/300s (i.e. up to 5m), and
``REVERSE_EXECUTABLE`` holding-horizon probes at 5m/30m/1h/6h/24h (each
relative to its own position's entry, not to a fixed additional delay).
This module maps the grid's 5s/15s/30s/60s/5m cells onto the entry-delay
curve built by :mod:`argus.copyability.delay_curves` (the same evidence
M3's half-life computation uses), and maps 30m/1h/6h/24h onto the median
REVERSE_EXECUTABLE return across all positions' own holding-horizon
probes at that label -- the closest honest reading of "remaining
information value at a given delay from first observation" that Phase
4's actual evidence supports. This is documented explicitly, never
silently assumed.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from argus.copyability.delay_curves import (
    DelayPoint,
    ForwardInfoCell,
    HalfLifeResult,
    build_delay_curve,
    build_forward_information_grid,
    compute_half_life,
    decimal_median,
)
from argus.copyability.executable_returns import EntryFill, ReverseQuote, compute_executable_return
from argus.copyability.identity import (
    evidence_manifest_digest,
)
from argus.copyability.loaders import (
    build_delay_observations_for_curve,
    load_contamination_firewall,
    load_prior_buy_sizes,
    load_wallet_shadow_positions,
)
from argus.copyability.persistence import get_or_create_wallet_copyability_snapshot
from argus.copyability.size_surprise import (
    SizeSurpriseInput,
    SizeSurpriseResult,
    compute_size_surprise,
)
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.wallet_copyability_snapshots import WalletCopyabilitySnapshot
from argus.domain.wallets import Wallet
from argus.scoring.copyability import CopyabilityInputs, CopyabilityResult, compute_copyability

ALGORITHM_VERSION = "copyability_v1"

# Same "hash every artifact whose code can change the decision" pattern
# Phase 3's qualification_service.BUILD_HASH established -- covers every
# Phase 5 module able to change a copyability output.
_PHASE5_ARTIFACT_RELATIVE_PATHS: Final[tuple[str, ...]] = (
    "identity.py",
    "executable_returns.py",
    "delay_curves.py",
    "size_surprise.py",
    "util.py",
    "loaders.py",
    "persistence.py",
    "service.py",
)
_SCORING_ARTIFACT_FILENAMES: Final[tuple[str, ...]] = (
    "copyability.py",
    "readiness.py",
    "config_weights.py",
)


def _compute_build_hash() -> str:
    digest = hashlib.sha256()
    module_dir = Path(__file__).parent
    scoring_dir = module_dir.parent / "scoring"
    for filename in _PHASE5_ARTIFACT_RELATIVE_PATHS:
        digest.update((module_dir / filename).read_bytes())
    for filename in _SCORING_ARTIFACT_FILENAMES:
        digest.update((scoring_dir / filename).read_bytes())
    return digest.hexdigest()


BUILD_HASH: Final[str] = _compute_build_hash()

_ENTRY_DELAY_TO_GRID_LABEL = {
    "1s": None,
    "5s": "5s",
    "15s": "15s",
    "30s": "30s",
    "60s": "60s",
    "300s": "5m",
}
_LONG_HORIZON_GRID_LABELS = ("30m", "1h", "6h", "24h")


@dataclass(frozen=True)
class WalletCopyabilityComputation:
    delay_points: list[DelayPoint]
    forward_information_grid: dict
    half_life: HalfLifeResult
    size_surprise: SizeSurpriseResult
    copyability: CopyabilityResult
    contributing_source_ids: list
    excluded_source_ids: list
    evidence_manifest_digest: str


async def compute_wallet_copyability(
    session: AsyncSession,
    *,
    wallet: Wallet,
    as_of: datetime,
    weights: dict[str, Decimal],
    current_size: Decimal | None = None,
    quote_mint: str = "So11111111111111111111111111111111111111112",
) -> WalletCopyabilityComputation:
    firewall = await load_contamination_firewall(session, wallet_id=wallet.wallet_id)
    shadow_evidence = await load_wallet_shadow_positions(
        session, wallet_id=wallet.wallet_id, cutoff=as_of, firewall=firewall
    )

    curve_observations = build_delay_observations_for_curve(shadow_evidence.delay_observations)
    delay_points = build_delay_curve(curve_observations)
    half_life = compute_half_life(delay_points)

    points_by_label = {p.target_label: p for p in delay_points}
    grid_cells: dict[str, ForwardInfoCell] = {}
    for entry_label, grid_label in _ENTRY_DELAY_TO_GRID_LABEL.items():
        if grid_label is None:
            continue
        point = points_by_label.get(entry_label)
        if point is None:
            continue
        grid_cells[grid_label] = ForwardInfoCell(
            available=True, return_fraction=point.median_return_fraction, is_executable=True
        )

    long_horizon_returns = await _load_long_horizon_returns(
        session, wallet_id=wallet.wallet_id, cutoff=as_of, firewall=firewall
    )
    for label in _LONG_HORIZON_GRID_LABELS:
        fractions = long_horizon_returns.get(label, [])
        if fractions:
            grid_cells[label] = ForwardInfoCell(
                available=True, return_fraction=decimal_median(fractions), is_executable=True
            )

    forward_information_grid = build_forward_information_grid(grid_cells)

    prior_buys = await load_prior_buy_sizes(
        session,
        wallet_address=wallet.wallet_address,
        quote_mint=quote_mint,
        signal_at=as_of,
        cutoff=as_of,
        firewall=firewall,
        token_id_by_mint={},
    )
    size_surprise = compute_size_surprise(
        SizeSurpriseInput(prior_sizes=prior_buys.sizes, current_size=current_size or Decimal(0))
    )

    primary_returns = [
        obs.executable_return_fraction
        for obs in shadow_evidence.delay_observations
        if obs.status == "SUCCESS" and obs.executable_return_fraction is not None
    ]
    follower_alpha_median = decimal_median(primary_returns) if primary_returns else None

    successful_terminal = [
        obs for obs in shadow_evidence.delay_observations if obs.status in ("SUCCESS", "FAILED")
    ]
    successful_count = sum(1 for obs in successful_terminal if obs.status == "SUCCESS")

    per_event_stability = tuple(
        Decimal(1)
        if (
            obs.status == "SUCCESS"
            and obs.executable_return_fraction is not None
            and obs.executable_return_fraction >= 0
        )
        else Decimal(0)
        for obs in shadow_evidence.delay_observations
        if obs.status == "SUCCESS"
    )

    positive_peak = (
        half_life.peak_return_fraction
        if half_life.outcome == "PEAK_FOUND" or half_life.outcome == "RIGHT_CENSORED"
        else None
    )
    latest_label = max(delay_points, key=lambda p: p.target_seconds) if delay_points else None
    latest_return = latest_label.median_return_fraction if latest_label else None

    copyability_inputs = CopyabilityInputs(
        follower_alpha_median_return_fraction=follower_alpha_median,
        successful_qty_matched_reverse_count=successful_count,
        all_terminal_reverse_count=len(successful_terminal),
        per_event_stability_fractions=per_event_stability,
        comparable_pairs_5m_le_30m_count=0,
        comparable_pairs_total=0,
        positive_peak_return_fraction=positive_peak,
        latest_comparable_delay_return_fraction=latest_return,
        adequate_comparable_evidence=len(delay_points) >= 2,
        mean_abs_price_impact_fraction=None,
        n_events=len(primary_returns),
        k_distinct_tokens=len(
            {obs.token_id for obs in shadow_evidence.delay_observations if obs.token_id is not None}
        ),
        coverage_numerator=successful_count,
        coverage_denominator=len(shadow_evidence.delay_observations) or 0,
        history_completeness="UNKNOWN",
    )
    copyability = compute_copyability(copyability_inputs, weights=weights)

    all_contributing = list(shadow_evidence.contributing) + list(prior_buys.contributing)
    all_excluded = list(shadow_evidence.excluded) + list(prior_buys.excluded)
    digest = evidence_manifest_digest(all_contributing)

    return WalletCopyabilityComputation(
        delay_points=delay_points,
        forward_information_grid=forward_information_grid,
        half_life=half_life,
        size_surprise=size_surprise,
        copyability=copyability,
        contributing_source_ids=[ref.as_dict() for ref in all_contributing],
        excluded_source_ids=[ref.as_dict() for ref in all_excluded],
        evidence_manifest_digest=digest,
    )


async def _load_long_horizon_returns(
    session: AsyncSession, *, wallet_id: uuid.UUID, cutoff: datetime, firewall
) -> dict[str, list[Decimal]]:
    from sqlalchemy import select

    from argus.domain.shadow_quote_probes import (
        PROBE_KIND_REVERSE_EXECUTABLE,
        ShadowQuoteProbe,
    )

    positions = (
        (
            await session.execute(
                select(ShadowPosition).where(
                    ShadowPosition.wallet_id == wallet_id, ShadowPosition.created_at <= cutoff
                )
            )
        )
        .scalars()
        .all()
    )
    results: dict[str, list[Decimal]] = {label: [] for label in _LONG_HORIZON_GRID_LABELS}
    for position in positions:
        if firewall.is_contaminated(position.token_id):
            continue
        probes = (
            (
                await session.execute(
                    select(ShadowQuoteProbe).where(
                        ShadowQuoteProbe.shadow_position_id == position.shadow_position_id,
                        ShadowQuoteProbe.probe_kind == PROBE_KIND_REVERSE_EXECUTABLE,
                        ShadowQuoteProbe.target_label.in_(_LONG_HORIZON_GRID_LABELS),
                    )
                )
            )
            .scalars()
            .all()
        )
        for probe in probes:
            if probe.terminal_at is None or probe.terminal_at > cutoff:
                continue
            entry = EntryFill(
                input_mint=position.input_mint,
                output_mint=position.output_mint,
                input_amount_raw=position.entry_input_amount_raw,
                output_amount_raw=position.entry_output_amount_raw,
            )
            reverse = ReverseQuote(
                outcome=probe.outcome,
                input_mint=probe.input_mint,
                output_mint=probe.output_mint,
                input_amount_raw=probe.notional_input_amount_raw,
                output_amount_raw=probe.expected_output_amount_raw,
            )
            result = compute_executable_return(entry, reverse)
            if result.status == "SUCCESS" and result.gross_return_fraction is not None:
                results[probe.target_label].append(result.gross_return_fraction)
    return results


def build_snapshot_row(
    *,
    wallet: Wallet,
    as_of: datetime,
    computation: WalletCopyabilityComputation,
    weights: dict[str, Decimal],
    build_hash: str,
    config_hash: str,
    master_spec_hash: str,
    git_commit: str,
    computed_at: datetime,
) -> WalletCopyabilitySnapshot:
    cop = computation.copyability
    return WalletCopyabilitySnapshot(
        snapshot_id=uuid.uuid4(),
        wallet_id=wallet.wallet_id,
        as_of=as_of,
        algorithm_version=ALGORITHM_VERSION,
        contributing_source_ids=computation.contributing_source_ids,
        excluded_source_ids=computation.excluded_source_ids,
        evidence_manifest_digest=computation.evidence_manifest_digest,
        delay_curve={
            p.target_label: {
                "target_seconds": p.target_seconds,
                "median_return_fraction": str(p.median_return_fraction),
                "n": p.n,
                "event_ids": list(p.event_ids),
            }
            for p in computation.delay_points
        },
        half_life_result={
            "outcome": computation.half_life.outcome,
            "peak_target_label": computation.half_life.peak_target_label,
            "peak_seconds": computation.half_life.peak_seconds,
            "peak_return_fraction": (
                str(computation.half_life.peak_return_fraction)
                if computation.half_life.peak_return_fraction is not None
                else None
            ),
            "crossing_target_label": computation.half_life.crossing_target_label,
            "crossing_seconds": computation.half_life.crossing_seconds,
            "half_life_seconds": (
                str(computation.half_life.half_life_seconds)
                if computation.half_life.half_life_seconds is not None
                else None
            ),
            "reason": computation.half_life.reason,
        },
        forward_information_grid=computation.forward_information_grid,
        size_surprise={
            "baseline_count": computation.size_surprise.baseline_count,
            "median": str(computation.size_surprise.median)
            if computation.size_surprise.median is not None
            else None,
            "mad": str(computation.size_surprise.mad)
            if computation.size_surprise.mad is not None
            else None,
            "z": str(computation.size_surprise.z)
            if computation.size_surprise.z is not None
            else None,
            "component": str(computation.size_surprise.component)
            if computation.size_surprise.component is not None
            else None,
            "unavailable_reason": computation.size_surprise.unavailable_reason,
        },
        copyability_score=cop.score,
        copyability_components={
            key: comp.as_dict(weight=weights.get(key, Decimal(0)))
            for key, comp in cop.components.items()
        },
        available_weight=cop.available_weight,
        sample_n=cop.sample_n,
        sample_k=cop.sample_k,
        sample_coverage=cop.sample_coverage,
        sample_c=cop.sample_c,
        confidence=cop.confidence,
        descriptive_extras={},
        build_hash=build_hash,
        config_hash=config_hash,
        master_spec_hash=master_spec_hash,
        git_commit=git_commit,
        computed_at=computed_at,
    )


async def compute_and_persist_wallet_copyability(
    session: AsyncSession,
    *,
    wallet: Wallet,
    as_of: datetime,
    weights: dict[str, Decimal],
    build_hash: str,
    config_hash: str,
    master_spec_hash: str,
    git_commit: str,
    computed_at: datetime,
    current_size: Decimal | None = None,
) -> tuple[WalletCopyabilitySnapshot, bool]:
    computation = await compute_wallet_copyability(
        session, wallet=wallet, as_of=as_of, weights=weights, current_size=current_size
    )

    def _build() -> WalletCopyabilitySnapshot:
        return build_snapshot_row(
            wallet=wallet,
            as_of=as_of,
            computation=computation,
            weights=weights,
            build_hash=build_hash,
            config_hash=config_hash,
            master_spec_hash=master_spec_hash,
            git_commit=git_commit,
            computed_at=computed_at,
        )

    return await get_or_create_wallet_copyability_snapshot(
        session,
        wallet_id=wallet.wallet_id,
        as_of=as_of,
        algorithm_version=ALGORITHM_VERSION,
        evidence_manifest_digest=computation.evidence_manifest_digest,
        build_row=_build,
    )
