"""P5-11 (SPEC_BLOCKING): consume CF-P4-01 -- explicit output-directory
option on ``scripts/argus_phase4_replay_demo.py``, orchestrator
instruction ``argus-phase-5-001``. Loaded the same way ``tests/
integration/test_replay_demo_isolation.py`` loads the script (it defines
no module-level side effects), so no subprocess/database is required for
this module's own path-validation-only coverage.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "argus_phase4_replay_demo.py"

_spec = importlib.util.spec_from_file_location("argus_phase4_replay_demo_p5_11_unit", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
replay_demo = importlib.util.module_from_spec(_spec)
sys.modules["argus_phase4_replay_demo_p5_11_unit"] = replay_demo
_spec.loader.exec_module(replay_demo)


def test_two_default_invocations_use_separate_destinations(tmp_path: Path) -> None:
    first = replay_demo.default_output_dir()
    second = replay_demo.default_output_dir()
    assert first != second
    # Neither default lives inside the tracked repository at all.
    assert REPO_ROOT not in first.parents
    assert REPO_ROOT not in second.parents


def test_explicit_tmp_output_succeeds(tmp_path: Path) -> None:
    results_path = replay_demo.resolve_results_path(tmp_path)
    assert results_path == tmp_path / replay_demo.RESULTS_FILENAME
    assert not results_path.exists()


def test_existing_sentinel_target_fails_with_bytes_unchanged(tmp_path: Path) -> None:
    sentinel_bytes = b'{"sentinel": true}'
    target = tmp_path / replay_demo.RESULTS_FILENAME
    target.write_bytes(sentinel_bytes)

    with pytest.raises(replay_demo.ExistingReplayOutputFileError):
        replay_demo.resolve_results_path(tmp_path)

    assert target.read_bytes() == sentinel_bytes


def test_no_overwrite_flag_exists_on_the_parser() -> None:
    args = replay_demo._parse_args(["--output-dir", "/tmp/whatever"])
    assert not hasattr(args, "overwrite")


def test_path_validation_creates_missing_output_dir() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as base:
        nested = Path(base) / "does" / "not" / "exist" / "yet"
        results_path = replay_demo.resolve_results_path(nested)
        assert nested.is_dir()
        assert results_path.parent == nested


def test_existing_tracked_historical_evidence_files_are_never_referenced_by_this_script() -> None:
    """The module no longer defines a module-level EVIDENCE_DIR/
    RESULTS_PATH constant pointing at a tracked orchestration path --
    proves there is no remaining code path that could regenerate a prior
    round's frozen evidence file merely by importing this module."""
    assert not hasattr(replay_demo, "EVIDENCE_DIR")
    assert not hasattr(replay_demo, "RESULTS_PATH")
