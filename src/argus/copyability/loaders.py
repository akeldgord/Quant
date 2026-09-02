"""Production, point-in-time-safe evidence loaders for Phase 5
(``argus-phase-5-001``) -- the "real production loader, not hand-built
feature objects" P5-01 requires. Every function here queries the existing
Phase 1/3/4 tables directly (``swaps``, ``wallet_discovery_events``,
``shadow_intents``/``shadow_positions``/``shadow_quote_probes``/
``shadow_mark_outcomes``, ``prospective_events``) and applies the M1
point-in-time cutoff and the M7 discovery-contamination firewall
uniformly, so every Phase 5 mechanic sees the same honestly-filtered
evidence.

Every row emitted by these loaders from real tables is
``EVIDENCE_CLASS_AUTHENTIC_PROSPECTIVE`` -- Phase 4's own REPLAY isolation
(P4-R7) means these production tables never carry REPLAY data; a test may
still construct HISTORICAL/SYNTHETIC/REPLAY inputs directly against the
pure M2-M6 functions without going through this module at all (M7's own
"HISTORICAL/REPLAY/SYNTHETIC can never become AUTHENTIC_PROSPECTIVE via
filename/report-mode/later import" rule -- this module is the one place
that label is ever assigned to real evidence, and it is never assigned to
anything but genuine production rows).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.copyability.delay_curves import DelayObservation
from argus.copyability.executable_returns import (
    EntryFill,
    ReverseQuote,
    compute_executable_return,
)
from argus.copyability.identity import (
    REASON_DISCOVERY_CONTAMINATED,
    REASON_FUTURE_KNOWLEDGE,
    ExcludedSourceRef,
    SourceRef,
)
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    PROBE_KIND_REVERSE_EXECUTABLE,
    ShadowQuoteProbe,
)
from argus.domain.swaps import Swap
from argus.domain.wallet_discovery_events import WalletDiscoveryEvent

PRIMARY_EXECUTABLE_HORIZON = "5m"
SIZE_SURPRISE_WINDOW_DAYS = 90
SIZE_SURPRISE_MAX_PRIOR = 100

# Classifications the parser marks as unambiguous swaps (never
# TRANSFER_IN/TRANSFER_OUT/TOKEN_CREATE/LP_ACTION/UNKNOWN) -- the same
# eligibility boundary Phase 3's position reconstruction already applies.
_UNAMBIGUOUS_SWAP_CLASSIFICATIONS = ("SWAP_SIMPLE", "SWAP_COMPLEX")


@dataclass(frozen=True)
class ContaminationFirewall:
    """A wallet's contaminated token set, per M7 -- derived from real
    persisted ``wallet_discovery_events`` provenance, never a caller's
    optional manual list."""

    contaminated_token_ids: frozenset[uuid.UUID]

    def is_contaminated(self, token_id: uuid.UUID | None) -> bool:
        return token_id is not None and token_id in self.contaminated_token_ids


async def load_contamination_firewall(
    session: AsyncSession, *, wallet_id: uuid.UUID
) -> ContaminationFirewall:
    rows = (
        await session.execute(
            select(WalletDiscoveryEvent.trigger_token_id).where(
                WalletDiscoveryEvent.wallet_id == wallet_id,
                WalletDiscoveryEvent.trigger_token_id.is_not(None),
            )
        )
    ).scalars()
    return ContaminationFirewall(
        contaminated_token_ids=frozenset(token_id for token_id in rows if token_id is not None)
    )


@dataclass(frozen=True)
class PriorBuyLoadResult:
    sizes: list[Decimal]
    contributing: list[SourceRef]
    excluded: list[ExcludedSourceRef]


async def load_prior_buy_sizes(
    session: AsyncSession,
    *,
    wallet_address: str,
    quote_mint: str,
    signal_at: datetime,
    cutoff: datetime,
    firewall: ContaminationFirewall,
    token_id_by_mint: dict[str, uuid.UUID | None],
    current_swap_id: uuid.UUID | None = None,
) -> PriorBuyLoadResult:
    """M4's baseline: the wallet's own last <=100 known positive buy
    notionals in ``quote_mint``, strictly during the 90 days before
    ``signal_at``, excluding the current buy, anything not yet known by
    ``cutoff`` (``first_seen_at > cutoff``), and anything whose acquired
    token is discovery-contaminated for this wallet (M7)."""
    window_start = signal_at - timedelta(days=SIZE_SURPRISE_WINDOW_DAYS)
    rows = (
        (
            await session.execute(
                select(Swap)
                .where(
                    Swap.wallet_address == wallet_address,
                    Swap.classification.in_(_UNAMBIGUOUS_SWAP_CLASSIFICATIONS),
                    Swap.input_mint == quote_mint,
                    Swap.output_mint.is_not(None),
                    Swap.output_mint != quote_mint,
                    Swap.input_amount_ui.is_not(None),
                    Swap.input_amount_ui > 0,
                    Swap.first_seen_at < signal_at,
                    Swap.first_seen_at >= window_start,
                )
                .order_by(Swap.first_seen_at.asc())
            )
        )
        .scalars()
        .all()
    )

    contributing: list[SourceRef] = []
    excluded: list[ExcludedSourceRef] = []
    sizes: list[Decimal] = []
    seen_swap_ids: set[uuid.UUID] = set()
    for row in rows:
        ref = SourceRef("swap", str(row.swap_id))
        if row.swap_id == current_swap_id:
            continue  # the current buy itself, excluded structurally (not a "prior" buy)
        if row.swap_id in seen_swap_ids:
            excluded.append(ExcludedSourceRef(ref, "DUPLICATE_EVENT"))
            continue
        if row.first_seen_at is None or row.first_seen_at > cutoff:
            excluded.append(ExcludedSourceRef(ref, REASON_FUTURE_KNOWLEDGE))
            continue
        token_id = token_id_by_mint.get(row.output_mint) if row.output_mint else None
        if firewall.is_contaminated(token_id):
            excluded.append(ExcludedSourceRef(ref, REASON_DISCOVERY_CONTAMINATED))
            continue
        if row.input_amount_ui is None:
            excluded.append(ExcludedSourceRef(ref, "MISSING_UI_AMOUNT"))
            continue
        seen_swap_ids.add(row.swap_id)
        contributing.append(ref)
        sizes.append(row.input_amount_ui)

    # Most recent <= 100, chronological ascending (M4's own contract).
    if len(sizes) > SIZE_SURPRISE_MAX_PRIOR:
        sizes = sizes[-SIZE_SURPRISE_MAX_PRIOR:]
        contributing = contributing[-SIZE_SURPRISE_MAX_PRIOR:]

    return PriorBuyLoadResult(sizes=sizes, contributing=contributing, excluded=excluded)


@dataclass(frozen=True)
class EventDelayObservation:
    """One event's realized primary-horizon executable return at whatever
    entry-delay label its single ShadowPosition actually filled at (the
    "important current data limitation" -- exactly one ShadowPosition per
    intent, at the first successful entry probe -- means the delay curve
    is built cross-sectionally across events, never within one event)."""

    shadow_position_id: uuid.UUID
    token_id: uuid.UUID | None
    target_label: str
    target_seconds: int
    executable_return_fraction: Decimal | None
    status: str


@dataclass(frozen=True)
class WalletShadowEvidence:
    delay_observations: list[EventDelayObservation]
    contributing: list[SourceRef]
    excluded: list[ExcludedSourceRef]


async def load_wallet_shadow_positions(
    session: AsyncSession,
    *,
    wallet_id: uuid.UUID,
    cutoff: datetime,
    firewall: ContaminationFirewall,
    horizon_label: str = PRIMARY_EXECUTABLE_HORIZON,
) -> WalletShadowEvidence:
    """Loads every known-by-``cutoff`` ``ShadowPosition`` for this wallet
    plus its ``REVERSE_EXECUTABLE`` probe at ``horizon_label``, and
    computes the resulting executable return via M2 -- the single primary
    data path every Phase 5 mechanic that needs an executable-return
    observation shares."""
    positions = (
        (
            await session.execute(
                select(ShadowPosition).where(
                    ShadowPosition.wallet_id == wallet_id,
                    ShadowPosition.created_at <= cutoff,
                )
            )
        )
        .scalars()
        .all()
    )

    contributing: list[SourceRef] = []
    excluded: list[ExcludedSourceRef] = []
    observations: list[EventDelayObservation] = []

    for position in positions:
        pos_ref = SourceRef("shadow_position", str(position.shadow_position_id))
        if firewall.is_contaminated(position.token_id):
            excluded.append(ExcludedSourceRef(pos_ref, REASON_DISCOVERY_CONTAMINATED))
            continue

        probe = (
            await session.execute(
                select(ShadowQuoteProbe).where(
                    ShadowQuoteProbe.shadow_position_id == position.shadow_position_id,
                    ShadowQuoteProbe.probe_kind == PROBE_KIND_REVERSE_EXECUTABLE,
                    ShadowQuoteProbe.target_label == horizon_label,
                )
            )
        ).scalar_one_or_none()

        if probe is None or probe.terminal_at is None or probe.terminal_at > cutoff:
            excluded.append(ExcludedSourceRef(pos_ref, "REVERSE_QUOTE_NOT_YET_TERMINAL_BY_CUTOFF"))
            continue

        contributing.append(pos_ref)
        contributing.append(SourceRef("shadow_quote_probe", str(probe.probe_id)))

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

        target_seconds = _entry_delay_seconds(position.entry_probe_target_label)
        observations.append(
            EventDelayObservation(
                shadow_position_id=position.shadow_position_id,
                token_id=position.token_id,
                target_label=position.entry_probe_target_label,
                target_seconds=target_seconds,
                executable_return_fraction=result.gross_return_fraction,
                status=result.status,
            )
        )

    return WalletShadowEvidence(
        delay_observations=observations, contributing=contributing, excluded=excluded
    )


def _entry_delay_seconds(label: str) -> int:
    """ "1s".."300s" -> integer seconds; entry-delay labels are always
    plain second counts (``config/signals_v1.yaml``'s
    ``copyability_delay_probes_seconds``)."""
    if label.endswith("s"):
        return int(label[:-1])
    raise ValueError(f"unrecognized entry-delay target label: {label!r}")


def build_delay_observations_for_curve(
    events: list[EventDelayObservation],
) -> list[DelayObservation]:
    """Reduces to distinct-event executable-return observations for
    :func:`argus.copyability.delay_curves.build_delay_curve` -- only
    genuinely SUCCESS-status returns contribute (failures/pending never
    fabricate a return fraction)."""
    return [
        DelayObservation(
            event_id=str(event.shadow_position_id),
            target_label=event.target_label,
            target_seconds=event.target_seconds,
            return_fraction=event.executable_return_fraction,
        )
        for event in events
        if event.status == "SUCCESS" and event.executable_return_fraction is not None
    ]


__all__ = [
    "PRIMARY_EXECUTABLE_HORIZON",
    "ContaminationFirewall",
    "load_contamination_firewall",
    "PriorBuyLoadResult",
    "load_prior_buy_sizes",
    "EventDelayObservation",
    "WalletShadowEvidence",
    "load_wallet_shadow_positions",
    "build_delay_observations_for_curve",
]
