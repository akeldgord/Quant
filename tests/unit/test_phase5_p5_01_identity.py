"""P5-01 (SPEC_BLOCKING) unit-level coverage: as-of evidence/provenance
primitives -- MASTER_SPEC.md M1, ``argus.copyability.identity``,
orchestrator instruction ``argus-phase-5-001``. Full production-loader
point-in-time behavior is covered by
``tests/integration/test_phase5_persistence_and_report.py`` (DB-backed);
this module covers the shared cutoff predicate and manifest-digest
primitives every loader calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from argus.copyability.identity import (
    SELECTION_ELIGIBLE_EVIDENCE_CLASSES,
    SourceRef,
    evidence_manifest_digest,
    known_by_cutoff,
)

CUTOFF = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def test_known_by_cutoff_true_when_both_times_at_or_before_cutoff() -> None:
    assert known_by_cutoff(created_at=CUTOFF, effective_at=CUTOFF, cutoff=CUTOFF) is True
    assert (
        known_by_cutoff(
            created_at=CUTOFF - timedelta(seconds=1),
            effective_at=CUTOFF - timedelta(seconds=1),
            cutoff=CUTOFF,
        )
        is True
    )


def test_known_by_cutoff_false_one_instant_after() -> None:
    just_after = CUTOFF + timedelta(microseconds=1)
    assert known_by_cutoff(created_at=just_after, effective_at=CUTOFF, cutoff=CUTOFF) is False
    assert known_by_cutoff(created_at=CUTOFF, effective_at=just_after, cutoff=CUTOFF) is False


def test_known_by_cutoff_false_when_either_timestamp_missing() -> None:
    assert known_by_cutoff(created_at=None, effective_at=CUTOFF, cutoff=CUTOFF) is False
    assert known_by_cutoff(created_at=CUTOFF, effective_at=None, cutoff=CUTOFF) is False


def test_evidence_manifest_digest_stable_under_reordering() -> None:
    refs_a = [SourceRef("swap", "1"), SourceRef("shadow_position", "2")]
    refs_b = [SourceRef("shadow_position", "2"), SourceRef("swap", "1")]
    assert evidence_manifest_digest(refs_a) == evidence_manifest_digest(refs_b)


def test_evidence_manifest_digest_changes_with_different_evidence() -> None:
    refs_a = [SourceRef("swap", "1")]
    refs_b = [SourceRef("swap", "2")]
    assert evidence_manifest_digest(refs_a) != evidence_manifest_digest(refs_b)


def test_only_authentic_prospective_is_selection_eligible() -> None:
    assert frozenset({"AUTHENTIC_PROSPECTIVE"}) == SELECTION_ELIGIBLE_EVIDENCE_CLASSES
    assert "HISTORICAL" not in SELECTION_ELIGIBLE_EVIDENCE_CLASSES
    assert "REPLAY" not in SELECTION_ELIGIBLE_EVIDENCE_CLASSES
    assert "SYNTHETIC" not in SELECTION_ELIGIBLE_EVIDENCE_CLASSES
    assert "UNKNOWN" not in SELECTION_ELIGIBLE_EVIDENCE_CLASSES
