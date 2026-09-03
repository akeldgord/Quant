"""P6-08 (SPEC_BLOCKING): actual fill accounting -- MASTER_SPEC.md
section 79, orchestrator instruction ``argus-phase-6-001``.

Confirmed chain-derived values are canonical; quoted/simulated
provenance is retained separately, never discarded; any value not yet
evidenced stays explicitly ``None``, never fabricated from an
earlier-stage value.
"""

from __future__ import annotations

from argus.executor.fill_accounting import FillEvidence


def test_quote_simulated_actual_can_all_differ_and_are_all_retained() -> None:
    evidence = FillEvidence(
        quoted_input_raw=1_000_000,
        quoted_output_raw=2_000_000,
        simulated_input_raw=1_000_000,
        simulated_output_raw=1_950_000,
        actual_input_raw=1_000_000,
        actual_output_raw=1_900_000,
    )
    assert evidence.quoted_output_raw == 2_000_000
    assert evidence.simulated_output_raw == 1_950_000
    assert evidence.actual_output_raw == 1_900_000


def test_canonical_values_are_the_actual_confirmed_chain_values() -> None:
    evidence = FillEvidence(
        quoted_input_raw=1_000_000,
        quoted_output_raw=2_000_000,
        simulated_input_raw=1_000_000,
        simulated_output_raw=1_950_000,
        actual_input_raw=1_000_000,
        actual_output_raw=1_900_000,
    )
    assert evidence.canonical_input_raw == 1_000_000
    assert evidence.canonical_output_raw == 1_900_000


def test_missing_actual_evidence_is_never_backfilled_from_quote_or_simulation() -> None:
    """The one rule this row exists to enforce: quote/simulation must
    never be silently substituted when the confirmed value is missing."""
    evidence = FillEvidence(
        quoted_input_raw=1_000_000,
        quoted_output_raw=2_000_000,
        simulated_input_raw=1_000_000,
        simulated_output_raw=1_950_000,
        actual_input_raw=None,
        actual_output_raw=None,
    )
    assert evidence.canonical_input_raw is None
    assert evidence.canonical_output_raw is None


def test_all_fields_default_to_none_never_zero() -> None:
    """A default of 0 would be indistinguishable from a real zero-value
    fill -- every unevidenced field must default to an explicit None."""
    evidence = FillEvidence()
    assert evidence.quoted_input_raw is None
    assert evidence.quoted_output_raw is None
    assert evidence.simulated_input_raw is None
    assert evidence.simulated_output_raw is None
    assert evidence.actual_input_raw is None
    assert evidence.actual_output_raw is None
    assert evidence.network_fee_raw is None
    assert evidence.priority_fee_raw is None
    assert evidence.tip_raw is None
    assert evidence.rent_raw is None
    assert evidence.canonical_input_raw is None
    assert evidence.canonical_output_raw is None


def test_fee_tip_rent_are_tracked_as_separate_fields() -> None:
    evidence = FillEvidence(network_fee_raw=5_000, priority_fee_raw=1_000, tip_raw=500, rent_raw=0)
    assert evidence.network_fee_raw == 5_000
    assert evidence.priority_fee_raw == 1_000
    assert evidence.tip_raw == 500
    assert evidence.rent_raw == 0
