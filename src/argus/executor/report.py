"""argus.executor.report — MASTER_SPEC.md section 82 (MAINNET CANARY),
Phase 6 (``argus-phase-6-001``), P6-17.

Honest disposition reporting: no claim of live readiness beyond actual
evidence. ``LIVE_CANARY_PASSED`` and ``LIVE_ARMED`` are ALWAYS false in
every report this module can produce -- there is no parameter or code
path here that can set either to true, since doing so requires a
human-authorized mainnet canary and a real external arm file this
codebase never creates or modifies. ``LIVE_READY_SOFTWARE`` may be true
only when every one of the caller-supplied software criteria is itself
true, and only when at least one criterion was actually supplied (an
empty criteria set is never silently "ready").
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Phase6Disposition:
    live_ready_software: bool
    live_canary_passed: bool
    live_armed: bool
    software_criteria: dict[str, bool]
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "LIVE_READY_SOFTWARE": self.live_ready_software,
            "LIVE_CANARY_PASSED": self.live_canary_passed,
            "LIVE_ARMED": self.live_armed,
            "software_criteria": dict(self.software_criteria),
            "limitations": list(self.limitations),
        }


def build_disposition(
    *, software_criteria: dict[str, bool], limitations: tuple[str, ...] = ()
) -> Phase6Disposition:
    """``live_canary_passed``/``live_armed`` are unconditionally
    ``False`` -- this function has no parameter that could ever set
    either to ``True``."""
    return Phase6Disposition(
        live_ready_software=bool(software_criteria) and all(software_criteria.values()),
        live_canary_passed=False,
        live_armed=False,
        software_criteria=dict(software_criteria),
        limitations=limitations,
    )
