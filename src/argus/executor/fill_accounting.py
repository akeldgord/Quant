"""argus.executor.fill_accounting — MASTER_SPEC.md section 79 (ACTUAL
FILL ACCOUNTING), Phase 6 (``argus-phase-6-001``).

Provider quote/response is NEVER canonical fill accounting. Confirmed
chain balance deltas always win; quoted/simulated provenance is
retained separately, never discarded, and any value not yet evidenced
stays explicitly ``None`` -- never fabricated from an earlier-stage
value.
"""

from __future__ import annotations

from dataclasses import dataclass


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

    @property
    def canonical_input_raw(self) -> int | None:
        """The confirmed chain-derived value wins; quote/simulation are
        never substituted when actual evidence is missing -- an
        explicit ``None`` instead."""
        return self.actual_input_raw

    @property
    def canonical_output_raw(self) -> int | None:
        return self.actual_output_raw
