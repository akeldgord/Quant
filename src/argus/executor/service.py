"""argus.executor.service — Phase 6 (``argus-phase-6-001``) orchestration:
ties the pure ``argus.executor.*`` mechanics together into the one honest
software-readiness disposition ``argus executor readiness`` (the CLI
command required by P6-17) reports.

``build_phase6_disposition`` never hardcodes its criteria as trivially
``True`` -- each one is a real runtime assertion against this build's own
constants (state count, terminal-state set, gate count, dispatch default,
capital defaults, scale-in policy), so a future code change that silently
breaks one of these invariants makes the report honestly show it as
unmet rather than continuing to claim readiness.

Exactly like ``argus.executor.report.build_disposition`` itself,
``live_canary_passed``/``live_armed`` can never become ``True`` through
this module -- no code path here touches a real arm file, a real signer,
or a real submission call.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from argus.executor.capital import (
    LIVE_MAX_DAILY_LOSS_SOL,
    LIVE_MAX_SINGLE_TRADE_SOL,
    LIVE_MAX_TOTAL_EXPOSURE_SOL,
)
from argus.executor.dispatch import DispatchGuard, raising_submission
from argus.executor.position_policy import ALLOW_AUTOMATIC_SCALE_IN
from argus.executor.reconciliation import ALL_DIMENSIONS as RECONCILIATION_DIMENSIONS
from argus.executor.report import Phase6Disposition, build_disposition
from argus.executor.risk_gates import GATE_KEYS
from argus.executor.signing import RaisingSigner
from argus.executor.state_machine import (
    STATE_CONFIRMED,
    STATE_FAILED,
    STATE_REJECTED,
    TERMINAL_STATES,
)
from argus.executor.token_safety import ALL_RISK_FLAGS

ALGORITHM_VERSION = "executor_readiness_v1"

# Same "hash every artifact whose code can change the decision" pattern
# established by Phase 5's ``copyability.service.BUILD_HASH`` -- covers
# every Phase 6 module able to change the readiness disposition.
_PHASE6_ARTIFACT_FILENAMES: Final[tuple[str, ...]] = (
    "capital.py",
    "arm.py",
    "signing.py",
    "singleton.py",
    "state_machine.py",
    "idempotency.py",
    "attestation.py",
    "fill_accounting.py",
    "slippage.py",
    "risk_gates.py",
    "position_policy.py",
    "risk_exits.py",
    "token_safety.py",
    "reconciliation.py",
    "dispatch.py",
    "report.py",
    "persistence.py",
    "service.py",
)


def _compute_build_hash() -> str:
    digest = hashlib.sha256()
    module_dir = Path(__file__).parent
    for filename in _PHASE6_ARTIFACT_FILENAMES:
        digest.update((module_dir / filename).read_bytes())
    return digest.hexdigest()


BUILD_HASH: Final[str] = _compute_build_hash()


def _state_machine_matches_spec() -> bool:
    """Section 76's frozen 11-state machine with exactly 3 terminal
    states (REJECTED, CONFIRMED, FAILED)."""
    from argus.domain.execution_intents import EXECUTION_STATES

    return (
        len(EXECUTION_STATES) == 11
        and frozenset({STATE_REJECTED, STATE_CONFIRMED, STATE_FAILED}) == TERMINAL_STATES
    )


def _default_dispatch_guard_never_dispatches() -> bool:
    """Every non-canary/non-live-execution code path must be constructed
    with the raising defaults (section 70/78) -- proven here by
    constructing exactly that default and checking it structurally."""
    guard = DispatchGuard(signer=RaisingSigner())
    return isinstance(guard.signer, RaisingSigner) and guard.submit is raising_submission


def _capital_defaults_are_zero() -> bool:
    """Section 71's zero-default capital configuration: no live trading
    is possible until an operator explicitly raises these away from
    zero."""
    return (
        LIVE_MAX_SINGLE_TRADE_SOL == 0
        and LIVE_MAX_TOTAL_EXPOSURE_SOL == 0
        and LIVE_MAX_DAILY_LOSS_SOL == 0
    )


def _automatic_scale_in_is_prohibited() -> bool:
    return ALLOW_AUTOMATIC_SCALE_IN is False


def _live_risk_gate_count_is_23() -> bool:
    return len(GATE_KEYS) == 23


def _token_safety_flag_count_is_8() -> bool:
    return len(ALL_RISK_FLAGS) == 8


def _reconciliation_dimension_count_is_7() -> bool:
    return len(RECONCILIATION_DIMENSIONS) == 7


def build_phase6_disposition() -> Phase6Disposition:
    """The one function ``argus executor readiness`` calls. Every
    criterion is a live assertion against this build's actual constants,
    never a hardcoded ``True`` -- see this module's own docstring."""
    software_criteria = {
        "state_machine_matches_spec_11_states_3_terminal": _state_machine_matches_spec(),
        "default_dispatch_guard_never_dispatches": _default_dispatch_guard_never_dispatches(),
        "capital_defaults_are_zero": _capital_defaults_are_zero(),
        "automatic_scale_in_prohibited": _automatic_scale_in_is_prohibited(),
        "live_risk_gate_count_is_23": _live_risk_gate_count_is_23(),
        "token_safety_flag_count_is_8": _token_safety_flag_count_is_8(),
        "host_reconciliation_dimension_count_is_7": _reconciliation_dimension_count_is_7(),
    }
    limitations = (
        "a real on-disk-keypair signer (argus.executor.live_signing.FileKeypairSigner, FSR-01) "
        "and a real transaction broadcast adapter (argus.executor.live_submission."
        "SolanaSubmissionClient) exist as of the final-spec-recovery, but are loadable/importable "
        "ONLY from the isolated argus.executor.main process entry point, from an external "
        "operator-controlled key path this coding session never reads, prints, or logs -- proven "
        "by tests/unit/test_fsr01_live_signer_isolation_boundary.py's own AST-based import-graph "
        "check, the same mechanism P6-02's signer isolation test uses",
        "no automated copy-signal/live-trading loop exists that would ever call the real signer/"
        "submission adapter on its own initiative -- risk/safety/sellability gates take typed "
        "evidence as parameters rather than calling a live provider, and argus.executor.main's own "
        "startup sequence never dispatches a transaction regardless of arm-file validity",
        "PostgresLeaseStore and the DB-backed persistence paths are structurally implemented but "
        "unexercised in this sandbox (no reachable Postgres); the executor-singleton concurrency "
        "guarantee is proven instead via InMemoryLeaseStore with two independent simulated callers",
        "LIVE_CANARY_PASSED and LIVE_ARMED are unconditionally false in every report this module "
        "can produce -- no mainnet canary has run (Phase 6.5 is explicitly human-only, never "
        "self-executed) and this module's own code path has no parameter that could ever flip "
        "either to true",
    )
    return build_disposition(software_criteria=software_criteria, limitations=limitations)
