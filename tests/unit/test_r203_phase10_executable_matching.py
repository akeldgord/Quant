"""R2-03 (``argus-final-spec-recovery-002``) and its Clarification-001
(``argus-final-spec-recovery-002-clarification-001``, section 4): Phase 10
strategy-time executable matching -- pure-function coverage for
``argus.synthetic.service._select_contemporaneous_reverse_outcome``,
``_select_contemporaneous_entry_probe``, ``_select_own_entry_fill_if_
contemporaneous``, and ``_entry_lookup_at``, requiring no database. These
replace the fixed ``PRIMARY_EXECUTABLE_HORIZON`` lookup, the
confirmation-entry opportunity lookup bug, the confirmation-entry PRICE
bug (Strategy C/D silently reusing the leader's own realized fill), the
unconditional Strategy A/B entry-fill reuse bug, and the hardcoded
unversioned 0.5x-2.0x ratio tolerance the two audits named; see
``tests/integration/test_phase10_synthetic_persistence_and_report.py``
and ``test_r202_specialist_knowledge_time.py`` for the DB-backed
end-to-end coverage of the same fixes.

Clarification-002 (``argus-final-spec-recovery-002-clarification-002``,
section 4): ``_select_own_entry_fill_if_contemporaneous`` now compares the
ACTUAL executable-entry-evidence timestamp to the STRATEGY's own entry
trigger time (``matched.entry.at``), never merely the matching probe's
own configured target delay (clarification-001's prior, weaker check) --
see the ``test_own_entry_fill_*`` tests below. Deterministic nearest/
tiebreak coverage for "more than one eligible real entry observation"
already exists for the sibling confirmation-entry function
(``test_entry_probe_tiebreak_is_deterministic_by_target_label``,
``_select_contemporaneous_entry_probe``) -- Strategy A/B's OWN function
deliberately stays bound to the ONE realized ``opportunity.entry_fill``
(never substituting a DIFFERENT ENTRY_DELAY probe's own hypothetical
fill, which would silently change the reported trade's actual bought
quantity/mint for a strategy whose entire premise is "the same wallet's
REAL realized buy") -- so there is exactly one real timing-evidence
candidate per opportunity here, and no tiebreak scenario arises.
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
    Phase10RunConfig,
    _entry_lookup_at,
    _select_contemporaneous_entry_probe,
    _select_contemporaneous_reverse_outcome,
    _select_own_entry_fill_if_contemporaneous,
)

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

# Clarification-001 section 4.2: the SAME absolute-delta tolerance every
# test here uses, matching the production default
# (``argus.cli``'s own ``Phase10RunConfig.contemporaneous_match_max_delta``)
# -- an explicit, versioned value, never a ratio.
_MAX_DELTA = Decimal(120)

_ENTRY_FILL = EntryFill(
    input_mint="quote", output_mint="token", input_amount_raw=1_000_000, output_amount_raw=42
)


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
    fill = _ENTRY_FILL if outcome == "SUCCESS" else None
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
    entry_fill: EntryFill | None = None,
    entry_target_label: str | None = "0s",
    entry_target_seconds: int | None = 0,
) -> WalletOpportunity:
    return WalletOpportunity(
        shadow_intent_id=uuid.uuid4(),
        token_id=uuid.uuid4(),
        first_seen_at=_NOW,
        entry_status="FILLED",
        shadow_position_id=uuid.uuid4(),
        entry_target_label=entry_target_label,
        entry_target_seconds=entry_target_seconds,
        entry_fill=entry_fill,
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
        opportunity, actual_hold_seconds=Decimal(3600), max_delta_seconds=_MAX_DELTA
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
        opportunity, actual_hold_seconds=Decimal(24 * 3600), max_delta_seconds=_MAX_DELTA
    )
    assert selected is None


def test_no_reverse_outcomes_at_all_is_none() -> None:
    opportunity = _opportunity({})
    selected = _select_contemporaneous_reverse_outcome(
        opportunity, actual_hold_seconds=Decimal(300), max_delta_seconds=_MAX_DELTA
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
        opportunity, actual_hold_seconds=Decimal(300), max_delta_seconds=_MAX_DELTA
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
        opportunity, actual_hold_seconds=Decimal(300), max_delta_seconds=_MAX_DELTA
    )
    assert selected is None


def test_zero_or_negative_hold_duration_is_always_none() -> None:
    opportunity = _opportunity({"5m": _outcome(label="5m", elapsed_seconds=300)})
    assert (
        _select_contemporaneous_reverse_outcome(
            opportunity, actual_hold_seconds=Decimal(0), max_delta_seconds=_MAX_DELTA
        )
        is None
    )
    assert (
        _select_contemporaneous_reverse_outcome(
            opportunity, actual_hold_seconds=Decimal(-1), max_delta_seconds=_MAX_DELTA
        )
        is None
    )


def test_reverse_outcome_tiebreak_is_deterministic_by_target_label() -> None:
    """Clarification-001 section 4.2: when two candidates are EQUALLY
    close to the trade's own actual hold duration, the tiebreak must be
    deterministic (by ``target_label``), never dependent on dict/DB
    iteration order."""
    opportunity = _opportunity(
        {
            "30m": _outcome(label="30m", elapsed_seconds=295),
            "5m": _outcome(label="5m", elapsed_seconds=305),
        }
    )
    selected = _select_contemporaneous_reverse_outcome(
        opportunity, actual_hold_seconds=Decimal(300), max_delta_seconds=_MAX_DELTA
    )
    assert selected is not None
    assert selected.target_label == "30m"


def test_reverse_outcome_rejected_exactly_past_the_configured_tolerance() -> None:
    """Clarification-001 section 4.2: eligibility is an ABSOLUTE delta
    against the configured tolerance -- one second past it is rejected,
    exactly at it is accepted."""
    at_boundary = _opportunity({"5m": _outcome(label="5m", elapsed_seconds=300 + 120)})
    assert (
        _select_contemporaneous_reverse_outcome(
            at_boundary, actual_hold_seconds=Decimal(300), max_delta_seconds=_MAX_DELTA
        )
        is not None
    )
    past_boundary = _opportunity({"5m": _outcome(label="5m", elapsed_seconds=300 + 121)})
    assert (
        _select_contemporaneous_reverse_outcome(
            past_boundary, actual_hold_seconds=Decimal(300), max_delta_seconds=_MAX_DELTA
        )
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
        opportunity, actual_entry_delay_seconds=Decimal(180), max_delta_seconds=_MAX_DELTA
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
        opportunity, actual_entry_delay_seconds=Decimal(3600), max_delta_seconds=_MAX_DELTA
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
        opportunity, actual_entry_delay_seconds=Decimal(180), max_delta_seconds=_MAX_DELTA
    )
    assert selected is None


def test_confirmation_entry_zero_or_negative_delay_is_always_none() -> None:
    opportunity = _opportunity(
        {}, entry_delay_probes={"1s": _entry_probe(label="1s", elapsed_seconds=1)}
    )
    assert (
        _select_contemporaneous_entry_probe(
            opportunity, actual_entry_delay_seconds=Decimal(0), max_delta_seconds=_MAX_DELTA
        )
        is None
    )
    assert (
        _select_contemporaneous_entry_probe(
            opportunity, actual_entry_delay_seconds=Decimal(-5), max_delta_seconds=_MAX_DELTA
        )
        is None
    )


def test_entry_probe_tiebreak_is_deterministic_by_target_label() -> None:
    """Same deterministic-tiebreak requirement as the exit side, for the
    entry side's own probe selection."""
    opportunity = _opportunity(
        {},
        entry_delay_probes={
            "60s": _entry_probe(label="60s", elapsed_seconds=175),
            "15s": _entry_probe(label="15s", elapsed_seconds=185),
        },
    )
    selected = _select_contemporaneous_entry_probe(
        opportunity, actual_entry_delay_seconds=Decimal(180), max_delta_seconds=_MAX_DELTA
    )
    assert selected is not None
    assert selected.target_label == "15s"


def test_own_entry_fill_used_when_within_tolerance_of_strategy_trigger() -> None:
    """Clarification-002 section 4: Strategy A/B's own entry_fill is used
    when the matching ENTRY_DELAY probe's REAL evidence timestamp
    (``first_seen_at + actual_elapsed_seconds_from_first_seen``) is
    genuinely contemporaneous with the STRATEGY's own entry trigger time
    -- the ordinary, well-behaved case."""
    opportunity = _opportunity(
        {},
        entry_fill=_ENTRY_FILL,
        entry_target_label="5s",
        entry_target_seconds=5,
        entry_delay_probes={"5s": _entry_probe(label="5s", elapsed_seconds=6)},
    )
    selected = _select_own_entry_fill_if_contemporaneous(
        opportunity, strategy_entry_at=_NOW + timedelta(seconds=8), max_delta_seconds=_MAX_DELTA
    )
    assert selected is _ENTRY_FILL


def test_own_entry_fill_rejected_when_real_evidence_drifts_from_strategy_trigger() -> None:
    """The exact defect clarification-002 section 4 names: a fill whose
    real evidence timestamp lands far from the STRATEGY's own entry
    trigger time must never be trusted, even if that timestamp is close
    to the fill's own configured target delay."""
    opportunity = _opportunity(
        {},
        entry_fill=_ENTRY_FILL,
        entry_target_label="5s",
        entry_target_seconds=5,
        entry_delay_probes={"5s": _entry_probe(label="5s", elapsed_seconds=6)},
    )
    selected = _select_own_entry_fill_if_contemporaneous(
        opportunity,
        strategy_entry_at=_NOW + timedelta(hours=2),
        max_delta_seconds=_MAX_DELTA,
    )
    assert selected is None


def test_own_entry_fill_rejected_when_it_perfectly_matches_own_target_but_far_from_trigger() -> (
    None
):
    """Clarification-002 section 4's own named scenario: a fill that
    perfectly matches its own configured ``entry_target_seconds`` (delta
    of zero against ITS OWN target) must still be rejected when its real
    evidence timestamp is far from the strategy's actual trigger time --
    "actual delay versus configured target delay" is never a substitute
    for "actual evidence timestamp versus strategy trigger timestamp."""
    opportunity = _opportunity(
        {},
        entry_fill=_ENTRY_FILL,
        entry_target_label="5s",
        entry_target_seconds=5,
        # elapsed_seconds == entry_target_seconds exactly -- a perfect
        # match against the fill's OWN target, the old (wrong) check.
        entry_delay_probes={"5s": _entry_probe(label="5s", elapsed_seconds=5)},
    )
    # The strategy's own trigger is far from first_seen_at + 5s.
    selected = _select_own_entry_fill_if_contemporaneous(
        opportunity,
        strategy_entry_at=_NOW + timedelta(hours=1),
        max_delta_seconds=_MAX_DELTA,
    )
    assert selected is None


def test_own_entry_fill_none_when_no_matching_probe_timing_evidence() -> None:
    """No ENTRY_DELAY probe at all for the fill's own target label -- no
    timing evidence to validate against, so honestly no-executable-
    evidence rather than assuming it is fine."""
    opportunity = _opportunity(
        {}, entry_fill=_ENTRY_FILL, entry_target_label="5s", entry_target_seconds=5
    )
    selected = _select_own_entry_fill_if_contemporaneous(
        opportunity, strategy_entry_at=_NOW, max_delta_seconds=_MAX_DELTA
    )
    assert selected is None


def test_own_entry_fill_none_when_no_entry_fill_at_all() -> None:
    opportunity = _opportunity(
        {},
        entry_fill=None,
        entry_target_label="5s",
        entry_target_seconds=5,
        entry_delay_probes={"5s": _entry_probe(label="5s", elapsed_seconds=5)},
    )
    assert (
        _select_own_entry_fill_if_contemporaneous(
            opportunity, strategy_entry_at=_NOW, max_delta_seconds=_MAX_DELTA
        )
        is None
    )


def test_own_entry_fill_none_when_target_label_or_seconds_missing() -> None:
    opportunity = _opportunity(
        {}, entry_fill=_ENTRY_FILL, entry_target_label=None, entry_target_seconds=None
    )
    assert (
        _select_own_entry_fill_if_contemporaneous(
            opportunity, strategy_entry_at=_NOW, max_delta_seconds=_MAX_DELTA
        )
        is None
    )


def test_own_entry_fill_accepted_exactly_at_the_configured_tolerance_boundary() -> None:
    """Boundary check against the STRATEGY trigger time (never the fill's
    own configured target): the probe's real evidence timestamp is
    ``first_seen_at + 120s``, and the strategy trigger is exactly 120s
    (then 121s) away from ``first_seen_at``."""
    opportunity = _opportunity(
        {},
        entry_fill=_ENTRY_FILL,
        entry_target_label="0s",
        entry_target_seconds=0,
        entry_delay_probes={"0s": _entry_probe(label="0s", elapsed_seconds=120)},
    )
    assert (
        _select_own_entry_fill_if_contemporaneous(
            opportunity, strategy_entry_at=_NOW, max_delta_seconds=_MAX_DELTA
        )
        is _ENTRY_FILL
    )
    opportunity_past = _opportunity(
        {},
        entry_fill=_ENTRY_FILL,
        entry_target_label="0s",
        entry_target_seconds=0,
        entry_delay_probes={"0s": _entry_probe(label="0s", elapsed_seconds=121)},
    )
    assert (
        _select_own_entry_fill_if_contemporaneous(
            opportunity_past, strategy_entry_at=_NOW, max_delta_seconds=_MAX_DELTA
        )
        is None
    )


def test_own_entry_fill_no_mark_price_fallback_when_no_probe_qualifies() -> None:
    """Clarification-002 section 4's own required test: with no
    contemporaneous timing evidence at all, the result must be ``None``
    -- the caller maps this to ``FAILURE_NO_EXECUTABLE_EVIDENCE``, never
    silently substituting a mark price or a distant fill."""
    opportunity = _opportunity(
        {},
        entry_fill=_ENTRY_FILL,
        entry_target_label="5s",
        entry_target_seconds=5,
        entry_delay_probes={"5s": _entry_probe(label="5s", elapsed_seconds=5)},
    )
    selected = _select_own_entry_fill_if_contemporaneous(
        opportunity,
        strategy_entry_at=_NOW + timedelta(days=1),
        max_delta_seconds=_MAX_DELTA,
    )
    assert selected is None


def test_config_hash_changes_with_contemporaneous_match_max_delta() -> None:
    """Clarification-001 section 4.2: the tolerance must be VERSIONED
    configuration -- two ``Phase10RunConfig``s differing only in
    ``contemporaneous_match_max_delta`` must never hash identically."""
    base = Phase10RunConfig(
        entry_exit_price_max_staleness=timedelta(minutes=30),
        cost_bps=Decimal(100),
        max_concurrent_positions=10,
        high_convergence_surprisal_threshold=Decimal("3.0"),
        min_exit_specialist_score=Decimal(70),
        max_hold_duration=timedelta(hours=6),
        contemporaneous_match_max_delta=timedelta(minutes=2),
    )
    changed = Phase10RunConfig(
        entry_exit_price_max_staleness=timedelta(minutes=30),
        cost_bps=Decimal(100),
        max_concurrent_positions=10,
        high_convergence_surprisal_threshold=Decimal("3.0"),
        min_exit_specialist_score=Decimal(70),
        max_hold_duration=timedelta(hours=6),
        contemporaneous_match_max_delta=timedelta(minutes=5),
    )
    assert base.config_hash() != changed.config_hash()
