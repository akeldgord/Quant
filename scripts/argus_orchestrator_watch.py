#!/usr/bin/env python3
"""ARGUS local "no-nudge" orchestrator watcher.

Polls this repository for a new ``ACTIVE`` instruction in
``orchestration/ORCHESTRATOR_INSTRUCTIONS.md`` and, when one appears, launches
the local Claude CLI non-interactively to execute exactly that instruction
under the existing GitHub orchestration protocol (``orchestration/PROTOCOL.md``).

Deliberately stdlib-only: no Celery/Redis/Kafka, no systemd dependency inside
the code, no Docker daemon dependency, no new external service. Just ordinary
``git`` subprocess calls, a JSON state file, a file lock, and a subprocess
launch of the Claude CLI.

Usage::

    uv run python scripts/argus_orchestrator_watch.py [--interval SECONDS] ...

or ``make orchestrator-watch``. See docs/OPERATIONS.md for background-start
options (nohup / a user-level systemd example) -- neither is installed or
enabled automatically.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_BRANCH = "claude/argus-folder-setup-77ahrk"
DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_CLAUDE_BIN = "claude"
DEFAULT_CLAUDE_TIMEOUT_SECONDS = 3600

INSTRUCTIONS_RELPATH = Path("orchestration/ORCHESTRATOR_INSTRUCTIONS.md")
HANDOFF_RELPATH = Path("orchestration/AGENT_HANDOFF.md")
STATE_RELPATH = Path("runtime/orchestrator_watcher_state.json")
LOCK_RELPATH = Path("runtime/orchestrator_watcher.lock")
PAUSE_RELPATH = Path("runtime/ORCHESTRATION_PAUSED")
LOG_RELPATH = Path("runtime/logs/orchestrator_watcher.log")

# Between TARGET_COMMIT and current HEAD, only these paths may differ for the
# watcher to consider an ACTIVE instruction safe to execute (section 5,
# TARGET_COMMIT protection). Anything else is unreviewed implementation drift.
ALLOWED_POST_TARGET_PATHS = {"orchestration/ORCHESTRATOR_INSTRUCTIONS.md"}

VALID_STATUSES = {"IDLE", "CLAIMED", "RUNNING", "COMPLETED", "FAILED"}

CLAUDE_PROMPT = """\
Read, in this exact order, before doing anything else:
1. MASTER_SPEC.md
2. docs/BUILD_STATE.md
3. docs/DECISION_LOG.md
4. orchestration/PROTOCOL.md
5. orchestration/ORCHESTRATOR_INSTRUCTIONS.md
6. orchestration/AGENT_HANDOFF.md

Execute ONLY the ACTIVE instruction currently present in
orchestration/ORCHESTRATOR_INSTRUCTIONS.md.
Follow all phase gates in MASTER_SPEC.md.
When authorized work is complete:
- run required tests,
- generate checkpoint,
- generate orchestrator bundle,
- update AGENT_HANDOFF.md,
- update BUILD_STATE.md,
- commit,
- push,
- STOP.
Do not begin later work.
"""


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class WatcherConfig:
    repo_root: Path = REPO_ROOT
    branch: str = DEFAULT_BRANCH
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    claude_bin: str = DEFAULT_CLAUDE_BIN
    claude_extra_args: tuple[str, ...] = ()
    claude_timeout_seconds: int = DEFAULT_CLAUDE_TIMEOUT_SECONDS

    @property
    def instructions_path(self) -> Path:
        return self.repo_root / INSTRUCTIONS_RELPATH

    @property
    def handoff_path(self) -> Path:
        return self.repo_root / HANDOFF_RELPATH

    @property
    def state_path(self) -> Path:
        return self.repo_root / STATE_RELPATH

    @property
    def lock_path(self) -> Path:
        return self.repo_root / LOCK_RELPATH

    @property
    def pause_path(self) -> Path:
        return self.repo_root / PAUSE_RELPATH

    @property
    def log_path(self) -> Path:
        return self.repo_root / LOG_RELPATH


# --------------------------------------------------------------------------
# Logging (never logs raw command output, env vars, or credentials -- only
# short structured event strings we construct ourselves).
# --------------------------------------------------------------------------


def log_event(config: WatcherConfig, event: str, detail: str = "") -> None:
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    line = f"{timestamp} {event}" + (f" {detail}" if detail else "")
    with config.log_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(line, file=sys.stderr)


# --------------------------------------------------------------------------
# State persistence (atomic write; never committed -- gitignored)
# --------------------------------------------------------------------------


@dataclasses.dataclass
class WatcherState:
    last_processed_instruction_id: str | None = None
    current_instruction_id: str | None = None
    current_status: str = "IDLE"
    last_check_at: str | None = None
    last_launch_at: str | None = None
    last_exit_code: int | None = None

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> WatcherState:
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in payload.items() if k in known})


def read_state(state_path: Path) -> WatcherState:
    if not state_path.exists():
        return WatcherState()
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return WatcherState()
    return WatcherState.from_json(payload)


def write_state(state_path: Path, state: WatcherState) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(state.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(tmp_path, state_path)  # atomic on POSIX


# --------------------------------------------------------------------------
# orchestration/ORCHESTRATOR_INSTRUCTIONS.md + AGENT_HANDOFF.md parsing
#
# Both files use plain "FIELD: value" lines near the top (see
# orchestration/PROTOCOL.md sections 4-5). This is a deliberately simple
# line-oriented parser, not a YAML/markdown parser -- it matches the exact
# contract those two files commit to.
# --------------------------------------------------------------------------

_FIELD_LINE_RE = re.compile(r"^([A-Z_]+):\s*(.*)$")


def _parse_fields(text: str, field_names: Iterable[str]) -> dict[str, str]:
    wanted = set(field_names)
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = _FIELD_LINE_RE.match(line.strip())
        if match and match.group(1) in wanted and match.group(1) not in found:
            found[match.group(1)] = match.group(2).strip()
    return found


@dataclasses.dataclass(frozen=True, slots=True)
class InstructionFields:
    instruction_id: str
    issued_at: str
    target_commit: str
    authorized_action: str
    authorized_phase: str
    status: str


INSTRUCTION_FIELD_NAMES = (
    "INSTRUCTION_ID",
    "ISSUED_AT",
    "TARGET_COMMIT",
    "AUTHORIZED_ACTION",
    "AUTHORIZED_PHASE",
    "STATUS",
)


def parse_instructions(text: str) -> InstructionFields:
    fields = _parse_fields(text, INSTRUCTION_FIELD_NAMES)
    return InstructionFields(
        instruction_id=fields.get("INSTRUCTION_ID", ""),
        issued_at=fields.get("ISSUED_AT", ""),
        target_commit=fields.get("TARGET_COMMIT", ""),
        authorized_action=fields.get("AUTHORIZED_ACTION", ""),
        authorized_phase=fields.get("AUTHORIZED_PHASE", ""),
        status=fields.get("STATUS", ""),
    )


def read_instructions(instructions_path: Path) -> InstructionFields | None:
    if not instructions_path.exists():
        return None
    return parse_instructions(instructions_path.read_text(encoding="utf-8"))


HANDOFF_FIELD_NAMES = (
    "HANDOFF_ID",
    "LAST_ORCHESTRATOR_INSTRUCTION_ID",
    "CHECKPOINT_PATH",
    "BUNDLE_PATH",
)


def parse_handoff(text: str) -> dict[str, str]:
    return _parse_fields(text, HANDOFF_FIELD_NAMES)


def read_handoff(handoff_path: Path) -> dict[str, str]:
    if not handoff_path.exists():
        return {}
    return parse_handoff(handoff_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Git helpers (ordinary subprocess calls to the local `git`)
# --------------------------------------------------------------------------


def _run_git(args: list[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )


def is_worktree_dirty(repo_root: Path) -> bool:
    result = _run_git(["status", "--porcelain"], cwd=repo_root)
    return bool(result.stdout.strip())


def git_fetch(repo_root: Path, branch: str) -> bool:
    result = _run_git(["fetch", "origin", branch], cwd=repo_root)
    return result.returncode == 0


def git_pull_ff_only(repo_root: Path, branch: str) -> bool:
    result = _run_git(["pull", "--ff-only", "origin", branch], cwd=repo_root)
    return result.returncode == 0


def git_head(repo_root: Path) -> str | None:
    result = _run_git(["rev-parse", "HEAD"], cwd=repo_root)
    return result.stdout.strip() if result.returncode == 0 else None


def git_remote_head(repo_root: Path, branch: str) -> str | None:
    result = _run_git(["rev-parse", f"origin/{branch}"], cwd=repo_root)
    return result.stdout.strip() if result.returncode == 0 else None


def git_resolve_commit(repo_root: Path, ref: str) -> str | None:
    if not ref:
        return None
    result = _run_git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=repo_root)
    return result.stdout.strip() if result.returncode == 0 else None


def git_is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    result = _run_git(["merge-base", "--is-ancestor", ancestor, descendant], cwd=repo_root)
    return result.returncode == 0


def git_changed_paths(repo_root: Path, from_ref: str, to_ref: str) -> list[str]:
    result = _run_git(["diff", "--name-only", from_ref, to_ref], cwd=repo_root)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


@dataclasses.dataclass(frozen=True, slots=True)
class TargetCommitCheck:
    ok: bool
    reason: str = ""


def verify_target_commit(repo_root: Path, target_commit: str) -> TargetCommitCheck:
    """TARGET_COMMIT protection (orchestration/PROTOCOL.md section 7).

    The ACTIVE instruction's TARGET_COMMIT must resolve to a real commit that
    is an ancestor of current HEAD, and every path that differs between
    TARGET_COMMIT and HEAD must be one the orchestrator is allowed to have
    touched on its own (currently just ORCHESTRATOR_INSTRUCTIONS.md).
    Anything else is unreviewed implementation drift -- conservative by
    design, per the protocol's explicit instruction to prefer that.
    """
    if not target_commit:
        return TargetCommitCheck(ok=False, reason="TARGET_COMMIT is empty")

    resolved = git_resolve_commit(repo_root, target_commit)
    if resolved is None:
        return TargetCommitCheck(
            ok=False, reason=f"TARGET_COMMIT {target_commit!r} does not resolve to a commit"
        )

    head = git_head(repo_root)
    if head is None:
        return TargetCommitCheck(ok=False, reason="could not resolve HEAD")

    if resolved == head:
        return TargetCommitCheck(ok=True)

    if not git_is_ancestor(repo_root, resolved, head):
        return TargetCommitCheck(
            ok=False, reason=f"TARGET_COMMIT {target_commit!r} is not an ancestor of HEAD"
        )

    changed = git_changed_paths(repo_root, resolved, head)
    unexpected = [p for p in changed if p not in ALLOWED_POST_TARGET_PATHS]
    if unexpected:
        return TargetCommitCheck(
            ok=False,
            reason=(
                "unreviewed implementation changes between TARGET_COMMIT and HEAD: "
                + ", ".join(unexpected)
            ),
        )
    return TargetCommitCheck(ok=True)


@dataclasses.dataclass(frozen=True, slots=True)
class PushCheck:
    ok: bool
    reason: str = ""


def verify_push_clean(repo_root: Path, branch: str) -> PushCheck:
    if is_worktree_dirty(repo_root):
        return PushCheck(ok=False, reason="working tree is dirty after Claude run")
    if not git_fetch(repo_root, branch):
        return PushCheck(ok=False, reason="git fetch failed while verifying push")
    head = git_head(repo_root)
    remote_head = git_remote_head(repo_root, branch)
    if head is None or remote_head is None:
        return PushCheck(ok=False, reason="could not resolve local/remote HEAD")
    if head != remote_head:
        return PushCheck(
            ok=False, reason=f"local HEAD {head[:12]} != origin/{branch} {remote_head[:12]}"
        )
    return PushCheck(ok=True)


@dataclasses.dataclass(frozen=True, slots=True)
class HandoffCheck:
    ok: bool
    reason: str = ""


def verify_handoff(
    repo_root: Path, handoff_path: Path, instruction_id: str, handoff_id_before: str | None
) -> HandoffCheck:
    fields = read_handoff(handoff_path)
    new_handoff_id = fields.get("HANDOFF_ID", "")
    last_instruction = fields.get("LAST_ORCHESTRATOR_INSTRUCTION_ID", "")

    if not new_handoff_id:
        return HandoffCheck(ok=False, reason="AGENT_HANDOFF.md has no HANDOFF_ID")
    if new_handoff_id == (handoff_id_before or ""):
        return HandoffCheck(ok=False, reason="AGENT_HANDOFF.md HANDOFF_ID was not updated")
    if instruction_id not in last_instruction:
        return HandoffCheck(
            ok=False,
            reason=(
                f"AGENT_HANDOFF.md LAST_ORCHESTRATOR_INSTRUCTION_ID "
                f"({last_instruction!r}) does not reference {instruction_id!r}"
            ),
        )

    for field_name in ("CHECKPOINT_PATH", "BUNDLE_PATH"):
        rel = fields.get(field_name, "")
        if not rel:
            return HandoffCheck(ok=False, reason=f"AGENT_HANDOFF.md missing {field_name}")
        if not (repo_root / rel).exists():
            return HandoffCheck(ok=False, reason=f"{field_name} {rel!r} does not exist on disk")

    return HandoffCheck(ok=True)


# --------------------------------------------------------------------------
# Single-instance lock. fcntl.flock is held for the process lifetime and is
# automatically released by the kernel on process exit/crash -- no stale-lock
# cleanup required.
# --------------------------------------------------------------------------


class LockUnavailable(Exception):
    pass


def acquire_lock(lock_path: Path) -> Any:
    import fcntl

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = lock_path.open("a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        fh.close()
        raise LockUnavailable("another watcher instance holds the lock") from exc
    fh.seek(0)
    fh.truncate()
    fh.write(f"pid={os.getpid()} started_at={datetime.now(UTC).isoformat()}\n")
    fh.flush()
    return fh


def release_lock(fh: Any) -> None:
    import fcntl

    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


# --------------------------------------------------------------------------
# Claude CLI launch (thin, mockable wrapper -- tests never invoke real claude)
# --------------------------------------------------------------------------

Runner = Callable[..., subprocess.CompletedProcess[str]]


def build_claude_command(config: WatcherConfig) -> list[str]:
    return [config.claude_bin, "-p", CLAUDE_PROMPT, *config.claude_extra_args]


def launch_claude(
    config: WatcherConfig, runner: Runner = subprocess.run
) -> subprocess.CompletedProcess[str]:
    cmd = build_claude_command(config)
    return runner(
        cmd,
        cwd=config.repo_root,
        capture_output=True,
        text=True,
        timeout=config.claude_timeout_seconds,
        check=False,
    )


# --------------------------------------------------------------------------
# Main tick
# --------------------------------------------------------------------------


def tick(config: WatcherConfig, claude_runner: Runner = subprocess.run) -> WatcherState:
    """Run one watch iteration. Returns the resulting state (also persisted)."""
    state = read_state(config.state_path)
    state.last_check_at = datetime.now(UTC).isoformat()

    # A RUNNING state found at rest means a previous watcher process crashed
    # mid-launch. Never blindly re-execute -- require a human/orchestrator
    # decision (section 4).
    if state.current_status == "RUNNING":
        log_event(
            config,
            "RUN_FAILED",
            f"stale RUNNING state found for instruction_id={state.current_instruction_id!r} "
            "(watcher crashed mid-run); not auto-retrying",
        )
        state.current_status = "FAILED"
        write_state(config.state_path, state)
        return state

    if config.pause_path.exists():
        log_event(config, "WATCHER_PAUSED", f"pause file present at {PAUSE_RELPATH}")
        write_state(config.state_path, state)
        return state

    if not git_fetch(config.repo_root, config.branch):
        log_event(config, "GIT_PULL_FAILED", "git fetch failed")
        write_state(config.state_path, state)
        return state

    if is_worktree_dirty(config.repo_root):
        log_event(config, "DIRTY_WORKTREE", "local worktree has uncommitted changes; not pulling")
        write_state(config.state_path, state)
        return state

    if not git_pull_ff_only(config.repo_root, config.branch):
        log_event(config, "GIT_PULL_FAILED", "git pull --ff-only failed")
        write_state(config.state_path, state)
        return state

    instructions = read_instructions(config.instructions_path)
    if instructions is None or instructions.status != "ACTIVE":
        log_event(
            config,
            "NO_ACTIVE_INSTRUCTION",
            f"status={instructions.status if instructions else 'MISSING'!r}",
        )
        write_state(config.state_path, state)
        return state

    instruction_id = instructions.instruction_id
    if not instruction_id:
        log_event(
            config,
            "NO_ACTIVE_INSTRUCTION",
            "ACTIVE instruction has no INSTRUCTION_ID; refusing to process",
        )
        write_state(config.state_path, state)
        return state

    if instruction_id == state.last_processed_instruction_id:
        write_state(config.state_path, state)
        return state

    if instruction_id == state.current_instruction_id and state.current_status in {
        "CLAIMED",
        "FAILED",
    }:
        # Already attempted (or mid-claim) this exact instruction id.
        # section 4 / 12: at most one Claude launch per unique INSTRUCTION_ID.
        write_state(config.state_path, state)
        return state

    target_check = verify_target_commit(config.repo_root, instructions.target_commit)
    if not target_check.ok:
        log_event(config, "TARGET_COMMIT_MISMATCH", target_check.reason)
        write_state(config.state_path, state)
        return state

    log_event(
        config,
        "NEW_INSTRUCTION",
        f"instruction_id={instruction_id!r} target_commit={instructions.target_commit!r}",
    )

    # Claim (persisted before launch so a crash here is visible as RUNNING or
    # -- if we crash between these two writes -- as CLAIMED, either of which
    # blocks a blind re-run next startup).
    state.current_instruction_id = instruction_id
    state.current_status = "CLAIMED"
    write_state(config.state_path, state)

    handoff_id_before = read_handoff(config.handoff_path).get("HANDOFF_ID")

    state.current_status = "RUNNING"
    state.last_launch_at = datetime.now(UTC).isoformat()
    write_state(config.state_path, state)
    log_event(config, "CLAUDE_STARTED", f"instruction_id={instruction_id!r}")

    try:
        result = launch_claude(config, runner=claude_runner)
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        exit_code = -1
        log_event(config, "CLAUDE_EXITED", "timed out")
    else:
        log_event(config, "CLAUDE_EXITED", f"exit_code={exit_code}")

    state.last_exit_code = exit_code

    handoff_check = verify_handoff(
        config.repo_root, config.handoff_path, instruction_id, handoff_id_before
    )
    if not handoff_check.ok:
        log_event(config, "RUN_FAILED", f"handoff verification failed: {handoff_check.reason}")
        state.current_status = "FAILED"
        write_state(config.state_path, state)
        return state
    log_event(config, "HANDOFF_VERIFIED", f"instruction_id={instruction_id!r}")

    push_check = verify_push_clean(config.repo_root, config.branch)
    if not push_check.ok:
        log_event(config, "RUN_FAILED", f"push verification failed: {push_check.reason}")
        state.current_status = "FAILED"
        write_state(config.state_path, state)
        return state

    log_event(config, "RUN_COMPLETED", f"instruction_id={instruction_id!r}")
    state.current_status = "COMPLETED"
    state.last_processed_instruction_id = instruction_id
    state.current_instruction_id = None
    write_state(config.state_path, state)
    return state


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------

_shutdown_requested = False


def _handle_shutdown_signal(signum: int, _frame: Any) -> None:
    global _shutdown_requested
    _shutdown_requested = True


def _sleep_or_shutdown(seconds: int) -> None:
    remaining = seconds
    while remaining > 0 and not _shutdown_requested:
        time.sleep(min(1, remaining))
        remaining -= 1


def run_forever(config: WatcherConfig) -> int:
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)

    try:
        lock_fh = acquire_lock(config.lock_path)
    except LockUnavailable:
        print("another watcher instance already holds the lock; exiting", file=sys.stderr)
        return 1

    log_event(
        config, "WATCHER_STARTED", f"branch={config.branch} interval={config.interval_seconds}s"
    )
    try:
        while not _shutdown_requested:
            tick(config)
            _sleep_or_shutdown(config.interval_seconds)
    finally:
        release_lock(lock_fh)
        log_event(config, "WATCHER_STOPPED", "")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("ARGUS_WATCHER_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)),
    )
    parser.add_argument("--branch", default=os.environ.get("ARGUS_WATCHER_BRANCH", DEFAULT_BRANCH))
    parser.add_argument(
        "--claude-bin", default=os.environ.get("ARGUS_WATCHER_CLAUDE_BIN", DEFAULT_CLAUDE_BIN)
    )
    parser.add_argument(
        "--claude-timeout-seconds",
        type=int,
        default=int(
            os.environ.get("ARGUS_WATCHER_CLAUDE_TIMEOUT_SECONDS", DEFAULT_CLAUDE_TIMEOUT_SECONDS)
        ),
    )
    parser.add_argument(
        "--claude-arg",
        dest="claude_extra_args",
        action="append",
        default=[],
        help="Extra argument to append to the Claude CLI invocation (repeatable). "
        "Use this to pass whatever permission-mode flag your local Claude CLI needs "
        "for non-interactive, unattended runs.",
    )
    parser.add_argument(
        "--once", action="store_true", help="Run a single tick and exit (for manual testing)."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    config = WatcherConfig(
        repo_root=REPO_ROOT,
        branch=args.branch,
        interval_seconds=args.interval,
        claude_bin=args.claude_bin,
        claude_extra_args=tuple(args.claude_extra_args),
        claude_timeout_seconds=args.claude_timeout_seconds,
    )
    if args.once:
        signal.signal(signal.SIGINT, _handle_shutdown_signal)
        signal.signal(signal.SIGTERM, _handle_shutdown_signal)
        try:
            lock_fh = acquire_lock(config.lock_path)
        except LockUnavailable:
            print("another watcher instance already holds the lock; exiting", file=sys.stderr)
            return 1
        try:
            tick(config)
        finally:
            release_lock(lock_fh)
        return 0
    return run_forever(config)


if __name__ == "__main__":
    raise SystemExit(main())
