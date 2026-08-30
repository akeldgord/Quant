"""Tests for scripts/argus_orchestrator_watch.py.

Real temporary git repositories are used for all git-logic scenarios (no
mocking of git itself) so the tests exercise the actual fetch/pull/diff/
merge-base commands the watcher relies on. The Claude CLI is always mocked
via an injected runner callable -- these tests never invoke a real `claude`
process and never spend Claude-model tokens.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "argus_orchestrator_watch.py"
_spec = importlib.util.spec_from_file_location("argus_orchestrator_watch", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
watch = importlib.util.module_from_spec(_spec)
sys.modules["argus_orchestrator_watch"] = watch
_spec.loader.exec_module(watch)


BRANCH = "main"

INITIAL_INSTRUCTIONS = """\
INSTRUCTION_ID: bootstrap
ISSUED_AT:
TARGET_COMMIT:
AUTHORIZED_ACTION: NONE
AUTHORIZED_PHASE: NONE
STATUS: NO_INSTRUCTION

No orchestrator instruction has been issued through GitHub yet.
"""

INITIAL_HANDOFF = """\
HANDOFF_ID: handoff-0000-initial
UTC_TIMESTAMP: 2026-01-01T00:00:00Z
LAST_ORCHESTRATOR_INSTRUCTION_ID: none
CHECKPOINT_PATH: orchestration/checkpoints/none.md
BUNDLE_PATH: orchestration/bundles/none.txt
"""


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"{cmd} failed in {cwd}: {result.stderr}"
    return result


def _init_git_identity(repo: Path) -> None:
    _run(["git", "config", "user.email", "test@example.com"], repo)
    _run(["git", "config", "user.name", "Test"], repo)


def _write(repo: Path, relpath: str, content: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def make_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a bare 'origin' repo and a working clone, with the baseline
    orchestration files committed and pushed. Returns (origin, work)."""
    origin = tmp_path / "origin.git"
    _run(["git", "init", "--bare", "-b", BRANCH, str(origin)], tmp_path)

    seed = tmp_path / "seed"
    _run(["git", "init", "-b", BRANCH, str(seed)], tmp_path)
    _init_git_identity(seed)
    # The watcher writes its own state/lock/log files under runtime/ inside
    # repo_root -- ignore that directory here just like the real repo does,
    # so those files never make the post-run worktree look dirty.
    _write(seed, ".gitignore", "runtime/\n")
    _write(seed, "MASTER_SPEC.md", "spec\n")
    _write(seed, "docs/BUILD_STATE.md", "```yaml\ncurrent_phase: 0\n```\n")
    _write(seed, "orchestration/ORCHESTRATOR_INSTRUCTIONS.md", INITIAL_INSTRUCTIONS)
    _write(seed, "orchestration/AGENT_HANDOFF.md", INITIAL_HANDOFF)
    _write(seed, "orchestration/checkpoints/none.md", "n/a\n")
    _write(seed, "orchestration/bundles/none.txt", "n/a\n")
    _run(["git", "add", "-A"], seed)
    _run(["git", "commit", "-m", "seed"], seed)
    _run(["git", "remote", "add", "origin", str(origin)], seed)
    _run(["git", "push", "-u", "origin", BRANCH], seed)

    work = tmp_path / "work"
    _run(["git", "clone", str(origin), str(work)], tmp_path)
    _run(["git", "checkout", BRANCH], work)
    _init_git_identity(work)
    return origin, work


def push_instruction(
    origin: Path,
    tmp_path: Path,
    *,
    instruction_id: str,
    status: str,
    target_commit: str,
    label: str,
    authorized_phase: str = "0",
) -> None:
    """Simulate the orchestrator committing ORCHESTRATOR_INSTRUCTIONS.md
    through GitHub: clone origin fresh, edit, commit, push -- independent of
    the watcher's own `work` clone, exactly like a real remote edit."""
    clone = tmp_path / f"orchestrator_clone_{label}"
    _run(["git", "clone", str(origin), str(clone)], tmp_path)
    _run(["git", "checkout", BRANCH], clone)
    _init_git_identity(clone)
    text = (
        f"INSTRUCTION_ID: {instruction_id}\n"
        "ISSUED_AT: 2026-01-01T00:00:00Z\n"
        f"TARGET_COMMIT: {target_commit}\n"
        "AUTHORIZED_ACTION: TEST\n"
        f"AUTHORIZED_PHASE: {authorized_phase}\n"
        f"STATUS: {status}\n"
    )
    _write(clone, "orchestration/ORCHESTRATOR_INSTRUCTIONS.md", text)
    _run(["git", "add", "-A"], clone)
    _run(["git", "commit", "-m", f"orchestrator: {label}"], clone)
    _run(["git", "push", "origin", BRANCH], clone)


def make_config(work: Path, **overrides: Any) -> watch.WatcherConfig:
    return watch.WatcherConfig(repo_root=work, branch=BRANCH, **overrides)


class FakeClaudeRunner:
    """Records calls; optionally performs a side effect simulating what a
    real Claude run would do (commit+push a handoff), controlled per-test."""

    def __init__(self, side_effect: Any = None, returncode: int = 0) -> None:
        self.calls = 0
        self.side_effect = side_effect
        self.returncode = returncode

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls += 1
        if self.side_effect is not None:
            self.side_effect(kwargs.get("cwd"))
        return subprocess.CompletedProcess(cmd, returncode=self.returncode, stdout="", stderr="")


def do_successful_handoff(work: Path, instruction_id: str) -> None:
    """Simulate Claude completing authorized work: write a new handoff +
    checkpoint/bundle, commit, push."""
    _write(work, "orchestration/checkpoints/done.md", "checkpoint\n")
    _write(work, "orchestration/bundles/done.txt", "bundle\n")
    _write(
        work,
        "orchestration/AGENT_HANDOFF.md",
        "HANDOFF_ID: handoff-0001-done\n"
        "UTC_TIMESTAMP: 2026-01-02T00:00:00Z\n"
        f"LAST_ORCHESTRATOR_INSTRUCTION_ID: {instruction_id}\n"
        "CHECKPOINT_PATH: orchestration/checkpoints/done.md\n"
        "BUNDLE_PATH: orchestration/bundles/done.txt\n",
    )
    _run(["git", "add", "-A"], work)
    _run(["git", "commit", "-m", "claude: authorized work complete"], work)
    _run(["git", "push", "origin", BRANCH], work)


# ---------------------------------------------------------------------
# 1. NO_INSTRUCTION does not launch
# ---------------------------------------------------------------------


def test_no_instruction_does_not_launch(tmp_path: Path) -> None:
    _origin, work = make_repo(tmp_path)
    runner = FakeClaudeRunner()
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_status == "IDLE"
    assert state.last_processed_instruction_id is None


# ---------------------------------------------------------------------
# 2. ACTIVE new instruction launches
# ---------------------------------------------------------------------


def test_active_new_instruction_launches(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-1", status="ACTIVE", target_commit=head, label="a"
    )

    runner = FakeClaudeRunner(side_effect=lambda cwd: do_successful_handoff(Path(cwd), "instr-1"))
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 1
    assert state.current_status == "COMPLETED"
    assert state.last_processed_instruction_id == "instr-1"
    assert state.current_instruction_id is None


# ---------------------------------------------------------------------
# 3. same instruction cannot run twice
# ---------------------------------------------------------------------


def test_same_instruction_does_not_relaunch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-1", status="ACTIVE", target_commit=head, label="a"
    )

    runner = FakeClaudeRunner(side_effect=lambda cwd: do_successful_handoff(Path(cwd), "instr-1"))
    config = make_config(work)

    state1 = watch.tick(config, claude_runner=runner)
    assert state1.current_status == "COMPLETED"
    assert runner.calls == 1

    # Same ACTIVE instruction is still sitting in the file (orchestrator
    # hasn't superseded it) -- a second tick must not relaunch.
    state2 = watch.tick(config, claude_runner=runner)
    assert runner.calls == 1
    assert state2.last_processed_instruction_id == "instr-1"


# ---------------------------------------------------------------------
# 4. dirty worktree blocks launch
# ---------------------------------------------------------------------


def test_dirty_worktree_blocks_launch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-1", status="ACTIVE", target_commit=head, label="a"
    )
    (work / "untracked_dirt.txt").write_text("uncommitted\n")

    runner = FakeClaudeRunner()
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_instruction_id is None
    assert state.current_status == "IDLE"


# ---------------------------------------------------------------------
# 5. pull failure blocks launch
# ---------------------------------------------------------------------


def test_pull_failure_blocks_launch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-1", status="ACTIVE", target_commit=head, label="a"
    )

    # Make the local branch diverge from origin (a local-only commit) so
    # `git pull --ff-only` cannot fast-forward.
    _write(work, "local_only.txt", "local divergence\n")
    _run(["git", "add", "-A"], work)
    _run(["git", "commit", "-m", "local divergent commit"], work)

    runner = FakeClaudeRunner()
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_status == "IDLE"


# ---------------------------------------------------------------------
# 6. target mismatch blocks launch
# ---------------------------------------------------------------------


def test_target_commit_not_ancestor_blocks_launch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    # A commit that exists but lives on an unrelated, unmerged branch.
    other = tmp_path / "other_branch_clone"
    _run(["git", "clone", str(origin), str(other)], tmp_path)
    _init_git_identity(other)
    _run(["git", "checkout", "-b", "unrelated", BRANCH], other)
    _write(other, "unrelated_file.txt", "x\n")
    _run(["git", "add", "-A"], other)
    _run(["git", "commit", "-m", "unrelated work"], other)
    unrelated_commit = _run(["git", "rev-parse", "HEAD"], other).stdout.strip()

    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-1",
        status="ACTIVE",
        target_commit=unrelated_commit,
        label="a",
    )

    runner = FakeClaudeRunner()
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_instruction_id is None


def test_target_commit_with_unreviewed_diff_blocks_launch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()

    # Orchestrator's instruction commit also (incorrectly) touches an
    # implementation file, not just ORCHESTRATOR_INSTRUCTIONS.md.
    clone = tmp_path / "orchestrator_clone_bad"
    _run(["git", "clone", str(origin), str(clone)], tmp_path)
    _run(["git", "checkout", BRANCH], clone)
    _init_git_identity(clone)
    _write(clone, "MASTER_SPEC.md", "spec (unreviewed edit)\n")
    _write(
        clone,
        "orchestration/ORCHESTRATOR_INSTRUCTIONS.md",
        "INSTRUCTION_ID: instr-1\nISSUED_AT: x\nTARGET_COMMIT: "
        + head
        + "\nAUTHORIZED_ACTION: TEST\nAUTHORIZED_PHASE: 0\nSTATUS: ACTIVE\n",
    )
    _run(["git", "add", "-A"], clone)
    _run(["git", "commit", "-m", "orchestrator: sneaks in an implementation change"], clone)
    _run(["git", "push", "origin", BRANCH], clone)

    runner = FakeClaudeRunner()
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_instruction_id is None


# ---------------------------------------------------------------------
# 7. stale RUNNING state does not relaunch
# ---------------------------------------------------------------------


def test_stale_running_state_does_not_relaunch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-1", status="ACTIVE", target_commit=head, label="a"
    )

    config = make_config(work)
    watch.write_state(
        config.state_path,
        watch.WatcherState(current_instruction_id="instr-1", current_status="RUNNING"),
    )

    runner = FakeClaudeRunner()
    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 8. pause file blocks launch
# ---------------------------------------------------------------------


def test_pause_file_blocks_launch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-1", status="ACTIVE", target_commit=head, label="a"
    )

    config = make_config(work)
    config.pause_path.parent.mkdir(parents=True, exist_ok=True)
    config.pause_path.write_text("")

    runner = FakeClaudeRunner()
    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_status == "IDLE"
    # Confirm it really didn't even fetch/pull: local HEAD unchanged.
    assert _run(["git", "rev-parse", "HEAD"], work).stdout.strip() == head


# ---------------------------------------------------------------------
# 9. new matching handoff marks completed
# ---------------------------------------------------------------------


def test_matching_handoff_marks_completed(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-9", status="ACTIVE", target_commit=head, label="a"
    )
    runner = FakeClaudeRunner(side_effect=lambda cwd: do_successful_handoff(Path(cwd), "instr-9"))
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "COMPLETED"
    assert state.last_exit_code == 0


# ---------------------------------------------------------------------
# 10. missing/mismatched handoff marks failed
# ---------------------------------------------------------------------


def test_missing_handoff_marks_failed(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-10", status="ACTIVE", target_commit=head, label="a"
    )
    # Claude "runs" but never updates AGENT_HANDOFF.md at all.
    runner = FakeClaudeRunner(side_effect=None)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 1
    assert state.current_status == "FAILED"
    assert state.last_processed_instruction_id is None


def test_mismatched_handoff_instruction_id_marks_failed(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-11", status="ACTIVE", target_commit=head, label="a"
    )
    # Claude updates the handoff, but references the WRONG instruction id.
    runner = FakeClaudeRunner(
        side_effect=lambda cwd: do_successful_handoff(Path(cwd), "some-other-id")
    )
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


def test_dirty_tree_after_claude_run_marks_failed(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-12", status="ACTIVE", target_commit=head, label="a"
    )

    def leave_dirty_and_handoff(cwd: Any) -> None:
        do_successful_handoff(Path(cwd), "instr-12")
        (Path(cwd) / "leftover.txt").write_text("oops\n")

    runner = FakeClaudeRunner(side_effect=leave_dirty_and_handoff)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# Remediation round: bug-fix regression tests
#
# Four defects found on independent audit, each with a dedicated
# adversarial test proving the *old* behavior would have wrongly allowed
# the run and the *new* behavior correctly blocks/fails it:
#   A. AUTHORIZED_PHASE was parsed but never validated -- a malformed or
#      out-of-sequence phase authorization reached Claude unchecked.
#   B. LAST_ORCHESTRATOR_INSTRUCTION_ID matching used substring containment
#      (`in`) instead of exact equality -- a stale/unrelated field value
#      that merely contained the instruction id as a substring would
#      false-positive match.
#   C. CHECKPOINT_PATH/BUNDLE_PATH were only checked for existence, not
#      that they were part of this run's own new commits -- stale
#      pre-existing evidence at the same path would pass.
#   D. Restart recovery only treated a stale RUNNING state as a crash;
#      a stale CLAIMED state (crash between claiming and actually
#      launching Claude) was silently ignored forever, with no FAILED
#      transition and no log event.
# ---------------------------------------------------------------------


def test_authorized_phase_skip_ahead_blocks_launch(tmp_path: Path) -> None:
    """(A) current_phase is 0; AUTHORIZED_PHASE: 2 skips ahead and must be
    rejected -- this is precisely a case of Phase 1 (or later) being
    authorized when it must not be."""
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-phase-skip",
        status="ACTIVE",
        target_commit=head,
        label="a",
        authorized_phase="2",
    )

    runner = FakeClaudeRunner()
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_instruction_id is None
    assert state.current_status == "IDLE"


def test_authorized_phase_malformed_blocks_launch(tmp_path: Path) -> None:
    """(A) A non-numeric AUTHORIZED_PHASE must never reach Claude."""
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-phase-bad",
        status="ACTIVE",
        target_commit=head,
        label="a",
        authorized_phase="one",
    )

    runner = FakeClaudeRunner()
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_instruction_id is None


def test_authorized_phase_same_or_next_is_allowed(tmp_path: Path) -> None:
    """(A) Sanity check: current_phase (re-authorizing current work) and
    current_phase + 1 (the legitimate next-phase case) are both allowed --
    the guard blocks skip-ahead, not ordinary progress."""
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-phase-ok",
        status="ACTIVE",
        target_commit=head,
        label="a",
        authorized_phase="1",
    )

    runner = FakeClaudeRunner(
        side_effect=lambda cwd: do_successful_handoff(Path(cwd), "instr-phase-ok")
    )
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 1
    assert state.current_status == "COMPLETED"


def test_handoff_substring_false_positive_now_fails(tmp_path: Path) -> None:
    """(B) LAST_ORCHESTRATOR_INSTRUCTION_ID = 'instr-12' textually contains
    instruction id 'instr-1' as a substring but is NOT the same instruction.
    The old `in`-based check would have wrongly accepted this."""
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-1", status="ACTIVE", target_commit=head, label="a"
    )

    def stale_substring_handoff(cwd: Any) -> None:
        cwd_path = Path(cwd)
        _write(cwd_path, "orchestration/checkpoints/done.md", "checkpoint\n")
        _write(cwd_path, "orchestration/bundles/done.txt", "bundle\n")
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            "HANDOFF_ID: handoff-0001-done\n"
            "UTC_TIMESTAMP: 2026-01-02T00:00:00Z\n"
            "LAST_ORCHESTRATOR_INSTRUCTION_ID: instr-12\n"
            "CHECKPOINT_PATH: orchestration/checkpoints/done.md\n"
            "BUNDLE_PATH: orchestration/bundles/done.txt\n",
        )
        _run(["git", "add", "-A"], cwd_path)
        _run(["git", "commit", "-m", "claude: mismatched instruction id"], cwd_path)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=stale_substring_handoff)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


def test_stale_preexisting_checkpoint_bundle_marks_failed(tmp_path: Path) -> None:
    """(C) CHECKPOINT_PATH/BUNDLE_PATH point at files that already existed
    (committed in the seed, untouched by this run) rather than files this
    run actually produced. Existence alone must not be accepted as
    evidence -- this is exactly 'stale checkpoint/bundle data'."""
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-stale",
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def point_at_preexisting_evidence(cwd: Any) -> None:
        cwd_path = Path(cwd)
        # Deliberately do NOT write new checkpoint/bundle files -- point at
        # the ones that already existed in the seed commit instead.
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            "HANDOFF_ID: handoff-0001-stale\n"
            "UTC_TIMESTAMP: 2026-01-02T00:00:00Z\n"
            "LAST_ORCHESTRATOR_INSTRUCTION_ID: instr-stale\n"
            "CHECKPOINT_PATH: orchestration/checkpoints/none.md\n"
            "BUNDLE_PATH: orchestration/bundles/none.txt\n",
        )
        _run(["git", "add", "-A"], cwd_path)
        _run(["git", "commit", "-m", "claude: points at stale evidence"], cwd_path)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=point_at_preexisting_evidence)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


def test_claimed_state_restart_marks_failed(tmp_path: Path) -> None:
    """(D) A crash between CLAIMED and RUNNING must be treated as stale on
    restart, exactly like a stale RUNNING state -- not silently ignored."""
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-claimed",
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    config = make_config(work)
    watch.write_state(
        config.state_path,
        watch.WatcherState(current_instruction_id="instr-claimed", current_status="CLAIMED"),
    )

    runner = FakeClaudeRunner()
    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 11. two watcher instances cannot run
# ---------------------------------------------------------------------


def test_second_watcher_instance_cannot_acquire_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "watcher.lock"
    first = watch.acquire_lock(lock_path)
    try:
        with pytest.raises(watch.LockUnavailable):
            watch.acquire_lock(lock_path)
    finally:
        watch.release_lock(first)

    # Lock is free again after release.
    second = watch.acquire_lock(lock_path)
    watch.release_lock(second)


# ---------------------------------------------------------------------
# Pure parsing unit tests
# ---------------------------------------------------------------------


def test_parse_instructions_basic() -> None:
    fields = watch.parse_instructions(INITIAL_INSTRUCTIONS)
    assert fields.instruction_id == "bootstrap"
    assert fields.status == "NO_INSTRUCTION"
    assert fields.target_commit == ""


def test_parse_handoff_basic() -> None:
    fields = watch.parse_handoff(INITIAL_HANDOFF)
    assert fields["HANDOFF_ID"] == "handoff-0000-initial"
    assert fields["LAST_ORCHESTRATOR_INSTRUCTION_ID"] == "none"
