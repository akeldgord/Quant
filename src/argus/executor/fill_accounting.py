"""argus.executor.fill_accounting — MASTER_SPEC.md section 79 (ACTUAL
FILL ACCOUNTING), Phase 6 (``argus-phase-6-001``), evidence-reference
fields added by FSR-02 (``argus-final-spec-recovery-001``).

Provider quote/response is NEVER canonical fill accounting. Confirmed
chain balance deltas always win; quoted/simulated provenance is
retained separately, never discarded, and any value not yet evidenced
stays explicitly ``None`` -- never fabricated from an earlier-stage
value.

``transaction_signature``/``slot``/``confirmation_state`` identify
exactly which confirmed transaction (if any) the ``actual_*`` values were
reconstructed from, and at what commitment level -- so "actual evidence"
can never mean "a value that happens to be present" without also meaning
"traceable to a specific confirmed chain transaction."
"""

from __future__ import annotations

from dataclasses import dataclass

# Commitment/resolution level of this evidence's actual_*/network_fee_raw
# fields. ``UNKNOWN`` means the submitted transaction's outcome has not
# yet been observed on chain (never a stand-in for "assume success").
CONFIRMATION_UNKNOWN = "UNKNOWN"
CONFIRMATION_PROCESSED = "PROCESSED"
CONFIRMATION_CONFIRMED = "CONFIRMED"
CONFIRMATION_FINALIZED = "FINALIZED"
CONFIRMATION_FAILED = "FAILED"

ALL_CONFIRMATION_STATES = frozenset(
    {
        CONFIRMATION_UNKNOWN,
        CONFIRMATION_PROCESSED,
        CONFIRMATION_CONFIRMED,
        CONFIRMATION_FINALIZED,
        CONFIRMATION_FAILED,
    }
)


@dataclass(frozen=True)
class FillEvidence:
    quoted_input_raw: int | None = None
    quoted_output_raw: int | None = None
    simulated_input_raw: int | None = None
    simulated_output_raw: int | None = None
    actual_input_raw: int | None = None
    actual_output_raw: int | None = None
    network_fee_raw: int | None = None
    priority_fee_raw: int | None = None
    tip_raw: int | None = None
    rent_raw: int | None = None

    transaction_signature: str | None = None
    slot: int | None = None
    confirmation_state: str | None = None

    @property
    def canonical_input_raw(self) -> int | None:
        """The confirmed chain-derived value wins; quote/simulation are
        never substituted when actual evidence is missing -- an
        explicit ``None`` instead."""
        return self.actual_input_raw

    @property
    def canonical_output_raw(self) -> int | None:
        return self.actual_output_raw
