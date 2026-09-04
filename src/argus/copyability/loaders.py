"""Production, point-in-time-safe evidence loaders for Phase 5
(``argus-phase-5-001``, remediated per ``argus-phase-5-remediation-001``)
-- the "real production loader, not hand-built feature objects" P5-01
requires. Every function here queries the existing Phase 1/3/4 tables
directly (``swaps``, ``tokens``, ``wallet_discovery_events``,
``prospective_events``, ``shadow_intents``/``shadow_positions``/
``shadow_quote_probes``) and applies the M1 point-in-time cutoff and the
M7 discovery-contamination firewall uniformly, so every Phase 5 mechanic
sees the same honestly-filtered evidence.

Every row emitted by these loaders from real tables is
``EVIDENCE_CLASS_AUTHENTIC_PROSPECTIVE`` -- Phase 4's own REPLAY isolation
(P4-R7) means these production tables never carry REPLAY data; a test may
still construct HISTORICAL/SYNTHETIC/REPLAY inputs directly against the
pure M2-M6 functions without going through this module at all (M7's own
"HISTORICAL/REPLAY/SYNTHETIC can never become AUTHENTIC_PROSPECTIVE via
filename/report-mode/later import" rule -- this module is the one place
that label is ever assigned to real evidence, and it is never assigned to
anything but genuine production rows).

F5-01/F5-02/F5-03 remediation (``argus-phase-5-remediation-001``): the
central evidence-assembly primitive is now :func:`load_wallet_opportunities`
-- ONE row per :class:`~argus.domain.shadow_intents.ShadowIntent` (an
"eligible terminal entry-event opportunity", including entry failures with
no position at all), carrying the real ``first_seen_at`` from its
:class:`~argus.domain.prospective_events.ProspectiveEvent`, every
known-by-cutoff ``REVERSE_EXECUTABLE`` probe's real actual timings, and
every timestamp (probe ``created_at``/``requested_at``/``responded_at``/
``terminal_at``, not merely ``terminal_at``) individually bounded by the
cutoff. This is the one place ``n``/``k``/coverage denominators, the
delay curve's cohort tag, and the forward-information grid's exact-match
elapsed-time discipline are all derived from the SAME real event
population, rather than three independently-drifting approximations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from argus.copyability.delay_curves import CohortKey, DelayObservation
from argus.copyability.executable_returns import (
    EntryFill,
    ExecutableReturnResult,
    ReverseQuote,
    compute_executable_return,
)
from argus.copyability.identity import (
    EVIDENCE_CLASS_AUTHENTIC_PROSPECTIVE,
    REASON_DISCOVERY_CONTAMINATED,
    REASON_FUTURE_KNOWLEDGE,
    ExcludedSourceRef,
    SourceRef,
)
from argus.domain.prospective_events import ProspectiveEvent
from argus.domain.shadow_intents import STATUS_CREATED, STATUS_FILLED, ShadowIntent
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    PROBE_KIND_ENTRY_DELAY,
    PROBE_KIND_REVERSE_EXECUTABLE,
    ShadowQuoteProbe,
)
from argus.domain.swaps import Swap
from argus.domain.tokens import Token
from argus.domain.wallet_discovery_events import WalletDiscoveryEvent

PRIMARY_EXECUTABLE_HORIZON = "5m"
LONG_HORIZON_LABELS = ("5m", "30m", "1h", "6h", "24h")
SIZE_SURPRISE_WINDOW_DAYS = 90
SIZE_SURPRISE_MAX_PRIOR = 100

# Fixed nominal seconds for every executable/reverse horizon label this
# project uses -- needed to compute an observation's actual elapsed time
# from first_seen_at against the forward-information grid's fixed cells.
_HORIZON_SECONDS = {"5m": 300, "30m": 1800, "1h": 3600, "6h": 21600, "24h": 86400}

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


async def resolve_token_ids_by_mint(session: AsyncSession, mints: set[str]) -> dict[str, uuid.UUID]:
    """F5-01: real persisted ``tokens`` lookup -- the one place a mint
    string is ever resolved to a real ``token_id`` for firewall
    exclusion, replacing the previous ``token_id_by_mint={}`` stub that
    made the discovery firewall structurally unable to exclude prior
    buys by output mint."""
    if not mints:
        return {}
    rows = (await session.execute(select(Token).where(Token.mint.in_(mints)))).scalars().all()
    return {row.mint: row.token_id for row in rows}


def _probe_known_by_cutoff(probe: ShadowQuoteProbe, cutoff: datetime) -> bool:
    """F5-01: a probe is usable evidence as-of ``cutoff`` only if it is
    genuinely terminal (``terminal_at`` set) AND every one of its own
    real timestamps (``created_at``, ``requested_at``, ``responded_at``,
    ``terminal_at``) -- not merely ``terminal_at`` -- is <= cutoff. A
    probe recorded/requested/responded one instant after cutoff must
    never be included even if its ``terminal_at`` happens to satisfy the
    bound alone."""
    if probe.terminal_at is None or probe.terminal_at > cutoff:
        return False
    if probe.created_at > cutoff:
        return False
    if probe.requested_at is not None and probe.requested_at > cutoff:
        return False
    return not (probe.responded_at is not None and probe.responded_at > cutoff)


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
    token_id_by_mint: dict[str, uuid.UUID] | None = None,
    current_swap_id: uuid.UUID | None = None,
) -> PriorBuyLoadResult:
    """M4's baseline: the wallet's own last <=100 known positive buy
    notionals in ``quote_mint``, strictly during the 90 days before
    ``signal_at``, excluding the current buy, anything not yet known by
    ``cutoff`` (bounding BOTH ``first_seen_at`` and ``created_at`` --
    F5-01: a buy first seen before cutoff but only recorded/backdated
    after it must still be excluded), duplicates (deduplicated by the
    underlying chain ``event_id``, not the possibly-reparsed ``swap_id``
    -- F5-01), and anything whose acquired token is discovery-
    contaminated for this wallet (M7)."""
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

    if token_id_by_mint is None:
        token_id_by_mint = await resolve_token_ids_by_mint(
            session, {row.output_mint for row in rows if row.output_mint}
        )

    contributing: list[SourceRef] = []
    excluded: list[ExcludedSourceRef] = []
    sizes: list[Decimal] = []
    seen_event_ids: set[uuid.UUID] = set()
    for row in rows:
        ref = SourceRef("swap", str(row.swap_id))
        if row.swap_id == current_swap_id:
            continue  # the current buy itself, excluded structurally (not a "prior" buy)
        if row.event_id in seen_event_ids:
            excluded.append(ExcludedSourceRef(ref, "DUPLICATE_EVENT"))
            continue
        if row.first_seen_at is None or row.first_seen_at > cutoff:
            excluded.append(ExcludedSourceRef(ref, REASON_FUTURE_KNOWLEDGE))
            continue
        if row.created_at is None or row.created_at > cutoff:
            excluded.append(ExcludedSourceRef(ref, REASON_FUTURE_KNOWLEDGE))
            continue
        token_id = token_id_by_mint.get(row.output_mint) if row.output_mint else None
        if firewall.is_contaminated(token_id):
            excluded.append(ExcludedSourceRef(ref, REASON_DISCOVERY_CONTAMINATED))
            continue
        if row.input_amount_ui is None:
            excluded.append(ExcludedSourceRef(ref, "MISSING_UI_AMOUNT"))
            continue
        seen_event_ids.add(row.event_id)
        contributing.append(ref)
        sizes.append(row.input_amount_ui)

    # Most recent <= 100, chronological ascending (M4's own contract).
    if len(sizes) > SIZE_SURPRISE_MAX_PRIOR:
        sizes = sizes[-SIZE_SURPRISE_MAX_PRIOR:]
        contributing = contributing[-SIZE_SURPRISE_MAX_PRIOR:]

    return PriorBuyLoadResult(sizes=sizes, contributing=contributing, excluded=excluded)


@dataclass(frozen=True)
class OpportunityReverseOutcome:
    """One known-by-cutoff ``REVERSE_EXECUTABLE`` probe's real result for
    one opportunity, at one horizon label.

    ``reverse_quote`` (R2-03) is the SAME raw quote ``result`` was
    computed from, preserved so a caller needing a different entry basis
    (Strategy C/D's confirmation-time entry, never the leader's own
    fill -- see ``OpportunityEntryProbe``) can recompute
    ``compute_executable_return`` against it. Recomputing against a
    substituted entry naturally -- via ``compute_executable_return``'s own
    mint/quantity validation, never a new ad hoc check -- rejects any
    combination where the reverse probe's sold quantity does not match
    the substituted entry's acquired quantity, since Phase 4 only ever
    sized a REVERSE_EXECUTABLE probe against the ONE real fill it
    followed."""

    probe_id: uuid.UUID
    target_label: str
    raw_outcome: str
    result: ExecutableReturnResult
    actual_elapsed_seconds_from_first_seen: Decimal | None
    reverse_quote: ReverseQuote | None = None


@dataclass(frozen=True)
class OpportunityEntryProbe:
    """One known-by-cutoff ``ENTRY_DELAY`` probe for one opportunity's
    shadow intent, at one delay label -- R2-03: Strategy C/D's
    confirmation-entry must be matched against these (never against the
    leader's own realized ``entry_fill``, which is always exactly ONE
    fixed delay Phase 4's own runtime happened to use)."""

    probe_id: uuid.UUID
    target_label: str
    outcome: str
    entry_fill: EntryFill | None
    actual_elapsed_seconds_from_first_seen: Decimal | None


@dataclass(frozen=True)
class WalletOpportunity:
    """One "eligible terminal entry-event opportunity" (F5-03's own
    phrase) -- one row per :class:`ShadowIntent` known by cutoff, whether
    or not its entry ultimately filled. An entry failure (``NO_FILL``)
    carries no position and an empty ``reverse_outcomes`` -- it still
    counts toward M5's coverage denominator, per F5-03's correction."""

    shadow_intent_id: uuid.UUID
    token_id: uuid.UUID | None
    first_seen_at: datetime
    entry_status: str
    shadow_position_id: uuid.UUID | None
    entry_target_label: str | None
    entry_target_seconds: int | None
    entry_fill: EntryFill | None
    entry_price_impact_pct: Decimal | None
    reverse_outcomes: dict[str, OpportunityReverseOutcome] = field(default_factory=dict)
    # R2-03: every known-by-cutoff ENTRY_DELAY probe for this SAME shadow
    # intent, keyed by target_label -- additive; existing M1-M6 consumers
    # never read this and are unaffected. Populated regardless of
    # ``entry_status``/``entry_fill`` (an ENTRY_DELAY probe is scheduled
    # against the shadow intent itself, before any position exists).
    entry_delay_probes: dict[str, OpportunityEntryProbe] = field(default_factory=dict)
    evidence_class: str = EVIDENCE_CLASS_AUTHENTIC_PROSPECTIVE


@dataclass(frozen=True)
class WalletOpportunitiesResult:
    opportunities: list[WalletOpportunity]
    contributing: list[SourceRef]
    excluded: list[ExcludedSourceRef]


def _entry_delay_seconds(label: str) -> int:
    """ "1s".."300s" -> integer seconds; entry-delay labels are always
    plain second counts (``config/signals_v1.yaml``'s
    ``copyability_delay_probes_seconds``)."""
    if label.endswith("s"):
        return int(label[:-1])
    raise ValueError(f"unrecognized entry-delay target label: {label!r}")


async def load_wallet_opportunities(
    session: AsyncSession,
    *,
    wallet_id: uuid.UUID,
    cutoff: datetime,
    firewall: ContaminationFirewall,
    exclude_shadow_intent_id: uuid.UUID | None = None,
) -> WalletOpportunitiesResult:
    """The one real production event population every Phase 5 mechanic
    (M2/M3/M5) reads from -- see module docstring. ``exclude_shadow_
    intent_id`` lets a per-opportunity readiness computation (M6) exclude
    its OWN opportunity from the copyability support it reads (M1: "an
    outcome belonging to the current opportunity cannot enter its own
    earlier readiness inputs")."""
    intents = (
        (
            await session.execute(
                select(ShadowIntent).where(
                    ShadowIntent.wallet_id == wallet_id,
                    ShadowIntent.created_at <= cutoff,
                    ShadowIntent.status != STATUS_CREATED,
                )
            )
        )
        .scalars()
        .all()
    )
    if exclude_shadow_intent_id is not None:
        intents = [i for i in intents if i.shadow_intent_id != exclude_shadow_intent_id]

    contributing: list[SourceRef] = []
    excluded: list[ExcludedSourceRef] = []
    opportunities: list[WalletOpportunity] = []

    for intent in intents:
        intent_ref = SourceRef("shadow_intent", str(intent.shadow_intent_id))
        if firewall.is_contaminated(intent.token_id):
            excluded.append(ExcludedSourceRef(intent_ref, REASON_DISCOVERY_CONTAMINATED))
            continue

        prospective_event = await session.get(ProspectiveEvent, intent.prospective_event_id)
        if (
            prospective_event is None
            or prospective_event.created_at > cutoff
            or prospective_event.first_seen_at > cutoff
        ):
            excluded.append(ExcludedSourceRef(intent_ref, REASON_FUTURE_KNOWLEDGE))
            continue
        first_seen_at = prospective_event.first_seen_at

        position: ShadowPosition | None = None
        entry_fill: EntryFill | None = None
        entry_price_impact_pct: Decimal | None = None
        entry_target_label: str | None = None
        entry_target_seconds: int | None = None
        reverse_outcomes: dict[str, OpportunityReverseOutcome] = {}

        if intent.status == STATUS_FILLED:
            position = (
                await session.execute(
                    select(ShadowPosition).where(
                        ShadowPosition.shadow_intent_id == intent.shadow_intent_id
                    )
                )
            ).scalar_one_or_none()
            if position is None or position.created_at > cutoff:
                excluded.append(ExcludedSourceRef(intent_ref, REASON_FUTURE_KNOWLEDGE))
                continue

            entry_fill = EntryFill(
                input_mint=position.input_mint,
                output_mint=position.output_mint,
                input_amount_raw=position.entry_input_amount_raw,
                output_amount_raw=position.entry_output_amount_raw,
            )
            entry_price_impact_pct = position.entry_price_impact_pct
            entry_target_label = position.entry_probe_target_label
            entry_target_seconds = _entry_delay_seconds(entry_target_label)

            probes = (
                (
                    await session.execute(
                        select(ShadowQuoteProbe).where(
                            ShadowQuoteProbe.shadow_position_id == position.shadow_position_id,
                            ShadowQuoteProbe.probe_kind == PROBE_KIND_REVERSE_EXECUTABLE,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for probe in probes:
                probe_ref = SourceRef("shadow_quote_probe", str(probe.probe_id))
                if not _probe_known_by_cutoff(probe, cutoff):
                    excluded.append(
                        ExcludedSourceRef(probe_ref, "REVERSE_QUOTE_NOT_YET_TERMINAL_BY_CUTOFF")
                    )
                    continue
                reverse = ReverseQuote(
                    outcome=probe.outcome,
                    input_mint=probe.input_mint,
                    output_mint=probe.output_mint,
                    input_amount_raw=probe.notional_input_amount_raw,
                    output_amount_raw=probe.expected_output_amount_raw,
                )
                result = compute_executable_return(entry_fill, reverse)
                elapsed = None
                if probe.terminal_at is not None:
                    elapsed = Decimal((probe.terminal_at - first_seen_at).total_seconds())
                reverse_outcomes[probe.target_label] = OpportunityReverseOutcome(
                    probe_id=probe.probe_id,
                    target_label=probe.target_label,
                    raw_outcome=probe.outcome,
                    result=result,
                    actual_elapsed_seconds_from_first_seen=elapsed,
                    reverse_quote=reverse,
                )
                contributing.append(probe_ref)
            contributing.append(SourceRef("shadow_position", str(position.shadow_position_id)))

        # R2-03: every known-by-cutoff ENTRY_DELAY probe for this shadow
        # intent -- independent of ``entry_status``/``position`` above,
        # since these probes are scheduled directly against the intent
        # itself. Strategy C/D's confirmation-entry matching needs the
        # FULL family (Phase 4 schedules one per configured delay), never
        # only whichever single delay happened to become the real fill.
        entry_delay_probes: dict[str, OpportunityEntryProbe] = {}
        entry_probes = (
            (
                await session.execute(
                    select(ShadowQuoteProbe).where(
                        ShadowQuoteProbe.shadow_intent_id == intent.shadow_intent_id,
                        ShadowQuoteProbe.probe_kind == PROBE_KIND_ENTRY_DELAY,
                    )
                )
            )
            .scalars()
            .all()
        )
        for entry_probe in entry_probes:
            entry_probe_ref = SourceRef("shadow_quote_probe", str(entry_probe.probe_id))
            if not _probe_known_by_cutoff(entry_probe, cutoff):
                excluded.append(
                    ExcludedSourceRef(entry_probe_ref, "ENTRY_DELAY_NOT_YET_TERMINAL_BY_CUTOFF")
                )
                continue
            probe_entry_fill = (
                EntryFill(
                    input_mint=entry_probe.input_mint,
                    output_mint=entry_probe.output_mint,
                    input_amount_raw=entry_probe.notional_input_amount_raw,
                    output_amount_raw=entry_probe.expected_output_amount_raw,
                )
                if entry_probe.outcome == "SUCCESS" and entry_probe.expected_output_amount_raw
                else None
            )
            probe_elapsed = None
            if entry_probe.terminal_at is not None:
                probe_elapsed = Decimal((entry_probe.terminal_at - first_seen_at).total_seconds())
            entry_delay_probes[entry_probe.target_label] = OpportunityEntryProbe(
                probe_id=entry_probe.probe_id,
                target_label=entry_probe.target_label,
                outcome=entry_probe.outcome,
                entry_fill=probe_entry_fill,
                actual_elapsed_seconds_from_first_seen=probe_elapsed,
            )
            contributing.append(entry_probe_ref)

        contributing.append(intent_ref)
        opportunities.append(
            WalletOpportunity(
                shadow_intent_id=intent.shadow_intent_id,
                token_id=intent.token_id,
                first_seen_at=first_seen_at,
                entry_status=intent.status,
                shadow_position_id=position.shadow_position_id if position else None,
                entry_target_label=entry_target_label,
                entry_target_seconds=entry_target_seconds,
                entry_fill=entry_fill,
                entry_price_impact_pct=entry_price_impact_pct,
                reverse_outcomes=reverse_outcomes,
                entry_delay_probes=entry_delay_probes,
            )
        )

    return WalletOpportunitiesResult(
        opportunities=opportunities, contributing=contributing, excluded=excluded
    )


def build_delay_observations_for_curve(
    opportunities: list[WalletOpportunity],
    *,
    horizon_label: str,
    quote_mint: str,
) -> list[DelayObservation]:
    """Reduces the real opportunity population to cohort-tagged
    :class:`DelayObservation` rows for :func:`argus.copyability.
    delay_curves.build_delay_curve` -- one per FILLED opportunity that
    has a genuinely SUCCESS executable return at ``horizon_label``,
    x-axis = that opportunity's own entry-delay label (cross-sectional
    across distinct events, per the "important data limitation": exactly
    one position per intent, so the entry-delay curve is necessarily
    built across events, never within one)."""
    observations: list[DelayObservation] = []
    for opp in opportunities:
        if opp.entry_fill is None or opp.entry_target_label is None:
            continue
        outcome = opp.reverse_outcomes.get(horizon_label)
        if outcome is None:
            continue
        result = outcome.result
        if result.status != "SUCCESS" or result.gross_return_fraction is None:
            continue
        cohort = CohortKey(
            notional_raw=opp.entry_fill.input_amount_raw,
            quote_mint=quote_mint,
            horizon_label=horizon_label,
            evidence_class=opp.evidence_class,
        )
        observations.append(
            DelayObservation(
                event_id=str(opp.shadow_intent_id),
                target_label=opp.entry_target_label,
                target_seconds=opp.entry_target_seconds,  # type: ignore[arg-type]
                return_fraction=result.gross_return_fraction,
                cohort=cohort,
            )
        )
    return observations


def build_forward_information_observations(
    opportunities: list[WalletOpportunity],
) -> dict[str, list[Decimal]]:
    """F5-02: honest forward-information-grid evidence -- for each fixed
    grid horizon label, collect ONLY the actual executable returns whose
    REAL elapsed time from ``first_seen_at`` to the reverse probe's own
    ``terminal_at`` exactly equals that horizon's nominal seconds. An
    entry delayed 5s with a 5m (300s) holding exit lands at an actual
    elapsed ~305s -- NOT an exact match for the "5m" cell, which stays
    unavailable for that opportunity (never relabeled/interpolated)."""
    from argus.copyability.delay_curves import FORWARD_INFO_HORIZON_LABELS

    results: dict[str, list[Decimal]] = {label: [] for label in FORWARD_INFO_HORIZON_LABELS}
    for opp in opportunities:
        for outcome in opp.reverse_outcomes.values():
            result = outcome.result
            if result.status != "SUCCESS" or result.gross_return_fraction is None:
                continue
            elapsed = outcome.actual_elapsed_seconds_from_first_seen
            if elapsed is None:
                continue
            for label in FORWARD_INFO_HORIZON_LABELS:
                nominal_seconds = _HORIZON_SECONDS.get(label)
                if nominal_seconds is None:
                    nominal_seconds = _entry_delay_seconds(label)
                if elapsed == nominal_seconds:
                    results[label].append(result.gross_return_fraction)
    return results


__all__ = [
    "LONG_HORIZON_LABELS",
    "PRIMARY_EXECUTABLE_HORIZON",
    "ContaminationFirewall",
    "OpportunityReverseOutcome",
    "PriorBuyLoadResult",
    "WalletOpportunitiesResult",
    "WalletOpportunity",
    "build_delay_observations_for_curve",
    "build_forward_information_observations",
    "load_contamination_firewall",
    "load_prior_buy_sizes",
    "load_wallet_opportunities",
    "resolve_token_ids_by_mint",
]
