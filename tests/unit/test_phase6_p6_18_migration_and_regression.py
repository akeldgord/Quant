"""P6-18 (SPEC_BLOCKING): prior-phase regression and schema integrity --
orchestrator instruction ``argus-phase-6-001``.

Migration ``0024`` is additive on top of ``0023`` and is the single
alembic head; every Phase 6 domain model matches its migration's table
name. The remainder of this row (full pytest, ruff, format, mypy,
checkpoint/bundle validators) is satisfied by actually running those
tools, recorded in the Phase 6 checkpoint -- not re-implemented as a
test here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_migration_0024_down_revision_is_0023() -> None:
    module_globals: dict = {}
    migration_path = (
        _REPO_ROOT / "migrations" / "versions" / "0024_phase6_hardened_isolated_executor.py"
    )
    exec(compile(migration_path.read_text(), str(migration_path), "exec"), module_globals)
    assert module_globals["revision"] == "0024"
    assert module_globals["down_revision"] == "0023"


def test_alembic_has_exactly_one_head_and_it_is_0024() -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", "heads"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"expected exactly one alembic head, got: {heads}"
    assert "0024" in heads[0]


def test_all_eight_phase6_domain_models_import_cleanly() -> None:
    from argus.domain.execution_attestations import ExecutionAttestation
    from argus.domain.execution_fills import ExecutionFill
    from argus.domain.execution_intent_transitions import ExecutionIntentTransition
    from argus.domain.execution_intents import ExecutionIntent
    from argus.domain.executor_leases import ExecutorLease
    from argus.domain.live_positions import LivePosition
    from argus.domain.risk_exit_events import RiskExitEvent
    from argus.domain.token_safety_assessments import TokenSafetyAssessment

    expected_tables = {
        ExecutorLease: "executor_leases",
        ExecutionIntent: "execution_intents",
        ExecutionIntentTransition: "execution_intent_transitions",
        ExecutionAttestation: "execution_attestations",
        ExecutionFill: "execution_fills",
        LivePosition: "live_positions",
        RiskExitEvent: "risk_exit_events",
        TokenSafetyAssessment: "token_safety_assessments",
    }
    for model, table_name in expected_tables.items():
        assert model.__tablename__ == table_name
