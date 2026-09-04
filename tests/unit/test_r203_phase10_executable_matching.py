"""R2-03 (``argus-final-spec-recovery-002``): Phase 10 strategy-time
executable matching -- pure-function coverage for
``argus.synthetic.service._select_contemporaneous_reverse_outcome``,
``_select_contemporaneous_entry_probe``, and ``_entry_lookup_at``,
requiring no database. These replace the fixed
``PRIMARY_EXECUTABLE_HORIZON`` lookup, the confirmation-entry opportunity
lookup bug, and the confirmation-entry PRICE bug (Strategy C/D silently
reusing the leader's own realized fill) the R2-03 audit named; see
``tests/integration/test_phase10_synthetic_persistence_and_report.py``
and ``test_r202_specialist_knowledge_time.py`` for the DB-backed
end-to-end coverage of the same fixes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from argus.copyability.executable_returns import EntryFill, ExecutableReturnResult
from argus.copyability.loaders import (
    OpportunityEntryProbe,
    OpportunityReverseOutcome,
    WalletOpportunity,
)
from argus.synthetic.loaders import LEADER_ENTRY_AT_REFERENCE_KEY
from argus.synthetic.matching import TriggerEvent
from argus.synthetic.service import (
    _entry_lookup_at,
    _select_contemporaneous_entry_probe,
    _select_contemporaneous_reverse_outcome,
)

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def _outcome(
    *, label: str, elapsed_seconds: int, status: str = "SUCCESS"
) -> OpportunityReverseOutcome:
    result = (
        ExecutableReturnResult(
            status="SUCCESS",
            gross_return_fraction=Decimal("0.05"),
            net_return_fraction=Decimal("0.04"),
        )
        if status == "SUCCESS"
        else ExecutableReturnResult(status="FAILED", failure_class="NO_ROUTE")
    )
    return OpportunityReverseOutcome(
        probe_id=uuid.uuid4(),
        target_label=label,
        raw_outcome="SUCCESS" if status == "SUCCESS" else "NO_ROUTE",
        result=result,
        actual_elapsed_seconds_from_first_seen=Decimal(elapsed_seconds),
    )


def _entry_probe(
    *, label: str, elapsed_seconds: int, outcome: str = "SUCCESS"
) -> OpportunityEntryProbe:
    fill = (
        EntryFill(
            input_mint="quote",
            output_mint="token",
            input_amount_raw=1_000_000,
            output_amount_raw=42,
        )
        if outcome == "SUCCESS"
        else None
    )
    return OpportunityEntryProbe(
        probe_id=uuid.uuid4(),
        target_label=label,
        outcome=outcome,
        entry_fill=fill,
        actual_elapsed_seconds_from_first_seen=Decimal(elapsed_seconds),
    )


def _opportunity(
    reverse_outcomes: dict[str, OpportunityReverseOutcome],
    *,
    entry_delay_probes: dict[str, OpportunityEntryProbe] | None = None,
) -> WalletOpportunity:
    return WalletOpportunity(
        shadow_intent_id=uuid.uuid4(),
        token_id=uuid.uuid4(),
        first_seen_at=_NOW,
        entry_status="FILLED",
        shadow_position_id=uuid.uuid4(),
        entry_target_label="0s",
        entry_target_seconds=0,
        entry_fill=None,
        entry_price_impact_pct=None,
        reverse_outcomes=reverse_outcomes,
        entry_delay_probes=entry_delay_probes or {},
    )


def test_one_hour_exit_trap_picks_the_one_hour_probe_not_five_minutes() -> None:
    """The exact bug R2-03 fixes: a trade held ~1 hour must be priced
    against the probe whose REAL elapsed time is close to 1 hour, never
    the always-available 5-minute probe."""
    opportunity = _opportunity(
        {
            "5m": _outcome(label="5m", elapsed_seconds=301),
            "1h": _outcome(label="1h", elapsed_seconds=3605),
        }
    )
    selected = _select_contemporaneous_reverse_outcome(
        opportunity, actual_hold_seconds=Decimal(3600)
    )
    assert selected is not None
    assert selected.target_label == "1h"


def test_no_exit_time_evidence_is_none_not_a_distant_substitute() -> None:
    """A trade held 24 hours with only a 5-minute probe available has NO
    genuinely contemporaneous evidence -- must be None (caller maps this
    to FAILURE_NO_EXECUTABLE_EVIDENCE), never silently priced off the
    5-minute quote."""
    opportunity = _opportunity({"5m": _outcome(label="5m", elapsed_seconds=300)})
    selected = _select_contemporaneous_reverse_outcome(
        opportunity, actual_hold_seconds=Decimal(24 * 3600)
    )
    assert selected is None


def test_no_reverse_outcomes_at_all_is_none() -> None:
    opportunity = _opportunity({})
    selected = _select_contemporaneous_reverse_outcome(
        opportunity, actual_hold_seconds=Decimal(300)
    )
    assert selected is None


def test_unsellable_exit_within_the_contemporaneous_band_is_still_a_failure() -> None:
    """A contemporaneous match that happens to be unsellable must still be
    selected and surfaced as a failure -- contemporaneous matching must
    never silently prefer a resolvable horizon over the genuinely
    contemporaneous (but unsellable) one."""
    opportunity = _opportunity(
        {
            "5m": _outcome(label="5m", elapsed_seconds=298, status="FAILED"),
            "24h": _outcome(label="24h", elapsed_seconds=24 * 3600),
        }
    )
    selected = _select_contemporaneous_reverse_outcome(
        opportunity, actual_hold_seconds=Decimal(300)
    )
    assert selected is not None
    assert selected.target_label == "5m"
    assert selected.result.status == "FAILED"
    assert selected.result.failure_class == "NO_ROUTE"


def test_probes_missing_real_elapsed_time_are_never_candidates() -> None:
    """A probe whose elapsed time was never observed (still pending, or a
    label-only record with no real timing) must never be silently
    substituted -- only probes with REAL observed elapsed evidence are
    eligible candidates."""
    pending = OpportunityReverseOutcome(
        probe_id=uuid.uuid4(),
        target_label="5m",
        raw_outcome="PENDING",
        result=ExecutableReturnResult(status="PENDING"),
        actual_elapsed_seconds_from_first_seen=None,
    )
    opportunity = _opportunity({"5m": pending})
    selected = _select_contemporaneous_reverse_outcome(
        opportunity, actual_hold_seconds=Decimal(300)
    )
    assert selected is None


def test_zero_or_negative_hold_duration_is_always_none() -> None:
    opportunity = _opportunity({"5m": _outcome(label="5m", elapsed_seconds=300)})
    assert (
        _select_contemporaneous_reverse_outcome(opportunity, actual_hold_seconds=Decimal(0)) is None
    )
    assert (
        _select_contemporaneous_reverse_outcome(opportunity, actual_hold_seconds=Decimal(-1))
        is None
    )


def test_confirmation_entry_uses_leaders_own_entry_time_not_confirmation_time() -> None:
    """The 'confirmation-entry trap': a Strategy C/D TriggerEvent's own
    ``at`` is the FOLLOWER's confirmation time (correct for sequencing),
    but the executable-return opportunity lookup must use the LEADER's
    real entry time carried in ``reference[LEADER_ENTRY_AT_REFERENCE_KEY]``."""
    leader_entry_at = _NOW
    confirmation_at = _NOW + timedelta(minutes=37)
    entry = TriggerEvent(
        token_id=uuid.uuid4(),
        wallet_id=uuid.uuid4(),
        at=confirmation_at,
        reference={
            "type": "confirmation_event",
            "id": "abc",
            LEADER_ENTRY_AT_REFERENCE_KEY: leader_entry_at.isoformat(),
        },
    )
    assert _entry_lookup_at(entry) == leader_entry_at
    assert _entry_lookup_at(entry) != entry.at


def test_confirmation_entry_no_evidence_falls_back_to_entry_at() -> None:
    """A source (non-confirmed) entry has no
    ``LEADER_ENTRY_AT_REFERENCE_KEY`` at all -- lookup must use ``at``
    directly, unchanged from before R2-03."""
    entry = TriggerEvent(
        token_id=uuid.uuid4(),
        wallet_id=uuid.uuid4(),
        at=_NOW,
        reference={"type": "swap", "id": "x"},
    )
    assert _entry_lookup_at(entry) == _NOW


def test_confirmation_entry_price_uses_contemporaneous_entry_probe_not_leader_fill() -> None:
    """The 'confirmation-entry PRICE trap': even once the opportunity
    lookup itself is fixed, Strategy C/D must price its entry from an
    ENTRY_DELAY probe genuinely contemporaneous with the follower's own
    confirmation delay -- never the leader's single realized fill delay
    (here "1s", far from the follower's real ~180s delay)."""
    opportunity = _opportunity(
        {},
        entry_delay_probes={
            "1s": _entry_probe(label="1s", elapsed_seconds=1),
            "300s": _entry_probe(label="300s", elapsed_seconds=298),
        },
    )
    selected = _select_contemporaneous_entry_probe(
        opportunity, actual_entry_delay_seconds=Decimal(180)
    )
    assert selected is not None
    assert selected.target_label == "300s"


def test_confirmation_entry_no_evidence_near_confirmation_is_none() -> None:
    """No ENTRY_DELAY probe genuinely contemporaneous with the
    follower's own confirmation delay -- must be ``None`` (the caller
    maps this to ``FAILURE_NO_EXECUTABLE_EVIDENCE``), never a distant
    substitute."""
    opportunity = _opportunity(
        {}, entry_delay_probes={"1s": _entry_probe(label="1s", elapsed_seconds=1)}
    )
    selected = _select_contemporaneous_entry_probe(
        opportunity, actual_entry_delay_seconds=Decimal(3600)
    )
    assert selected is None


def test_confirmation_entry_probe_missing_fill_is_never_a_candidate() -> None:
    """A FAILED/PENDING ENTRY_DELAY probe (no real fill resolved) must
    never be silently substituted, even if its timing would otherwise
    match."""
    opportunity = _opportunity(
        {},
        entry_delay_probes={
            "180s": _entry_probe(label="180s", elapsed_seconds=180, outcome="NO_ROUTE")
        },
    )
    selected = _select_contemporaneous_entry_probe(
        opportunity, actual_entry_delay_seconds=Decimal(180)
    )
    assert selected is None


def test_confirmation_entry_zero_or_negative_delay_is_always_none() -> None:
    opportunity = _opportunity(
        {}, entry_delay_probes={"1s": _entry_probe(label="1s", elapsed_seconds=1)}
    )
    assert (
        _select_contemporaneous_entry_probe(opportunity, actual_entry_delay_seconds=Decimal(0))
        is None
    )
    assert (
        _select_contemporaneous_entry_probe(opportunity, actual_entry_delay_seconds=Decimal(-5))
        is None
    )
