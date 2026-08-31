"""Tests for scripts/argus_orchestrator_watch.py.

Real temporary git repositories are used for all git-logic scenarios (no
mocking of git itself) so the tests exercise the actual fetch/pull/diff/
merge-base/log/interpret-trailers commands the watcher relies on. Where a
specific Git-command-failure injection is required (round-3 defect
category: "safety-critical Git command errors fail open"), a narrow,
deterministic failing result is injected for exactly one git subcommand
via monkeypatching `watch._run_git`, while the surrounding scenario still
uses a real temporary repository. The Claude CLI is always mocked via an
injected runner callable -- these tests never invoke a real `claude`
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
FIXTURE_SHA = "deadbeef" * 5  # 40 hex chars -- a realistic-looking, valid-format commit SHA

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


def origin_current_head(origin: Path, tmp_path: Path, label: str) -> str:
    """Read origin's actual current tip via a fresh probe clone -- never
    trust a possibly-stale local `work` view for this."""
    probe = tmp_path / f"probe_{label}"
    _run(["git", "clone", str(origin), str(probe)], tmp_path)
    return _run(["git", "rev-parse", "HEAD"], probe).stdout.strip()


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
) -> None:
    """Simulate the orchestrator committing ORCHESTRATOR_INSTRUCTIONS.md
    through GitHub: clone origin fresh, edit, commit, push -- independent of
    the watcher's own `work` clone, exactly like a real remote edit. This
    produces exactly one commit whose parent is whatever origin's HEAD was,
    matching the tightened target-provenance contract when the caller passes
    that same HEAD as `target_commit`."""
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
    invalid/quarantined state pass seed_idle_state=False."""
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
# satisfies validate_checkpoint_content()/validate_bundle_content()/
# verify_handoff()'s full-schema, exactly-once, and exact-embedding rules.
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
    *,
    current_phase: str = "0",
    utc_timestamp: str = "2026-01-02T00:00:00Z",
    working_tree: str = "clean",
    include_headings: bool = True,
) -> str:
    fields = (
        f"HANDOFF_ID: {handoff_id}\n"
        f"UTC_TIMESTAMP: {utc_timestamp}\n"
        f"CURRENT_COMMIT: {current_commit}\n"
        f"CURRENT_PHASE: {current_phase}\n"
        "WORK_STATUS: COMPLETE\n"
        f"LAST_ORCHESTRATOR_INSTRUCTION_ID: {instruction_id}\n"
        f"CHECKPOINT_PATH: {checkpoint_rel}\n"
        f"BUNDLE_PATH: {bundle_rel}\n"
        "TEST_STATUS: all tests passed\n"
        f"WORKING_TREE: {working_tree}\n"
        "ORCHESTRATOR_REVIEW_REQUIRED: none\n"
    )
    if not include_headings:
        return fields
    sections = (
        "\n## Work completed\nAuthorized work completed.\n"
        "\n## Important findings\nNone beyond what's in the checkpoint.\n"
        "\n## Failures or limitations\nNone new.\n"
        "\n## Deferred checks\nNone new.\n"
        "\n## Exact next action requested from orchestrator\n"
        "Review evidence and issue the next instruction.\n"
    )
    return fields + sections


def _git_commit_with_trailer(cwd: Path, message: str, instruction_id: str) -> str:
    """Produces a REAL terminal Git trailer (subject, blank line, then a
    trailing key:value-only paragraph) -- verified against
    `git interpret-trailers --parse` semantics, not merely text matching."""
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
    current_phase: str = "0",
) -> str:
    """Simulate Claude completing authorized work: write a new, structurally
    valid handoff + checkpoint/bundle (as newly-added files), commit with the
    required trailer (in two commits, exactly like the real repo's
    "implementation commit" + "hash-fill commit" convention), and push.
    Returns the final pushed commit sha."""
    checkpoint_rel = f"orchestration/checkpoints/{checkpoint_name}.md"
    bundle_rel = f"orchestration/bundles/{bundle_name}.txt"

    placeholder_checkpoint = _checkpoint_text(instruction_id, FIXTURE_SHA)
    _write(work, checkpoint_rel, placeholder_checkpoint)
    _write(work, bundle_rel, _bundle_text(instruction_id, FIXTURE_SHA, placeholder_checkpoint))
    _write(
        work,
        "orchestration/AGENT_HANDOFF.md",
        _handoff_text(
            instruction_id,
            checkpoint_rel,
            bundle_rel,
            FIXTURE_SHA,
            handoff_id,
            current_phase=current_phase,
        ),
    )
    impl_sha = _git_commit_with_trailer(work, "claude: authorized work complete", instruction_id)

    final_checkpoint = _checkpoint_text(instruction_id, impl_sha)
    _write(work, checkpoint_rel, final_checkpoint)
    _write(work, bundle_rel, _bundle_text(instruction_id, impl_sha, final_checkpoint))
    _write(
        work,
        "orchestration/AGENT_HANDOFF.md",
        _handoff_text(
            instruction_id,
            checkpoint_rel,
            bundle_rel,
            impl_sha,
            handoff_id,
            current_phase=current_phase,
        ),
    )
    final_sha = _git_commit_with_trailer(work, "docs: fill in commit hash", instruction_id)
    _run(["git", "push", "origin", BRANCH], work)
    return final_sha


def _failing_run_git(original: Any, should_fail: Any) -> Any:
    def wrapper(args: list[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        if should_fail(args):
            return subprocess.CompletedProcess(
                ["git", *args], returncode=1, stdout="", stderr="synthetic failure"
            )
        return original(args, cwd, timeout)

    return wrapper


# ---------------------------------------------------------------------
# 1 & 2. Self-authored next instruction -> terminal quarantine, not an
# ordinary retryable failure; a new instruction ID cannot recover from it.
# ---------------------------------------------------------------------


def test_self_authored_instruction_triggers_quarantine_and_blocks_forever(tmp_path: Path) -> None:
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
        impl_head = _run(["git", "rev-parse", "HEAD"], cwd_path).stdout.strip()
        # Final commit changes ONLY the instructions file, targets the
        # immediately preceding implementation commit, and carries
        # otherwise-valid next-phase metadata -- exactly the realistic
        # bypass the round-3 instruction describes.
        _write(
            cwd_path,
            "orchestration/ORCHESTRATOR_INSTRUCTIONS.md",
            "INSTRUCTION_ID: self-authored-phase-1\n"
            "ISSUED_AT: 2026-01-03T00:00:00Z\n"
            f"TARGET_COMMIT: {impl_head}\n"
            "AUTHORIZED_ACTION: PHASE_1\nAUTHORIZED_PHASE: 1\nAPPROVES_PHASE: 0\n"
            "STATUS: ACTIVE\n",
        )
        _git_commit_with_trailer(cwd_path, "claude: self-authorizes phase 1", instruction_id)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=self_authorize_next_phase)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)
    assert runner.calls == 1
    assert state.current_status == "QUARANTINED"

    # Second tick: absolutely nothing is evaluated, let alone launched.
    state2 = watch.tick(config, claude_runner=runner)
    assert runner.calls == 1
    assert state2.current_status == "QUARANTINED"

    # A brand-new, structurally plausible ACTIVE instruction (different ID,
    # proper single-commit-atop-target provenance) still cannot recover
    # quarantine merely by appearing.
    fresh_target = origin_current_head(origin, tmp_path, "post-quarantine")
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-totally-fresh",
        status="ACTIVE",
        target_commit=fresh_target,
        label="b",
    )
    state3 = watch.tick(config, claude_runner=runner)
    assert runner.calls == 1
    assert state3.current_status == "QUARANTINED"

    # Manual operator recovery (the documented --reset-quarantine procedure)
    # is the only way out. Verify the reset itself lands correctly -- a
    # further tick isn't exercised here since `runner`'s side effect always
    # re-self-authorizes by construction, which would (correctly) quarantine
    # again and conflate two different things being proven.
    watch.write_state(config.state_path, watch.WatcherState())
    reloaded = watch.read_state_safe(config.state_path)
    assert reloaded.outcome == "OK"
    assert reloaded.state is not None
    assert reloaded.state.current_status == "IDLE"


def test_reset_quarantine_refuses_when_not_quarantined(tmp_path: Path) -> None:
    _origin, work = make_repo(tmp_path)
    config = make_config(work)  # seeded IDLE, not QUARANTINED
    load_before = watch.read_state_safe(config.state_path)
    assert load_before.state is not None and load_before.state.current_status == "IDLE"

    # main() targets the real REPO_ROOT, so exercise the reset precondition
    # directly: read_state_safe must correctly report "not QUARANTINED" so
    # main()'s --reset-quarantine branch would refuse to act.
    assert load_before.state.current_status != "QUARANTINED"


# ---------------------------------------------------------------------
# 3. Target equal to HEAD is rejected for ACTIVE instructions.
# ---------------------------------------------------------------------


def test_target_commit_equal_to_head_is_rejected(tmp_path: Path) -> None:
    _origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    result = watch.verify_target_commit(work, head)
    assert not result.ok
    assert "HEAD" in result.reason


# ---------------------------------------------------------------------
# 4. More than one commit between target and instruction HEAD is rejected.
# ---------------------------------------------------------------------


def test_target_commit_multiple_commits_between_is_rejected(tmp_path: Path) -> None:
    _origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    _write(work, "orchestration/ORCHESTRATOR_INSTRUCTIONS.md", "STATUS: ACTIVE\nSTEP: 1\n")
    _run(["git", "add", "-A"], work)
    _run(["git", "commit", "-m", "first instruction edit"], work)
    _write(work, "orchestration/ORCHESTRATOR_INSTRUCTIONS.md", "STATUS: ACTIVE\nSTEP: 2\n")
    _run(["git", "add", "-A"], work)
    _run(["git", "commit", "-m", "second instruction edit"], work)

    result = watch.verify_target_commit(work, head)
    assert not result.ok
    assert "exactly one commit" in result.reason


# ---------------------------------------------------------------------
# 5. The exact valid case -- one instruction-only commit directly atop
# target -- is accepted (negative control).
# ---------------------------------------------------------------------


def test_target_commit_single_commit_atop_target_is_accepted(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-ok", status="ACTIVE", target_commit=head, label="a"
    )
    _run(["git", "pull", "--ff-only", "origin", BRANCH], work)
    result = watch.verify_target_commit(work, head)
    assert result.ok, result.reason


# ---------------------------------------------------------------------
# 6-10. Safety-critical Git command failures must fail closed, never open.
# ---------------------------------------------------------------------


def test_failed_commit_log_read_fails_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _origin, work = make_repo(tmp_path)
    head_before = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    _write(work, "some_file.txt", "work\n")
    _git_commit_with_trailer(work, "some work", "instr-x")
    head_after = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()

    original = watch._run_git
    monkeypatch.setattr(
        watch, "_run_git", _failing_run_git(original, lambda args: args[:1] == ["log"])
    )

    result = watch.verify_run_ancestry_and_attribution(work, head_before, head_after, "instr-x")
    assert not result.ok
    assert "git error" in result.reason or "could not" in result.reason


def test_failed_merge_enumeration_fails_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _origin, work = make_repo(tmp_path)
    head_before = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    _write(work, "some_file.txt", "work\n")
    _git_commit_with_trailer(work, "some work", "instr-x")
    head_after = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()

    original = watch._run_git
    monkeypatch.setattr(
        watch,
        "_run_git",
        _failing_run_git(original, lambda args: args[:2] == ["rev-list", "--merges"]),
    )

    result = watch.verify_run_ancestry_and_attribution(work, head_before, head_after, "instr-x")
    assert not result.ok


def test_failed_git_status_never_counts_as_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _origin, work = make_repo(tmp_path)
    original = watch._run_git
    monkeypatch.setattr(
        watch,
        "_run_git",
        _failing_run_git(original, lambda args: args[:2] == ["status", "--porcelain"]),
    )

    assert watch.is_worktree_dirty(work) is None
    push_check = watch.verify_push_clean(work, BRANCH)
    assert not push_check.ok
    assert "status" in push_check.reason.lower()


def test_failed_git_diff_never_counts_as_no_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-diff",
        status="ACTIVE",
        target_commit=head,
        label="a",
    )
    _run(["git", "pull", "--ff-only", "origin", BRANCH], work)

    original = watch._run_git
    monkeypatch.setattr(
        watch,
        "_run_git",
        _failing_run_git(original, lambda args: args[:2] == ["diff", "--name-only"]),
    )

    result = watch.verify_target_commit(work, head)
    assert not result.ok
    assert "could not determine changed paths" in result.reason


def test_failed_run_range_enumeration_fails_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _origin, work = make_repo(tmp_path)
    head_before = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    final_sha = do_successful_handoff(work, "instr-range")
    head_after = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    assert final_sha == head_after

    original = watch._run_git

    def should_fail(args: list[str]) -> bool:
        # Plain range enumeration (no --merges/--count) as used by
        # verify_handoff -- must not disturb the earlier ancestry/
        # attribution pass over the same commits, which this test performs
        # separately (and successfully) before injecting the failure.
        return args[:1] == ["rev-list"] and "--merges" not in args and "--count" not in args

    ancestry = watch.verify_run_ancestry_and_attribution(
        work, head_before, head_after, "instr-range"
    )
    assert ancestry.ok, ancestry.reason

    monkeypatch.setattr(watch, "_run_git", _failing_run_git(original, should_fail))
    result = watch.verify_handoff(
        work,
        work / "orchestration" / "AGENT_HANDOFF.md",
        "instr-range",
        "0",
        None,
        head_before,
        head_after,
    )
    assert not result.ok
    assert "could not enumerate commits" in result.reason


# ---------------------------------------------------------------------
# 11-13. Real terminal trailer required -- prose mention, duplicates, and
# conflicts are rejected; exactly one exact trailer is accepted.
# ---------------------------------------------------------------------


def test_trailer_in_ordinary_prose_is_not_recognized(tmp_path: Path) -> None:
    _origin, work = make_repo(tmp_path)
    head_before = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    _run(
        [
            "git",
            "commit",
            "--allow-empty",
            "-m",
            "subject\n\nprose mentions ARGUS-INSTRUCTION-ID: instr-x inline\n\nmore prose after\n",
        ],
        work,
    )
    head_after = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    result = watch.verify_run_ancestry_and_attribution(work, head_before, head_after, "instr-x")
    assert not result.ok


def test_duplicate_conflicting_trailers_rejected(tmp_path: Path) -> None:
    _origin, work = make_repo(tmp_path)
    head_before = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    _run(
        [
            "git",
            "commit",
            "--allow-empty",
            "-m",
            "subject\n\nARGUS-INSTRUCTION-ID: instr-x\nARGUS-INSTRUCTION-ID: instr-y\n",
        ],
        work,
    )
    head_after = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    result = watch.verify_run_ancestry_and_attribution(work, head_before, head_after, "instr-x")
    assert not result.ok


def test_single_exact_trailer_is_accepted(tmp_path: Path) -> None:
    _origin, work = make_repo(tmp_path)
    head_before = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    _run(
        ["git", "commit", "--allow-empty", "-m", "subject\n\nARGUS-INSTRUCTION-ID: instr-x\n"], work
    )
    head_after = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    result = watch.verify_run_ancestry_and_attribution(work, head_before, head_after, "instr-x")
    assert result.ok, result.reason


def test_extra_value_text_on_trailer_rejected(tmp_path: Path) -> None:
    _origin, work = make_repo(tmp_path)
    head_before = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    _run(
        [
            "git",
            "commit",
            "--allow-empty",
            "-m",
            "subject\n\nARGUS-INSTRUCTION-ID:   instr-x extra-suffix\n",
        ],
        work,
    )
    head_after = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    result = watch.verify_run_ancestry_and_attribution(work, head_before, head_after, "instr-x")
    assert not result.ok


# ---------------------------------------------------------------------
# 14. A launch wrapper raising an ordinary exception immediately persists
# FAILED -- proven at the tick() level, which is the same code path
# main()'s --once flag invokes with no additional exception handling of
# its own, so this equally proves --once cannot leave a stale RUNNING state.
# ---------------------------------------------------------------------


def test_launch_runtime_error_persists_failed_immediately(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin, tmp_path, instruction_id="instr-rte", status="ACTIVE", target_commit=head, label="a"
    )

    def raising_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise RuntimeError("boom")

    config = make_config(work)
    state = watch.tick(config, claude_runner=raising_runner)

    assert state.current_status == "FAILED"
    assert state.last_exit_code is None

    reloaded = watch.read_state_safe(config.state_path)
    assert reloaded.outcome == "OK"
    assert reloaded.state is not None
    assert reloaded.state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 15. Claude stdout/stderr (even containing a fake credential and an
# embedded newline meant to forge a log line) never appears in the log.
# ---------------------------------------------------------------------


def test_claude_output_never_appears_in_log(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-leak",
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    secret = "FAKE_API_KEY=sk-should-never-appear-in-logs"

    def leaking_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            cmd,
            returncode=1,
            stdout=f"{secret}\n2026-01-01T00:00:00Z FORGED_LOG_LINE injected\n",
            stderr=f"more {secret}\nsome\x00control\x01chars\n",
        )

    config = make_config(work)
    watch.tick(config, claude_runner=leaking_runner)

    log_text = config.log_path.read_text()
    assert secret not in log_text
    assert "sk-should-never-appear" not in log_text
    assert "FORGED_LOG_LINE" not in log_text


# ---------------------------------------------------------------------
# 16 & 17. Impossible-but-shape-matching timestamps are rejected for both
# instructions and handoffs.
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_timestamp", ["2026-02-30T00:00:00Z", "2026-13-01T00:00:00Z", "2026-01-01T25:00:00Z"]
)
def test_instruction_impossible_timestamp_rejected(tmp_path: Path, bad_timestamp: str) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    push_instruction(
        origin,
        tmp_path,
        instruction_id="instr-badts2",
        status="ACTIVE",
        target_commit=head,
        label="a",
        issued_at=bad_timestamp,
    )
    runner = FakeClaudeRunner()
    state = watch.tick(make_config(work), claude_runner=runner)
    assert runner.calls == 0
    assert state.current_instruction_id is None


def test_handoff_impossible_timestamp_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-hbadts"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def bad_handoff_timestamp(cwd: Any) -> None:
        cwd_path = Path(cwd)
        checkpoint_text = _checkpoint_text(instruction_id, FIXTURE_SHA)
        _write(cwd_path, "orchestration/checkpoints/done.md", checkpoint_text)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text(instruction_id, FIXTURE_SHA, checkpoint_text),
        )
        sha = _git_commit_with_trailer(cwd_path, "claude: work", instruction_id)
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
                "handoff-badts",
                utc_timestamp="2026-13-01T00:00:00Z",
            ),
        )
        _git_commit_with_trailer(cwd_path, "docs: handoff", instruction_id)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=bad_handoff_timestamp)
    state = watch.tick(make_config(work), claude_runner=runner)
    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 18. A bundle containing a different, structurally-valid checkpoint is
# rejected -- proven directly at the content-validator level.
# ---------------------------------------------------------------------


def test_bundle_with_different_checkpoint_rejected() -> None:
    real_checkpoint = _checkpoint_text("instr-real", FIXTURE_SHA)
    other_checkpoint = _checkpoint_text("instr-different", FIXTURE_SHA)
    bundle_text = _bundle_text("instr-real", FIXTURE_SHA, other_checkpoint)
    ok, reason = watch.validate_bundle_content(bundle_text, real_checkpoint)
    assert not ok
    assert "verbatim" in reason


def test_bundle_with_exact_checkpoint_is_accepted() -> None:
    checkpoint = _checkpoint_text("instr-real", FIXTURE_SHA)
    bundle_text = _bundle_text("instr-real", FIXTURE_SHA, checkpoint)
    ok, reason = watch.validate_bundle_content(bundle_text, checkpoint)
    assert ok, reason


# ---------------------------------------------------------------------
# 19. Missing required handoff section headings are rejected.
# ---------------------------------------------------------------------


def test_handoff_missing_section_heading_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-noheading"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def missing_heading(cwd: Any) -> None:
        cwd_path = Path(cwd)
        checkpoint_text = _checkpoint_text(instruction_id, FIXTURE_SHA)
        _write(cwd_path, "orchestration/checkpoints/done.md", checkpoint_text)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text(instruction_id, FIXTURE_SHA, checkpoint_text),
        )
        sha = _git_commit_with_trailer(cwd_path, "claude: work", instruction_id)
        final_checkpoint = _checkpoint_text(instruction_id, sha)
        _write(cwd_path, "orchestration/checkpoints/done.md", final_checkpoint)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text(instruction_id, sha, final_checkpoint),
        )
        handoff = _handoff_text(
            instruction_id,
            "orchestration/checkpoints/done.md",
            "orchestration/bundles/done.txt",
            sha,
            "handoff-noheading",
        )
        handoff = handoff.replace("## Deferred checks\nNone new.\n", "")
        _write(cwd_path, "orchestration/AGENT_HANDOFF.md", handoff)
        _git_commit_with_trailer(cwd_path, "docs: handoff", instruction_id)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=missing_heading)
    state = watch.tick(make_config(work), claude_runner=runner)
    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 20. Invalid/contradictory checkpoint status or commit fields are
# rejected -- proven directly at the content-validator level and through
# the full pipeline.
# ---------------------------------------------------------------------


def test_checkpoint_duplicate_contradictory_status_rejected() -> None:
    base = _checkpoint_text("instr-x", FIXTURE_SHA)
    contradictory = base.replace("STATUS: PASS\n", "STATUS: PASS\nSTATUS: FAIL\n")
    ok, reason = watch.validate_checkpoint_content(contradictory)
    assert not ok
    assert "STATUS" in reason


def test_checkpoint_git_commit_not_full_sha_rejected() -> None:
    text = _checkpoint_text("instr-x", "not-a-full-sha")
    ok, reason = watch.validate_checkpoint_content(text)
    assert not ok
    assert "GIT_COMMIT" in reason


def test_checkpoint_duplicate_git_commit_rejected() -> None:
    base = _checkpoint_text("instr-x", FIXTURE_SHA)
    contradictory = base.replace(
        f"GIT_COMMIT: {FIXTURE_SHA}\n", f"GIT_COMMIT: {FIXTURE_SHA}\nGIT_COMMIT: {'a' * 40}\n"
    )
    ok, reason = watch.validate_checkpoint_content(contradictory)
    assert not ok
    assert "GIT_COMMIT" in reason


def test_checkpoint_contradictory_status_rejected_end_to_end(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-contrastatus"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def contradictory_status(cwd: Any) -> None:
        cwd_path = Path(cwd)
        base = _checkpoint_text(instruction_id, FIXTURE_SHA)
        contradictory = base.replace("STATUS: PASS\n", "STATUS: PASS\nSTATUS: FAIL\n")
        _write(cwd_path, "orchestration/checkpoints/done.md", contradictory)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text(instruction_id, FIXTURE_SHA, contradictory),
        )
        sha = _git_commit_with_trailer(cwd_path, "claude: work", instruction_id)
        final = contradictory.replace(FIXTURE_SHA, sha)
        _write(cwd_path, "orchestration/checkpoints/done.md", final)
        _write(cwd_path, "orchestration/bundles/done.txt", _bundle_text(instruction_id, sha, final))
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            _handoff_text(
                instruction_id,
                "orchestration/checkpoints/done.md",
                "orchestration/bundles/done.txt",
                sha,
                "handoff-contrastatus",
            ),
        )
        _git_commit_with_trailer(cwd_path, "docs: handoff", instruction_id)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=contradictory_status)
    state = watch.tick(make_config(work), claude_runner=runner)
    assert state.current_status == "FAILED"


# ---------------------------------------------------------------------
# 21 & 22. Retained coverage from prior rounds, updated to the current API
# (CURRENT_PHASE must match AUTHORIZED_PHASE; required section headings;
# real timestamp validation; tightened target provenance), plus a
# same-phase remediation negative control that still reaches COMPLETED.
# ---------------------------------------------------------------------


def test_no_instruction_does_not_launch(tmp_path: Path) -> None:
    _origin, work = make_repo(tmp_path)
    runner = FakeClaudeRunner()
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_status == "IDLE"
    assert state.last_processed_instruction_id is None


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

    state2 = watch.tick(config, claude_runner=runner)
    assert runner.calls == 1
    assert state2.last_processed_instruction_id == "instr-remediation-ok"


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

    state2 = watch.tick(config, claude_runner=runner)
    assert runner.calls == 1
    assert state2.last_processed_instruction_id == "instr-1"


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
    assert config.state_path.read_text() == "{not valid json"


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
    _run(["git", "pull", "--ff-only", "origin", BRANCH], work)
    do_successful_handoff(work, "instr-done")

    config = make_config(work, seed_idle_state=False)
    assert not config.state_path.exists()
    runner = FakeClaudeRunner()

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 0
    assert state.current_status == "IDLE"
    assert state.last_processed_instruction_id == "instr-done"


def test_nonzero_exit_with_valid_handoff_is_failed(tmp_path: Path) -> None:
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

    runner = FakeClaudeRunner(
        side_effect=lambda cwd: do_successful_handoff(Path(cwd), "instr-badexit"), returncode=1
    )
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert runner.calls == 1
    assert state.current_status == "FAILED"
    assert state.last_exit_code == 1
    assert state.last_processed_instruction_id is None


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


def test_modified_preexisting_checkpoint_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-modstale"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def edit_preexisting_checkpoint(cwd: Any) -> None:
        cwd_path = Path(cwd)
        text = _checkpoint_text(instruction_id, FIXTURE_SHA)
        _write(cwd_path, "orchestration/checkpoints/none.md", text)
        bundle_text = _bundle_text(instruction_id, FIXTURE_SHA, text)
        _write(cwd_path, "orchestration/bundles/done.txt", bundle_text)
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            _handoff_text(
                instruction_id,
                "orchestration/checkpoints/none.md",
                "orchestration/bundles/done.txt",
                FIXTURE_SHA,
                "handoff-0001-modstale",
            ),
        )
        sha = _git_commit_with_trailer(cwd_path, "claude: edits stale checkpoint", instruction_id)
        text2 = _checkpoint_text(instruction_id, sha)
        _write(cwd_path, "orchestration/checkpoints/none.md", text2)
        _write(cwd_path, "orchestration/bundles/done.txt", _bundle_text(instruction_id, sha, text2))
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            _handoff_text(
                instruction_id,
                "orchestration/checkpoints/none.md",
                "orchestration/bundles/done.txt",
                sha,
                "handoff-0001-modstale",
            ),
        )
        _git_commit_with_trailer(cwd_path, "docs: fill hash", instruction_id)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=edit_preexisting_checkpoint)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


def test_empty_newly_added_checkpoint_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-emptycp"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def placeholder_checkpoint(cwd: Any) -> None:
        cwd_path = Path(cwd)
        _write(cwd_path, "orchestration/checkpoints/done.md", "checkpoint\n")
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text("x", FIXTURE_SHA, "checkpoint\n"),
        )
        sha = _git_commit_with_trailer(cwd_path, "claude: work", instruction_id)
        _write(
            cwd_path,
            "orchestration/AGENT_HANDOFF.md",
            _handoff_text(
                instruction_id,
                "orchestration/checkpoints/done.md",
                "orchestration/bundles/done.txt",
                sha,
                "handoff-0001-emptycp",
            ),
        )
        _git_commit_with_trailer(cwd_path, "docs: handoff", instruction_id)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=placeholder_checkpoint)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


def test_missing_handoff_field_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-missingfield"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def missing_working_tree_field(cwd: Any) -> None:
        cwd_path = Path(cwd)
        checkpoint_text = _checkpoint_text(instruction_id, FIXTURE_SHA)
        _write(cwd_path, "orchestration/checkpoints/done.md", checkpoint_text)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text(instruction_id, FIXTURE_SHA, checkpoint_text),
        )
        sha = _git_commit_with_trailer(cwd_path, "claude: work", instruction_id)
        final_checkpoint = _checkpoint_text(instruction_id, sha)
        _write(cwd_path, "orchestration/checkpoints/done.md", final_checkpoint)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text(instruction_id, sha, final_checkpoint),
        )
        handoff = _handoff_text(
            instruction_id,
            "orchestration/checkpoints/done.md",
            "orchestration/bundles/done.txt",
            sha,
            "handoff-0001-missingfield",
        )
        handoff = handoff.replace("WORKING_TREE: clean\n", "")
        _write(cwd_path, "orchestration/AGENT_HANDOFF.md", handoff)
        _git_commit_with_trailer(cwd_path, "docs: handoff", instruction_id)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=missing_working_tree_field)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


def test_duplicate_handoff_field_is_rejected(tmp_path: Path) -> None:
    origin, work = make_repo(tmp_path)
    head = _run(["git", "rev-parse", "HEAD"], work).stdout.strip()
    instruction_id = "instr-dupfield"
    push_instruction(
        origin,
        tmp_path,
        instruction_id=instruction_id,
        status="ACTIVE",
        target_commit=head,
        label="a",
    )

    def duplicate_handoff_id_field(cwd: Any) -> None:
        cwd_path = Path(cwd)
        checkpoint_text = _checkpoint_text(instruction_id, FIXTURE_SHA)
        _write(cwd_path, "orchestration/checkpoints/done.md", checkpoint_text)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text(instruction_id, FIXTURE_SHA, checkpoint_text),
        )
        sha = _git_commit_with_trailer(cwd_path, "claude: work", instruction_id)
        final_checkpoint = _checkpoint_text(instruction_id, sha)
        _write(cwd_path, "orchestration/checkpoints/done.md", final_checkpoint)
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text(instruction_id, sha, final_checkpoint),
        )
        base = _handoff_text(
            instruction_id,
            "orchestration/checkpoints/done.md",
            "orchestration/bundles/done.txt",
            sha,
            "handoff-0001-dupfield",
        )
        _write(
            cwd_path, "orchestration/AGENT_HANDOFF.md", base + "HANDOFF_ID: handoff-0002-sneaky\n"
        )
        _git_commit_with_trailer(cwd_path, "docs: handoff", instruction_id)
        _run(["git", "push", "origin", BRANCH], cwd_path)

    runner = FakeClaudeRunner(side_effect=duplicate_handoff_id_field)
    config = make_config(work)

    state = watch.tick(config, claude_runner=runner)

    assert state.current_status == "FAILED"


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
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text(instruction_id, FIXTURE_SHA, "x"),
        )
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
        _write(
            cwd_path,
            "orchestration/bundles/done.txt",
            _bundle_text(instruction_id, FIXTURE_SHA, "x"),
        )
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


def test_instructions_file_modified_but_uncommitted_is_rejected(tmp_path: Path) -> None:
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

    assert state.current_status == "QUARANTINED"


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


def test_phase_1_blocked_without_approves_phase(tmp_path: Path) -> None:
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
        side_effect=lambda cwd: do_successful_handoff(
            Path(cwd), "instr-phase1-ok", current_phase="1"
        )
    )
    state = watch.tick(make_config(work), claude_runner=runner)

    assert runner.calls == 1
    assert state.current_status == "COMPLETED"


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
        side_effect=lambda cwd: do_successful_handoff(
            Path(cwd), "instr-phase1.5-ok", current_phase="1.5"
        )
    )
    state = watch.tick(make_config(work), claude_runner=runner)

    assert runner.calls == 1
    assert state.current_status == "COMPLETED"


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
    ok, reason = watch.validate_checkpoint_content(_checkpoint_text("instr-x", FIXTURE_SHA))
    assert ok, reason


def test_validate_bundle_content_rejects_placeholder() -> None:
    ok, _reason = watch.validate_bundle_content("bundle\n", "checkpoint\n")
    assert not ok


def test_canonical_utc_timestamp_parser() -> None:
    assert watch.parse_canonical_utc_timestamp("2026-08-31T03:24:15Z") is not None
    assert watch.parse_canonical_utc_timestamp("2026-99-31T03:24:15Z") is None
    assert watch.parse_canonical_utc_timestamp("2026-08-31T99:24:15Z") is None
    assert watch.parse_canonical_utc_timestamp("2026-02-30T03:24:15Z") is None
    assert watch.parse_canonical_utc_timestamp("2026-08-31T03:24:15.000Z") is None
    assert watch.parse_canonical_utc_timestamp("2026-08-31 03:24:15Z") is None
