"""Tests for scripts/argus_orchestrator_watch.py.

Real temporary git repositories are used for all git-logic scenarios (no
mocking of git itself) so the tests exercise the actual fetch/pull/diff/
merge-base/log commands the watcher relies on. The Claude CLI is always
mocked via an injected runner callable -- these tests never invoke a real
`claude` process and never spend Claude-model tokens.
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
APPROVES_PHASE: NONE
STATUS: NO_INSTRUCTION

No orchestrator instruction has been issued through GitHub yet.
"""

INITIAL_HANDOFF = """\
HANDOFF_ID: handoff-0000-initial
UTC_TIMESTAMP: 2026-01-01T00:00:00Z
CURRENT_COMMIT: 0000000000000000000000000000000000000000
CURRENT_PHASE: 0
WORK_STATUS: AWAITING_ORCHESTRATOR_INSTRUCTION
LAST_ORCHESTRATOR_INSTRUCTION_ID: none
CHECKPOINT_PATH: orchestration/checkpoints/none.md
BUNDLE_PATH: orchestration/bundles/none.txt
TEST_STATUS: n/a
WORKING_TREE: clean
ORCHESTRATOR_REVIEW_REQUIRED: none
"""

BUILD_STATE_TEXT = (
    "```yaml\ncurrent_phase: 0\nlast_completed_phase: 0\nawaiting_orchestrator_review: true\n```\n"
)


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
    _write(seed, "docs/BUILD_STATE.md", BUILD_STATE_TEXT)
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
    approves_phase: str = "NONE",
    issued_at: str = "2026-01-01T00:00:00Z",
    authorized_action: str = "TEST",
    extra_field: str | None = None,
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
        f"ISSUED_AT: {issued_at}\n"
        f"TARGET_COMMIT: {target_commit}\n"
        f"AUTHORIZED_ACTION: {authorized_action}\n"
        f"AUTHORIZED_PHASE: {authorized_phase}\n"
        f"APPROVES_PHASE: {approves_phase}\n"
        f"STATUS: {status}\n"
    )
    if extra_field:
        text += extra_field + "\n"
    _write(clone, "orchestration/ORCHESTRATOR_INSTRUCTIONS.md", text)
    _run(["git", "add", "-A"], clone)
    _run(["git", "commit", "-m", f"orchestrator: {label}"], clone)
    _run(["git", "push", "origin", BRANCH], clone)


def make_config(
    work: Path, *, seed_idle_state: bool = True, **overrides: Any
) -> watch.WatcherConfig:
    """By default, pre-seed a fresh IDLE state file -- realistic for a
    watcher that has already run at least one tick before an ACTIVE
    instruction ever appears. Tests specifically exercising missing/corrupt/
    invalid state pass seed_idle_state=False to leave that to the test."""
    config = watch.WatcherConfig(repo_root=work, branch=BRANCH, **overrides)
    if seed_idle_state:
        watch.write_state(config.state_path, watch.WatcherState())
    return config


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


# ---------------------------------------------------------------------
# Realistic, structurally-valid checkpoint/bundle/handoff fixture content.
# A one-line placeholder like "checkpoint\n" must no longer count as a
# successful handoff -- these builders produce content that actually
# satisfies validate_checkpoint_content()/validate_bundle_content().
# ---------------------------------------------------------------------


def _checkpoint_text(instruction_id: str, git_commit: str) -> str:
    return f"""{watch.CHECKPOINT_START_MARKER}

PROJECT: ARGUS
SCOPE: Operational tooling remediation (instruction_id={instruction_id})
STATUS: PASS
GIT_COMMIT: {git_commit}

Commands actually run:
- uv run pytest tests/unit/test_orchestrator_watch.py -v

Test results: 10 passed, 0 failed, 0 skipped.

Acceptance criteria: [PASS] all criteria for this instruction were met.

Architectural deviations: NONE.

Known bugs / debt: none new.

Security state: unchanged; no new secrets, no live-execution code touched.

Next specified phase: STOP. Do not begin Phase 1.

{watch.CHECKPOINT_END_MARKER}
"""


def _bundle_text(instruction_id: str, git_commit: str, checkpoint_text: str) -> str:
    return (
        f"ARGUS REVIEW BUNDLE for instruction_id={instruction_id}\n"
        f"STATUS: PASS\nGIT_COMMIT: {git_commit}\nTEST_STATUS: all tests passed\n\n"
        f"{checkpoint_text}\n"
        "Additional review evidence: see checkpoint above for full detail.\n"
    )


def _handoff_text(
    instruction_id: str,
    checkpoint_rel: str,
    bundle_rel: str,
    current_commit: str,
    handoff_id: str,
) -> str:
    return (
        f"HANDOFF_ID: {handoff_id}\n"
        "UTC_TIMESTAMP: 2026-01-02T00:00:00Z\n"
        f"CURRENT_COMMIT: {current_commit}\n"
        "CURRENT_PHASE: 0\n"
        "WORK_STATUS: COMPLETE\n"
        f"LAST_ORCHESTRATOR_INSTRUCTION_ID: {instruction_id}\n"
        f"CHECKPOINT_PATH: {checkpoint_rel}\n"
        f"BUNDLE_PATH: {bundle_rel}\n"
        "TEST_STATUS: all tests passed\n"
        "WORKING_TREE: clean\n"
        "ORCHESTRATOR_REVIEW_REQUIRED: none\n"
    )


def _git_commit_with_trailer(cwd: Path, message: str, instruction_id: str) -> str:
    _run(["git", "add", "-A"], cwd)
    full_message = f"{message}\n\nARGUS-INSTRUCTION-ID: {instruction_id}\n"
    _run(["git", "commit", "-m", full_message], cwd)
    return _run(["git", "rev-parse", "HEAD"], cwd).stdout.strip()


def do_successful_handoff(
    work: Path,
    instruction_id: str,
    *,
    checkpoint_name: str = "done",
    bundle_name: str = "done",
    handoff_id: str = "handoff-0001-done",
) -> str:
    """Simulate Claude completing authorized work: write a new, structurally
    valid handoff + checkpoint/bundle (as newly-added files), commit with the
    required trailer (in two commits, exactly like the real repo's
    "implementation commit" + "hash-fill commit" convention), and push.
    Returns the final pushed commit sha."""
    checkpoint_rel = f"orchestration/checkpoints/{checkpoint_name}.md"
    bundle_rel = f"orchestration/bundles/{bundle_name}.txt"

    placeholder_checkpoint = _checkpoint_text(instruction_id, "PENDING")
    _write(work, checkpoint_rel, placeholder_checkpoint)
    _write(work, bundle_rel, _bundle_text(instruction_id, "PENDING", placeholder_checkpoint))
    _write(
        work,
        "orchestration/AGENT_HANDOFF.md",
        _handoff_text(instruction_id, checkpoint_rel, bundle_rel, "PENDING", handoff_id),
    )
    impl_sha = _git_commit_with_trailer(work, "claude: authorized work complete", instruction_id)

    final_checkpoint = _checkpoint_text(instruction_id, impl_sha)
    _write(work, checkpoint_rel, final_checkpoint)
    _write(work, bundle_rel, _bundle_text(instruction_id, impl_sha, final_checkpoint))
    _write(
        work,
        "orchestration/AGENT_HANDOFF.md",
        _handoff_text(instruction_id, checkpoint_rel, bundle_rel, impl_sha, handoff_id),
    )
    final_sha = _git_commit_with_trailer(work, "docs: fill in commit hash", instruction_id)
    _run(["git", "push", "origin", BRANCH], work)
    return final_sha


# ---------------------------------------------------------------------
# 1. missing state + ACTIVE instruction does not launch
# ---------------------------------------------------------------------


def test_missing_state_with_active_instruction_does_not_launch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-1", status="ACTIVE", target_commit=head, label="a"
    )

    config = make_config(work, seed_idle_state=False)
    assert not config.state_path.exists()
    runner = FakeClaudeRunner()

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_status == "FAILED"
    assert state.current_instruction_id == "instr-1"


# ---------------------------------------------------------------------
# 2. corrupt JSON state does not launch
# ---------------------------------------------------------------------


def test_corrupt_json_state_does_not_launch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-1", status="ACTIVE", target_commit=head, label="a"
    )

    config = make_config(work, seed_idle_state=False)
    config.state_path.parent.mkdir(parents=True, exist_ok=True)
    config.state_path.write_text("{not valid json")

    runner = FakeClaudeRunner()
    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_status == "FAILED"
    # The corrupt file itself must be left untouched for forensic inspection.
    assert config.state_path.read_text() == "{not valid json"


# ---------------------------------------------------------------------
# 3. invalid state schema/status does not launch
# ---------------------------------------------------------------------


def test_invalid_state_status_does_not_launch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-1", status="ACTIVE", target_commit=head, label="a"
    )

    config = make_config(work, seed_idle_state=False)
    config.state_path.parent.mkdir(parents=True, exist_ok=True)
    config.state_path.write_text('{"current_status": "BOGUS_STATUS"}')

    runner = FakeClaudeRunner()
    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_status == "FAILED"


def test_invalid_state_wrong_field_type_does_not_launch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-1", status="ACTIVE", target_commit=head, label="a"
    )

    config = make_config(work, seed_idle_state=False)
    config.state_path.parent.mkdir(parents=True, exist_ok=True)
    config.state_path.write_text('{"current_status": "IDLE", "last_exit_code": "not-an-int"}')

    runner = FakeClaudeRunner()
    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 4. a completed/handoff-recorded instruction cannot replay after state loss
# ---------------------------------------------------------------------


def test_state_loss_after_completion_does_not_replay(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-done",
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    # Simulate a prior successful run whose local state.json was then lost
    # (e.g. runtime/ wiped) -- but AGENT_HANDOFF.md, which is tracked in
    # git, still faithfully records completion.
    _run(["git", "pull", "--ff-only", "origin", BRANCH], work)
    do_successful_handoff(work, "instr-done")

    config = make_config(work, seed_idle_state=False)
    assert not config.state_path.exists()
    runner = FakeClaudeRunner()

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_status == "IDLE"
    assert state.last_processed_instruction_id == "instr-done"


# ---------------------------------------------------------------------
# 5. nonzero Claude exit with otherwise valid handoff/evidence is FAILED
# ---------------------------------------------------------------------


def test_nonzero_exit_with_valid_handoff_is_failed(tmp_path: Path) -> None:
    """This is precisely the originally-reported bug: a failed Claude
    process must not be accepted as COMPLETED just because handoff/evidence
    files happen to look valid."""
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-badexit",
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def produce_valid_handoff_but_fail(cwd: Any) -> None:
        do_successful_handoff(Path(cwd), "instr-badexit")

    runner = FakeClaudeRunner(side_effect=produce_valid_handoff_but_fail, returncode=1)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 1
    assert state.current_status == "FAILED"
    assert state.last_exit_code == 1
    assert state.last_processed_instruction_id is None


# ---------------------------------------------------------------------
# 6. timeout and launch exception are FAILED
# ---------------------------------------------------------------------


def test_claude_timeout_is_failed(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-timeout",
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def timeout_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

    config = make_config(work)
    state = watch.tick(config, claude_runner=timeout_runner)

    assert state.current_status == "FAILED"
    assert state.last_exit_code is None


def test_claude_launch_exception_is_failed(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-launcherr",
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def raising_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("claude binary not found")

    config = make_config(work)
    state = watch.tick(config, claude_runner=raising_runner)

    assert state.current_status == "FAILED"
    assert state.last_exit_code is None


# ---------------------------------------------------------------------
# 7. modified pre-existing checkpoint/bundle is rejected
# ---------------------------------------------------------------------


def test_modified_preexisting_checkpoint_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-modstale",
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def edit_preexisting_checkpoint(cwd: Any) -> None:
        cwd_path = Path(cwd)
        # "none.md" already existed in the seed commit -- lightly editing it
        # (not adding a new file) must still be rejected as stale.
        text = _checkpoint_text("instr-modstale", "PENDING")
        _write(cwd_path, "orchestration/checkpoints/none.md", text)
        bundle_text = _bundle_text("instr-modstale", "PENDING", text)
        _write(cwd_path, "orchestration/bundles/done.txt", bundle_text)
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            _handoff_text(
                "instr-modstale",
                "orchestration/checkpoints/none.md",
                "orchestration/bundles/done.txt",
                "PENDING",
                "handoff-0001-modstale",
            ),
        )
        sha = _git_commit_with_trailer(cwd_path, "claude: edits stale checkpoint", "instr-modstale")
        # fill in the real commit hash so every OTHER check passes
        text2 = _checkpoint_text("instr-modstale", sha)
        _write(cwd_path, "orchestration/checkpoints/none.md", text2)
        _write(
            cwd_path, "orchestration/bundles/done.txt", _bundle_text("instr-modstale", sha, text2)
        )
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            _handoff_text(
                "instr-modstale",
                "orchestration/checkpoints/none.md",
                "orchestration/bundles/done.txt",
                sha,
                "handoff-0001-modstale",
            ),
        )
        _git_commit_with_trailer(cwd_path, "docs: fill hash", "instr-modstale")
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=edit_preexisting_checkpoint)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 8. empty/malformed newly added checkpoint is rejected
# ---------------------------------------------------------------------


def test_empty_newly_added_checkpoint_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-emptycp",
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def placeholder_checkpoint(cwd: Any) -> None:
        cwd_path = Path(cwd)
        _write(cwd_path, "orchestration/checkpoints/done.md", "checkpoint\n")
        _write(cwd_path, "orchestration/bundles/done.txt", _bundle_text("x", "x", "checkpoint\n"))
        sha = _git_commit_with_trailer(cwd_path, "claude: work", "instr-emptycp")
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            _handoff_text(
                "instr-emptycp",
                "orchestration/checkpoints/done.md",
                "orchestration/bundles/done.txt",
                sha,
                "handoff-0001-emptycp",
            ),
        )
        _git_commit_with_trailer(cwd_path, "docs: handoff", "instr-emptycp")
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=placeholder_checkpoint)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 9. empty/malformed newly added bundle is rejected
# ---------------------------------------------------------------------


def test_empty_newly_added_bundle_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-emptybundle",
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def placeholder_bundle(cwd: Any) -> None:
        cwd_path = Path(cwd)
        checkpoint_text = _checkpoint_text("instr-emptybundle", "PENDING")
        _write(cwd_path, "orchestration/checkpoints/done.md", checkpoint_text)
        _write(cwd_path, "orchestration/bundles/done.txt", "bundle\n")
        sha = _git_commit_with_trailer(cwd_path, "claude: work", "instr-emptybundle")
        final_checkpoint = _checkpoint_text("instr-emptybundle", sha)
        _write(cwd_path, "orchestration/checkpoints/done.md", final_checkpoint)
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            _handoff_text(
                "instr-emptybundle",
                "orchestration/checkpoints/done.md",
                "orchestration/bundles/done.txt",
                sha,
                "handoff-0001-emptybundle",
            ),
        )
        _git_commit_with_trailer(cwd_path, "docs: handoff", "instr-emptybundle")
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=placeholder_bundle)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 10. missing and duplicate handoff fields are rejected
# ---------------------------------------------------------------------


def test_missing_handoff_field_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-missingfield",
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def missing_working_tree_field(cwd: Any) -> None:
        cwd_path = Path(cwd)
        checkpoint_text = _checkpoint_text("instr-missingfield", "PENDING")
        _write(cwd_path, "orchestration/checkpoints/done.md", checkpoint_text)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text("instr-missingfield", "PENDING", checkpoint_text),
        )
        sha = _git_commit_with_trailer(cwd_path, "claude: work", "instr-missingfield")
        final_checkpoint = _checkpoint_text("instr-missingfield", sha)
        _write(cwd_path, "orchestration/checkpoints/done.md", final_checkpoint)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text("instr-missingfield", sha, final_checkpoint),
        )
        # Handoff missing WORKING_TREE entirely.
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            "HANDOFF_ID: handoff-0001-missingfield\n"
            "UTC_TIMESTAMP: 2026-01-02T00:00:00Z\n"
            f"CURRENT_COMMIT: {sha}\n"
            "CURRENT_PHASE: 0\n"
            "WORK_STATUS: COMPLETE\n"
            "LAST_ORCHESTRATOR_INSTRUCTION_ID: instr-missingfield\n"
            "CHECKPOINT_PATH: orchestration/checkpoints/done.md\n"
            "BUNDLE_PATH: orchestration/bundles/done.txt\n"
            "TEST_STATUS: all tests passed\n"
            "ORCHESTRATOR_REVIEW_REQUIRED: none\n",
        )
        _git_commit_with_trailer(cwd_path, "docs: handoff", "instr-missingfield")
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=missing_working_tree_field)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


def test_duplicate_handoff_field_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-dupfield",
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def duplicate_handoff_id_field(cwd: Any) -> None:
        cwd_path = Path(cwd)
        checkpoint_text = _checkpoint_text("instr-dupfield", "PENDING")
        _write(cwd_path, "orchestration/checkpoints/done.md", checkpoint_text)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text("instr-dupfield", "PENDING", checkpoint_text),
        )
        sha = _git_commit_with_trailer(cwd_path, "claude: work", "instr-dupfield")
        final_checkpoint = _checkpoint_text("instr-dupfield", sha)
        _write(cwd_path, "orchestration/checkpoints/done.md", final_checkpoint)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text("instr-dupfield", sha, final_checkpoint),
        )
        base = _handoff_text(
            "instr-dupfield",
            "orchestration/checkpoints/done.md",
            "orchestration/bundles/done.txt",
            sha,
            "handoff-0001-dupfield",
        )
        # Duplicate HANDOFF_ID line with a different (contradictory) value.
        _write(
            cwd_path, "orchestration/AGENT_HANDOFF.md", base + "HANDOFF_ID: handoff-0002-sneaky\n"
        )
        _git_commit_with_trailer(cwd_path, "docs: handoff", "instr-dupfield")
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=duplicate_handoff_id_field)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 11. foreign/absolute/path-traversal/symlink evidence paths are rejected
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_checkpoint_path",
    [
        "/etc/passwd",
        "../outside.md",
        "orchestration/checkpoints/../../escape.md",
        "orchestration/bundles/wrong_dir.md",
        "orchestration/checkpoints/no_extension",
    ],
)
def test_foreign_or_traversal_evidence_path_is_rejected(
    tmp_path: Path, bad_checkpoint_path: str
) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-badpath"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def bad_path_handoff(cwd: Any) -> None:
        cwd_path = Path(cwd)
        _write(cwd_path, "orchestration/bundles/done.txt", _bundle_text(instruction_id, "x", "x"))
        sha = _git_commit_with_trailer(cwd_path, "claude: work", instruction_id)
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            _handoff_text(
                instruction_id,
                bad_checkpoint_path,
                "orchestration/bundles/done.txt",
                sha,
                "handoff-0001-badpath",
            ),
        )
        _git_commit_with_trailer(cwd_path, "docs: handoff", instruction_id)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=bad_path_handoff)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


def test_symlink_evidence_path_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-symlink"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def symlink_checkpoint(cwd: Any) -> None:
        cwd_path = Path(cwd)
        real_target = cwd_path / "orchestration" / "checkpoints" / "none.md"
        link_path = cwd_path / "orchestration" / "checkpoints" / "sneaky.md"
        link_path.symlink_to(real_target)
        _write(cwd_path, "orchestration/bundles/done.txt", _bundle_text(instruction_id, "x", "x"))
        _run(["git", "add", "-A"], cwd_path)
        _run(
            ["git", "commit", "-m", f"claude: work\n\nARGUS-INSTRUCTION-ID: {instruction_id}\n"],
            cwd_path,
        )
        sha = _run(["git", "rev-parse", "HEAD"], cwd_path).stdout.strip()
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            _handoff_text(
                instruction_id,
                "orchestration/checkpoints/sneaky.md",
                "orchestration/bundles/done.txt",
                sha,
                "handoff-0001-symlink",
            ),
        )
        _git_commit_with_trailer(cwd_path, "docs: handoff", instruction_id)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=symlink_checkpoint)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 12. post-run HEAD not descending from pre-launch HEAD is rejected
# ---------------------------------------------------------------------


def test_head_not_descending_from_prelaunch_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-rewrite"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def rewrite_history(cwd: Any) -> None:
        cwd_path = Path(cwd)
        do_successful_handoff(cwd_path, instruction_id)
        # Simulate a rewritten/force-pushed branch: reset to a brand new
        # orphan commit and force-push over the real history.
        _run(["git", "checkout", "--orphan", "rewritten"], cwd_path)
        _write(cwd_path, "orchestration/AGENT_HANDOFF.md", INITIAL_HANDOFF)
        _run(["git", "add", "-A"], cwd_path)
        _run(["git", "commit", "-m", "orphan rewrite"], cwd_path)
        _run(["git", "branch", "-f", BRANCH, "rewritten"], cwd_path)
        _run(["git", "checkout", BRANCH], cwd_path)
        _run(["git", "push", "--force", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=rewrite_history)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 13. a merge commit in the run range is rejected
# ---------------------------------------------------------------------


def test_merge_commit_in_run_range_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-merge"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def make_merge_commit(cwd: Any) -> None:
        cwd_path = Path(cwd)
        _run(["git", "checkout", "-b", "side"], cwd_path)
        _write(cwd_path, "side_file.txt", "side\n")
        _git_commit_with_trailer(cwd_path, "claude: side work", instruction_id)
        _run(["git", "checkout", BRANCH], cwd_path)
        do_successful_handoff(cwd_path, instruction_id)
        _run(["git", "merge", "--no-ff", "-m", "merge side", "side"], cwd_path)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=make_merge_commit)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 14. a concurrent commit without the exact instruction trailer is rejected
# ---------------------------------------------------------------------


def test_concurrent_untrailered_commit_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-notrailer"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def commit_without_trailer(cwd: Any) -> None:
        cwd_path = Path(cwd)
        _write(cwd_path, "untracked_change.txt", "concurrent, unattributed change\n")
        _run(["git", "add", "-A"], cwd_path)
        _run(["git", "commit", "-m", "some concurrent commit with no trailer"], cwd_path)
        do_successful_handoff(cwd_path, instruction_id)

    runner = FakeClaudeRunner(side_effect=commit_without_trailer)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 15. a run commit with the wrong/substr-matching trailer is rejected
# ---------------------------------------------------------------------


def test_substring_matching_trailer_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-trailer"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def wrong_trailer_commit(cwd: Any) -> None:
        cwd_path = Path(cwd)
        checkpoint_text = _checkpoint_text(instruction_id, "PENDING")
        _write(cwd_path, "orchestration/checkpoints/done.md", checkpoint_text)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text(instruction_id, "PENDING", checkpoint_text),
        )
        # Trailer looks similar but is NOT an exact match (extra suffix).
        _run(["git", "add", "-A"], cwd_path)
        _run(
            [
                "git",
                "commit",
                "-m",
                f"claude: work\n\nARGUS-INSTRUCTION-ID: {instruction_id}-extra\n",
            ],
            cwd_path,
        )
        sha = _run(["git", "rev-parse", "HEAD"], cwd_path).stdout.strip()
        final_checkpoint = _checkpoint_text(instruction_id, sha)
        _write(cwd_path, "orchestration/checkpoints/done.md", final_checkpoint)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text(instruction_id, sha, final_checkpoint),
        )
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            _handoff_text(
                instruction_id,
                "orchestration/checkpoints/done.md",
                "orchestration/bundles/done.txt",
                sha,
                "handoff-0001-trailer",
            ),
        )
        _run(["git", "add", "-A"], cwd_path)
        _run(
            [
                "git",
                "commit",
                "-m",
                f"docs: hash\n\nARGUS-INSTRUCTION-ID: {instruction_id}-extra\n",
            ],
            cwd_path,
        )
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=wrong_trailer_commit)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 16. an implementation-agent change to ORCHESTRATOR_INSTRUCTIONS is rejected
# ---------------------------------------------------------------------


def test_instructions_file_modified_during_run_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-selfedit"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def edit_instructions_file(cwd: Any) -> None:
        cwd_path = Path(cwd)
        do_successful_handoff(cwd_path, instruction_id)
        _write(
            cwd_path,
            "orchestration/ORCHESTRATOR_INSTRUCTIONS.md",
            "INSTRUCTION_ID: hijacked\nISSUED_AT: 2026-01-01T00:00:00Z\n"
            "TARGET_COMMIT: 0000000000000000000000000000000000000000\n"
            "AUTHORIZED_ACTION: HIJACK\nAUTHORIZED_PHASE: 0\nAPPROVES_PHASE: NONE\n"
            "STATUS: ACTIVE\n",
        )
        _git_commit_with_trailer(cwd_path, "claude: sneaky edit", instruction_id)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=edit_instructions_file)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


def test_instructions_file_modified_but_uncommitted_is_rejected(tmp_path: Path) -> None:
    """The blob-hash check must catch an in-place edit even before it's
    committed -- the run must fail rather than be masked by the later
    dirty-worktree check alone."""
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-uncommitted-edit"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def edit_uncommitted(cwd: Any) -> None:
        cwd_path = Path(cwd)
        do_successful_handoff(cwd_path, instruction_id)
        (cwd_path / "orchestration" / "ORCHESTRATOR_INSTRUCTIONS.md").write_text("tampered\n")

    runner = FakeClaudeRunner(side_effect=edit_uncommitted)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 17. a self-authored next-phase instruction cannot launch
# ---------------------------------------------------------------------


def test_self_authored_instruction_cannot_launch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-selfauth"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def self_authorize_next_phase(cwd: Any) -> None:
        cwd_path = Path(cwd)
        do_successful_handoff(cwd_path, instruction_id)
        _write(cwd_path, "some_implementation_file.txt", "phase 1 work\n")
        _write(
            cwd_path,
            "orchestration/ORCHESTRATOR_INSTRUCTIONS.md",
            "INSTRUCTION_ID: self-authored-phase-1\n"
            "ISSUED_AT: 2026-01-03T00:00:00Z\n"
            f"TARGET_COMMIT: {head}\n"
            "AUTHORIZED_ACTION: PHASE_1\nAUTHORIZED_PHASE: 1\nAPPROVES_PHASE: 0\n"
            "STATUS: ACTIVE\n",
        )
        _git_commit_with_trailer(cwd_path, "claude: self-authorizes phase 1", instruction_id)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=self_authorize_next_phase)
    config = make_config(work)

    # This run is rejected (instructions-file-changed check).
    state = watch.tick(config, claude_runner=runner)
    assert state.current_status == "FAILED"
    assert runner.calls == 1

    # And the self-authored instruction must not be launched on a later
    # tick either -- it fails TARGET_COMMIT protection because the diff
    # between TARGET_COMMIT (head) and the new HEAD now includes more than
    # just the instructions file.
    state2 = watch.tick(config, claude_runner=runner)
    assert runner.calls == 1
    assert state2.current_status != "COMPLETED"
    assert state2.last_processed_instruction_id != "self-authored-phase-1"


# ---------------------------------------------------------------------
# 18. duplicate instruction fields are rejected
# ---------------------------------------------------------------------


def test_duplicate_instruction_field_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()

    clone = tmp_path / "orchestrator_clone_dup"
    _run(["git", "clone", str(origin), str(clone)], tmp_path)
    _run(["git", "checkout", BRANCH], clone)
    _init_git_identity(clone)
    _write(
        clone,
        "orchestration/ORCHESTRATOR_INSTRUCTIONS.md",
        "INSTRUCTION_ID: instr-dup\nISSUED_AT: 2026-01-01T00:00:00Z\n"
        f"TARGET_COMMIT: {head}\nAUTHORIZED_ACTION: TEST\nAUTHORIZED_PHASE: 0\n"
        "APPROVES_PHASE: NONE\nSTATUS: ACTIVE\nSTATUS: SUPERSEDED\n",
    )
    _run(["git", "add", "-A"], clone)
    _run(["git", "commit", "-m", "orchestrator: duplicate STATUS field"], clone)
    _run(["git", "push", "origin", BRANCH], clone)

    runner = FakeClaudeRunner()
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_instruction_id is None


# ---------------------------------------------------------------------
# 19. malformed timestamp/full-SHA/action are rejected
# ---------------------------------------------------------------------


def test_malformed_issued_at_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-badts",
        status="ACTIVE",
        target_commit=head,
        label="a",
        issued_at="not-a-timestamp",
    )

    runner = FakeClaudeRunner()
    state = watch.tick(make_config(work), claude_runner=runner)

    assert runner.calls == 0
    assert state.current_instruction_id is None


def test_non_full_sha_target_commit_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-shortsha",
        status="ACTIVE",
        target_commit="abc123",
        label="a",
    )

    runner = FakeClaudeRunner()
    state = watch.tick(make_config(work), claude_runner=runner)

    assert runner.calls == 0
    assert state.current_instruction_id is None


def test_empty_authorized_action_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-noaction",
        status="ACTIVE",
        target_commit=head,
        label="a",
        authorized_action="NONE",
    )

    runner = FakeClaudeRunner()
    state = watch.tick(make_config(work), claude_runner=runner)

    assert runner.calls == 0
    assert state.current_instruction_id is None


# ---------------------------------------------------------------------
# 20 & 21. Phase 1 blocked while Phase 0 incomplete / allowed only with
# exact predecessor approval and completed state
# ---------------------------------------------------------------------


def test_phase_1_blocked_without_approves_phase(tmp_path: Path) -> None:
    """current_phase is 0; AUTHORIZED_PHASE: 1 with APPROVES_PHASE: NONE
    is same-phase remediation semantics and must be rejected as advancing
    without an explicit APPROVES_PHASE: 0."""
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-phase1-noapprove",
        status="ACTIVE",
        target_commit=head,
        label="a",
        authorized_phase="1",
        approves_phase="NONE",
    )

    runner = FakeClaudeRunner()
    state = watch.tick(make_config(work), claude_runner=runner)

    assert runner.calls == 0
    assert state.current_instruction_id is None


def test_phase_1_blocked_when_phase_0_not_marked_complete(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    # Phase 0 is current but NOT marked complete (awaiting_orchestrator_review: false).
    _write(
        work,
        "docs/BUILD_STATE.md",
        "```yaml\ncurrent_phase: 0\nlast_completed_phase: 0\nawaiting_orchestrator_review: false\n```\n",
    )
    _run(["git", "add", "-A"], work)
    _run(["git", "commit", "-m", "test: not awaiting review"], work)
    _run(["git", "push", "origin", BRANCH], work)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()

    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-phase1-notready",
        status="ACTIVE",
        target_commit=head,
        label="a",
        authorized_phase="1",
        approves_phase="0",
    )

    runner = FakeClaudeRunner()
    state = watch.tick(make_config(work), claude_runner=runner)

    assert runner.calls == 0
    assert state.current_instruction_id is None


def test_phase_1_allowed_with_full_predecessor_approval(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-phase1-ok",
        status="ACTIVE",
        target_commit=head,
        label="a",
        authorized_phase="1",
        approves_phase="0",
    )

    runner = FakeClaudeRunner(
        side_effect=lambda cwd: do_successful_handoff(Path(cwd), "instr-phase1-ok")
    )
    state = watch.tick(make_config(work), claude_runner=runner)

    assert runner.calls == 1
    assert state.current_status == "COMPLETED"


# ---------------------------------------------------------------------
# 22. Phase 1.5 accepted only as immediate successor of completed Phase 1
# ---------------------------------------------------------------------


def test_phase_1_5_accepted_as_immediate_successor_of_phase_1(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    _write(
        work,
        "docs/BUILD_STATE.md",
        "```yaml\ncurrent_phase: 1\nlast_completed_phase: 1\nawaiting_orchestrator_review: true\n```\n",
    )
    _run(["git", "add", "-A"], work)
    _run(["git", "commit", "-m", "test: phase 1 complete"], work)
    _run(["git", "push", "origin", BRANCH], work)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()

    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-phase1.5-ok",
        status="ACTIVE",
        target_commit=head,
        label="a",
        authorized_phase="1.5",
        approves_phase="1",
    )

    runner = FakeClaudeRunner(
        side_effect=lambda cwd: do_successful_handoff(Path(cwd), "instr-phase1.5-ok")
    )
    state = watch.tick(make_config(work), claude_runner=runner)

    assert runner.calls == 1
    assert state.current_status == "COMPLETED"


# ---------------------------------------------------------------------
# 23. Phase 2 blocked directly from Phase 1 (must go through 1.5)
# ---------------------------------------------------------------------


def test_phase_2_blocked_directly_from_phase_1(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    _write(
        work,
        "docs/BUILD_STATE.md",
        "```yaml\ncurrent_phase: 1\nlast_completed_phase: 1\nawaiting_orchestrator_review: true\n```\n",
    )
    _run(["git", "add", "-A"], work)
    _run(["git", "commit", "-m", "test: phase 1 complete"], work)
    _run(["git", "push", "origin", BRANCH], work)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()

    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-phase2-skip",
        status="ACTIVE",
        target_commit=head,
        label="a",
        authorized_phase="2",
        approves_phase="1",
    )

    runner = FakeClaudeRunner()
    state = watch.tick(make_config(work), claude_runner=runner)

    assert runner.calls == 0
    assert state.current_instruction_id is None


# ---------------------------------------------------------------------
# 24. stale CLAIMED and RUNNING remain fail-closed
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


def test_stale_claimed_state_does_not_relaunch(tmp_path: Path) -> None:
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
# 25. dirty worktree and unpushed/diverged commits remain blocked
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


def test_diverged_local_commit_blocks_launch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-1", status="ACTIVE", target_commit=head, label="a"
    )

    _write(work, "local_only.txt", "local divergence\n")
    _run(["git", "add", "-A"], work)
    _run(["git", "commit", "-m", "local divergent commit"], work)

    runner = FakeClaudeRunner()
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_status == "IDLE"


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
# 26. a valid same-phase remediation run still completes (negative control)
# ---------------------------------------------------------------------


def test_valid_same_phase_remediation_run_completes(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-remediation-ok",
        status="ACTIVE",
        target_commit=head,
        label="a",
        authorized_phase="0",
        approves_phase="NONE",
    )

    runner = FakeClaudeRunner(
        side_effect=lambda cwd: do_successful_handoff(Path(cwd), "instr-remediation-ok")
    )
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 1
    assert state.current_status == "COMPLETED"
    assert state.last_processed_instruction_id == "instr-remediation-ok"
    assert state.current_instruction_id is None
    assert state.last_exit_code == 0

    # A second tick with the same still-ACTIVE instruction must not relaunch.
    state2 = watch.tick(config, claude_runner=runner)
    assert runner.calls == 1
    assert state2.last_processed_instruction_id == "instr-remediation-ok"


# ---------------------------------------------------------------------
# Other retained scenarios: pause file, target-commit checks, lock
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
    assert _run(["git", "rev-parse", "HEAD"], work).stdout.strip() == head


def test_target_commit_not_ancestor_blocks_launch(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
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

    clone = tmp_path / "orchestrator_clone_bad"
    _run(["git", "clone", str(origin), str(clone)], tmp_path)
    _run(["git", "checkout", BRANCH], clone)
    _init_git_identity(clone)
    _write(clone, "MASTER_SPEC.md", "spec (unreviewed edit)\n")
    _write(
        clone,
        "orchestration/ORCHESTRATOR_INSTRUCTIONS.md",
        "INSTRUCTION_ID: instr-1\nISSUED_AT: 2026-01-01T00:00:00Z\nTARGET_COMMIT: "
        + head
        + "\nAUTHORIZED_ACTION: TEST\nAUTHORIZED_PHASE: 0\nAPPROVES_PHASE: NONE\nSTATUS: ACTIVE\n",
    )
    _run(["git", "add", "-A"], clone)
    _run(["git", "commit", "-m", "orchestrator: sneaks in an implementation change"], clone)
    _run(["git", "push", "origin", BRANCH], clone)

    runner = FakeClaudeRunner()
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_instruction_id is None


def test_second_watcher_instance_cannot_acquire_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "watcher.lock"
    first = watch.acquire_lock(lock_path)
    try:
        with pytest.raises(watch.LockUnavailable):
            watch.acquire_lock(lock_path)
    finally:
        watch.release_lock(first)

    second = watch.acquire_lock(lock_path)
    watch.release_lock(second)


# ---------------------------------------------------------------------
# Pure parsing / validation unit tests
# ---------------------------------------------------------------------


def test_parse_instructions_basic() -> None:
    result = watch.parse_instructions(INITIAL_INSTRUCTIONS)
    assert result.ok
    assert result.fields is not None
    assert result.fields.instruction_id == "bootstrap"
    assert result.fields.status == "NO_INSTRUCTION"
    assert result.fields.target_commit == ""


def test_parse_handoff_basic() -> None:
    fields = watch.parse_handoff(INITIAL_HANDOFF)
    assert fields["HANDOFF_ID"] == "handoff-0000-initial"
    assert fields["LAST_ORCHESTRATOR_INSTRUCTION_ID"] == "none"


def test_phase_sequence_ordering() -> None:
    assert watch.PHASE_SEQUENCE.index("1.5") == watch.PHASE_SEQUENCE.index("1") + 1
    assert watch.PHASE_SEQUENCE.index("6.5") == watch.PHASE_SEQUENCE.index("6") + 1
    assert watch._phase_index("bogus") is None


def test_validate_checkpoint_content_rejects_placeholder() -> None:
    ok, _reason = watch.validate_checkpoint_content("checkpoint\n")
    assert not ok


def test_validate_checkpoint_content_accepts_realistic_fixture() -> None:
    ok, reason = watch.validate_checkpoint_content(_checkpoint_text("instr-x", "abc123"))
    assert ok, reason


def test_validate_bundle_content_rejects_placeholder() -> None:
    ok, _reason = watch.validate_bundle_content("bundle\n")
    assert not ok
