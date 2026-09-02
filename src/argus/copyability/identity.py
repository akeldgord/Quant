"""M1 (identity/times/units) — MASTER_SPEC.md sections 46-52, Phase 5
(``argus-phase-5-001``).

Shared primitives every Phase 5 mechanic builds on: the evidence-class
enum, the stable evidence-manifest digest used for snapshot identity
(``argus.domain.wallet_copyability_snapshots``/
``opportunity_readiness_snapshots``), and the point-in-time cutoff
predicate every loader in ``argus.copyability.loaders`` applies before a
row is allowed to contribute to a computation.

Point-in-time discipline (this instruction's own explicit rule): "Outcome
summaries at cutoff C include only sources created/known by C and
terminal/response/effective times <= C." ``known_by_cutoff`` is the single
place this rule is enforced so every mechanic applies it identically.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

EvidenceClass = Literal["AUTHENTIC_PROSPECTIVE", "HISTORICAL", "REPLAY", "SYNTHETIC", "UNKNOWN"]

EVIDENCE_CLASS_AUTHENTIC_PROSPECTIVE: EvidenceClass = "AUTHENTIC_PROSPECTIVE"
EVIDENCE_CLASS_HISTORICAL: EvidenceClass = "HISTORICAL"
EVIDENCE_CLASS_REPLAY: EvidenceClass = "REPLAY"
EVIDENCE_CLASS_SYNTHETIC: EvidenceClass = "SYNTHETIC"
EVIDENCE_CLASS_UNKNOWN: EvidenceClass = "UNKNOWN"

# HISTORICAL/REPLAY/SYNTHETIC/UNKNOWN can never become AUTHENTIC_PROSPECTIVE
# via filename, report mode, or later import (M7's own explicit rule) --
# this frozenset is the one place "is this row eligible for authentic
# prospective selection" is decided.
SELECTION_ELIGIBLE_EVIDENCE_CLASSES = frozenset({EVIDENCE_CLASS_AUTHENTIC_PROSPECTIVE})


@dataclass(frozen=True)
class SourceRef:
    """One identified, typed evidence row -- the atomic unit every
    ``contributing_source_ids``/``excluded_source_ids`` entry and the
    evidence-manifest digest are built from."""

    source_type: str
    source_id: str

    def as_dict(self) -> dict:
        return {"type": self.source_type, "id": self.source_id}


@dataclass(frozen=True)
class ExcludedSourceRef:
    ref: SourceRef
    reason: str

    def as_dict(self) -> dict:
        return {"type": self.ref.source_type, "id": self.ref.source_id, "reason": self.reason}


REASON_DISCOVERY_CONTAMINATED = "DISCOVERY_CONTAMINATED"
REASON_FUTURE_KNOWLEDGE = "FUTURE_KNOWLEDGE"
REASON_NOT_AUTHENTIC_PROSPECTIVE = "EVIDENCE_CLASS_NOT_AUTHENTIC_PROSPECTIVE"
REASON_OWN_FUTURE_OUTCOME = "OPPORTUNITYS_OWN_FUTURE_OUTCOME"
REASON_DUPLICATE = "DUPLICATE_EVENT"


def known_by_cutoff(
    *,
    created_at: datetime | None,
    effective_at: datetime | None,
    cutoff: datetime,
) -> bool:
    """True iff a row is safe to use for a computation as-of ``cutoff``:
    it must have been recorded (``created_at``) by the cutoff, AND its own
    substantive/terminal/response/effective time (``effective_at``) must
    also be <= cutoff -- a row recorded early but describing a still-future
    event is not "known" in the M1 sense. Either timestamp missing (not
    yet recorded / not yet terminal) means "not yet known," which is
    always safely excluded rather than guessed."""
    if created_at is None or effective_at is None:
        return False
    return created_at <= cutoff and effective_at <= cutoff


def evidence_manifest_digest(source_ids: list[SourceRef]) -> str:
    """Stable SHA-256 hex digest over the exact sorted set of contributing
    source identities -- part of a Phase 5 snapshot's own persisted
    identity (P5-09), not merely descriptive metadata. Sorted by
    (type, id) so insertion order never changes the digest."""
    sorted_ids = sorted((ref.source_type, ref.source_id) for ref in source_ids)
    canonical = json.dumps(sorted_ids, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
