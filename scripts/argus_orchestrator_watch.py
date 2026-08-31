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

This module is deliberately conservative and fail-closed throughout: any
state, instruction, handoff, or evidence condition this module cannot
positively confirm as safe is treated as unsafe. See
``orchestration/PROTOCOL.md`` sections 4-8 for the contract this file
mechanically enforces.

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
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_BRANCH = "claude/argus-folder-setup-77ahrk"
DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_CLAUDE_BIN = "claude"
DEFAULT_CLAUDE_TIMEOUT_SECONDS = 3600

INSTRUCTIONS_RELPATH = Path("orchestration/ORCHESTRATOR_INSTRUCTIONS.md")
HANDOFF_RELPATH = Path("orchestration/AGENT_HANDOFF.md")
BUILD_STATE_RELPATH = Path("docs/BUILD_STATE.md")
STATE_RELPATH = Path("runtime/orchestrator_watcher_state.json")
LOCK_RELPATH = Path("runtime/orchestrator_watcher.lock")
PAUSE_RELPATH = Path("runtime/ORCHESTRATION_PAUSED")
LOG_RELPATH = Path("runtime/logs/orchestrator_watcher.log")

# Between TARGET_COMMIT and current HEAD, only these paths may differ for the
# watcher to consider an ACTIVE instruction safe to execute (section 5,
# TARGET_COMMIT protection). Anything else is unreviewed implementation drift.
ALLOWED_POST_TARGET_PATHS = {"orchestration/ORCHESTRATOR_INSTRUCTIONS.md"}

VALID_STATUSES = {"IDLE", "CLAIMED", "RUNNING", "COMPLETED", "FAILED"}

# Canonical ordered ARGUS phase sequence (MASTER_SPEC.md), including the
# mandatory sub-phase gates. Represented as exact string tokens, compared by
# list position -- never as floats/binary comparison, since "1.5" and "6.5"
# are not evenly spaced and float equality on parsed YAML values is unsafe.
PHASE_SEQUENCE: tuple[str, ...] = (
    "0",
    "1",
    "1.5",
    "2",
    "3",
    "4",
    "5",
    "6",
    "6.5",
    "7",
    "8",
    "9",
    "10",
    "11",
)


def _phase_index(phase: str) -> int | None:
    try:
        return PHASE_SEQUENCE.index(phase)
    except ValueError:
        return None


def build_claude_prompt(instruction_id: str) -> str:
    return f"""\
Read, in this exact order, before doing anything else:
1. MASTER_SPEC.md
2. docs/BUILD_STATE.md
3. docs/DECISION_LOG.md
4. orchestration/PROTOCOL.md
5. orchestration/ORCHESTRATOR_INSTRUCTIONS.md
6. orchestration/AGENT_HANDOFF.md

Execute ONLY the ACTIVE instruction currently present in
orchestration/ORCHESTRATOR_INSTRUCTIONS.md, whose INSTRUCTION_ID is exactly:
{instruction_id}
Follow all phase gates in MASTER_SPEC.md.

Do NOT modify orchestration/ORCHESTRATOR_INSTRUCTIONS.md for any reason, at
any point during this run -- not even to "fix" it. That file is
orchestrator-owned. Any change to its bytes during this run, even if later
committed and pushed, causes the entire run to be rejected as FAILED,
regardless of anything else this run produces.

Every commit you create during this run MUST include this exact
commit-message trailer (its own line, exact text, no extra wording):
ARGUS-INSTRUCTION-ID: {instruction_id}
A commit without this exact trailer, or a merge commit, anywhere in this
run's commit range will cause the run to be rejected as FAILED.

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

AGENT_HANDOFF.md and evidence requirements this watcher enforces
mechanically (a run that violates any of these is marked FAILED, not
COMPLETED):
- LAST_ORCHESTRATOR_INSTRUCTION_ID must be EXACTLY {instruction_id} -- nothing
  appended or reworded.
- Every field in orchestration/PROTOCOL.md section 5 must be present exactly
  once, non-empty, with no duplicates.
- CHECKPOINT_PATH and BUNDLE_PATH must be newly added files (not edits to an
  existing file) inside orchestration/checkpoints/ and
  orchestration/bundles/ respectively, produced by this run's own commits --
  never overwrite an existing checkpoint or bundle, never point at a path
  that already existed before this run started.
- The checkpoint and bundle must be complete, structurally valid ARGUS
  documents (standard start/end markers, STATUS, GIT_COMMIT, commands run,
  test results, acceptance criteria, deviations, known debt, security state,
  next action/STOP statement) -- not placeholders.
- CURRENT_COMMIT and the checkpoint's GIT_COMMIT must resolve to commits
  created during this run.
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
    def build_state_path(self) -> Path:
        return self.repo_root / BUILD_STATE_RELPATH

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
# short structured event strings, and bounded/truncated diagnostics).
# --------------------------------------------------------------------------


def log_event(config: WatcherConfig, event: str, detail: str = "") -> None:
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    line = f"{timestamp} {event}" + (f" {detail}" if detail else "")
    with config.log_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(line, file=sys.stderr)


def _bounded_diagnostic(text: str, limit: int = 300) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) > limit:
        return cleaned[:limit] + "...[truncated]"
    return cleaned


# --------------------------------------------------------------------------
# State persistence (atomic write with fsync durability; never committed --
# gitignored). Reading is strict: a missing, unreadable, or schema-invalid
# state file is never silently treated as "fresh IDLE" -- see
# read_state_safe() and its use in tick().
# --------------------------------------------------------------------------


@dataclasses.dataclass
class WatcherState:
    last_processed_instruction_id: str | None = None
    current_instruction_id: str | None = None
    current_status: str = "IDLE"
    last_check_at: str | None = None
    last_launch_at: str | None = None
    last_exit_code: int | None = None
    last_failure_reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> WatcherState:
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in payload.items() if k in known})


def write_state(state_path: Path, state: WatcherState) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(state.to_json(), indent=2, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, state_path)  # atomic on POSIX
    try:
        dir_fd = os.open(str(state_path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass  # best-effort directory durability; not fatal if unsupported


_STATE_OPTIONAL_STR_FIELDS = (
    "last_processed_instruction_id",
    "current_instruction_id",
    "last_check_at",
    "last_launch_at",
    "last_failure_reason",
)


def _validate_state_payload(payload: Any) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "state payload is not a JSON object"
    status = payload.get("current_status")
    if not isinstance(status, str) or status not in VALID_STATUSES:
        return False, f"current_status {status!r} is not a recognized status"
    for field_name in _STATE_OPTIONAL_STR_FIELDS:
        if (
            field_name in payload
            and payload[field_name] is not None
            and not isinstance(payload[field_name], str)
        ):
            return False, f"field {field_name!r} must be a string or null"
    if "last_exit_code" in payload:
        exit_code = payload["last_exit_code"]
        if exit_code is not None and not isinstance(exit_code, int):
            return False, "field 'last_exit_code' must be an integer or null"
    return True, ""


@dataclasses.dataclass(frozen=True, slots=True)
class StateLoadResult:
    state: WatcherState | None
    outcome: str  # "OK" | "MISSING" | "INVALID"
    reason: str = ""


def read_state_safe(state_path: Path) -> StateLoadResult:
    if not state_path.exists():
        return StateLoadResult(state=None, outcome="MISSING")
    try:
        raw = state_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return StateLoadResult(
            state=None, outcome="INVALID", reason=f"unreadable or corrupt state file: {exc}"
        )
    ok, reason = _validate_state_payload(payload)
    if not ok:
        return StateLoadResult(state=None, outcome="INVALID", reason=reason)
    try:
        state = WatcherState.from_json(payload)
    except TypeError as exc:
        return StateLoadResult(state=None, outcome="INVALID", reason=f"state schema error: {exc}")
    return StateLoadResult(state=state, outcome="OK")


# --------------------------------------------------------------------------
# orchestration/ORCHESTRATOR_INSTRUCTIONS.md + AGENT_HANDOFF.md parsing
#
# Both files use plain "FIELD: value" lines near the top (see
# orchestration/PROTOCOL.md sections 4-5). This is a deliberately simple
# line-oriented parser, not a YAML/markdown parser -- it matches the exact
# contract those two files commit to. Parsing is strict: duplicate field
# lines are detected and rejected rather than silently keeping the first.
# --------------------------------------------------------------------------

_FIELD_LINE_RE = re.compile(r"^([A-Z_]+):\s*(.*)$")


def _parse_fields_all(text: str, field_names: Iterable[str]) -> dict[str, list[str]]:
    wanted = set(field_names)
    found: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = _FIELD_LINE_RE.match(line.strip())
        if match and match.group(1) in wanted:
            found.setdefault(match.group(1), []).append(match.group(2).strip())
    return found


def _parse_fields_strict(text: str, field_names: Iterable[str]) -> tuple[dict[str, str], list[str]]:
    """Returns (first-value-per-field, names that occurred more than once)."""
    all_found = _parse_fields_all(text, field_names)
    result = {name: values[0] for name, values in all_found.items()}
    duplicates = sorted(name for name, values in all_found.items() if len(values) > 1)
    return result, duplicates


def _parse_fields(text: str, field_names: Iterable[str]) -> dict[str, str]:
    """Lenient single-value parse -- used only for best-effort "before"
    snapshots, never for the mechanical accept/reject decision on new
    evidence (that always goes through _parse_fields_strict)."""
    return {name: values[0] for name, values in _parse_fields_all(text, field_names).items()}


INSTRUCTION_FIELD_NAMES = (
    "INSTRUCTION_ID",
    "ISSUED_AT",
    "TARGET_COMMIT",
    "AUTHORIZED_ACTION",
    "AUTHORIZED_PHASE",
    "APPROVES_PHASE",
    "STATUS",
)

VALID_INSTRUCTION_STATUSES = {"NO_INSTRUCTION", "ACTIVE", "SUPERSEDED"}

_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclasses.dataclass(frozen=True, slots=True)
class InstructionFields:
    instruction_id: str
    issued_at: str
    target_commit: str
    authorized_action: str
    authorized_phase: str
    approves_phase: str
    status: str


@dataclasses.dataclass(frozen=True, slots=True)
class InstructionParseResult:
    ok: bool
    fields: InstructionFields | None
    reason: str = ""


def parse_instructions(text: str) -> InstructionParseResult:
    fields, duplicates = _parse_fields_strict(text, INSTRUCTION_FIELD_NAMES)
    if duplicates:
        return InstructionParseResult(
            ok=False,
            fields=None,
            reason=f"duplicate instruction field(s): {', '.join(duplicates)}",
        )
    missing = [name for name in INSTRUCTION_FIELD_NAMES if name not in fields]
    if missing:
        return InstructionParseResult(
            ok=False,
            fields=None,
            reason=f"missing required instruction field(s): {', '.join(missing)}",
        )

    status = fields["STATUS"].strip()
    if status not in VALID_INSTRUCTION_STATUSES:
        return InstructionParseResult(ok=False, fields=None, reason=f"unknown STATUS {status!r}")

    instruction_id = fields["INSTRUCTION_ID"].strip()
    if not instruction_id:
        return InstructionParseResult(ok=False, fields=None, reason="INSTRUCTION_ID is empty")

    parsed = InstructionFields(
        instruction_id=instruction_id,
        issued_at=fields["ISSUED_AT"].strip(),
        target_commit=fields["TARGET_COMMIT"].strip(),
        authorized_action=fields["AUTHORIZED_ACTION"].strip(),
        authorized_phase=fields["AUTHORIZED_PHASE"].strip(),
        approves_phase=fields["APPROVES_PHASE"].strip(),
        status=status,
    )

    if status in {"NO_INSTRUCTION", "SUPERSEDED"}:
        # Safe/inert schema: STATUS alone already guarantees no launch can
        # occur for these, so field *content* beyond presence (checked
        # above) is not further constrained.
        return InstructionParseResult(ok=True, fields=parsed)

    # status == "ACTIVE": every field must be well-formed before this
    # instruction is trusted enough to even reach the target-commit/phase
    # checks.
    if not _UTC_TIMESTAMP_RE.match(parsed.issued_at):
        return InstructionParseResult(
            ok=False,
            fields=None,
            reason=f"ISSUED_AT {parsed.issued_at!r} is not a valid UTC timestamp",
        )
    if not _FULL_SHA_RE.match(parsed.target_commit):
        return InstructionParseResult(
            ok=False,
            fields=None,
            reason=f"TARGET_COMMIT {parsed.target_commit!r} is not a full 40-character commit SHA",
        )
    if not parsed.authorized_action or parsed.authorized_action == "NONE":
        return InstructionParseResult(
            ok=False,
            fields=None,
            reason="AUTHORIZED_ACTION is empty or NONE for an ACTIVE instruction",
        )
    if _phase_index(parsed.authorized_phase) is None:
        return InstructionParseResult(
            ok=False,
            fields=None,
            reason=f"AUTHORIZED_PHASE {parsed.authorized_phase!r} is not a recognized phase identifier",
        )
    if parsed.approves_phase != "NONE" and _phase_index(parsed.approves_phase) is None:
        return InstructionParseResult(
            ok=False,
            fields=None,
            reason=f"APPROVES_PHASE {parsed.approves_phase!r} is not NONE or a recognized phase identifier",
        )

    return InstructionParseResult(ok=True, fields=parsed)


def read_instructions(instructions_path: Path) -> InstructionParseResult:
    if not instructions_path.exists():
        return InstructionParseResult(ok=True, fields=None, reason="")
    return parse_instructions(instructions_path.read_text(encoding="utf-8"))


HANDOFF_FIELD_NAMES = (
    "HANDOFF_ID",
    "UTC_TIMESTAMP",
    "CURRENT_COMMIT",
    "CURRENT_PHASE",
    "WORK_STATUS",
    "LAST_ORCHESTRATOR_INSTRUCTION_ID",
    "CHECKPOINT_PATH",
    "BUNDLE_PATH",
    "TEST_STATUS",
    "WORKING_TREE",
    "ORCHESTRATOR_REVIEW_REQUIRED",
)


def parse_handoff(text: str) -> dict[str, str]:
    return _parse_fields(text, HANDOFF_FIELD_NAMES)


def read_handoff_fields_lenient(handoff_path: Path) -> dict[str, str]:
    """Best-effort snapshot only (used for the pre-launch HANDOFF_ID/
    already-completed cross-check) -- never the basis for accepting new
    evidence as COMPLETED. New evidence always goes through verify_handoff(),
    which uses the strict duplicate-rejecting parser."""
    if not handoff_path.exists():
        return {}
    return parse_handoff(handoff_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# docs/BUILD_STATE.md phase fields -- read as exact string tokens, never as
# a parsed int/float, so "1.5"/"6.5" round-trip exactly and PHASE_SEQUENCE
# lookups are the only source of ordering.
# --------------------------------------------------------------------------

_CURRENT_PHASE_RE = re.compile(r"^current_phase:\s*([^\s#]+)", re.MULTILINE)
_LAST_COMPLETED_PHASE_RE = re.compile(r"^last_completed_phase:\s*([^\s#]+)", re.MULTILINE)
_AWAITING_REVIEW_RE = re.compile(
    r"^awaiting_orchestrator_review:\s*(true|false)\b", re.MULTILINE | re.IGNORECASE
)


def _strip_yaml_token(raw: str) -> str:
    token = raw.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        token = token[1:-1]
    return token


@dataclasses.dataclass(frozen=True, slots=True)
class BuildStateFields:
    current_phase: str | None
    last_completed_phase: str | None
    awaiting_orchestrator_review: bool | None


def read_build_state(build_state_path: Path) -> BuildStateFields:
    if not build_state_path.exists():
        return BuildStateFields(None, None, None)
    text = build_state_path.read_text(encoding="utf-8")
    current = _CURRENT_PHASE_RE.search(text)
    last_completed = _LAST_COMPLETED_PHASE_RE.search(text)
    awaiting = _AWAITING_REVIEW_RE.search(text)
    return BuildStateFields(
        current_phase=_strip_yaml_token(current.group(1)) if current else None,
        last_completed_phase=_strip_yaml_token(last_completed.group(1)) if last_completed else None,
        awaiting_orchestrator_review=(awaiting.group(1).lower() == "true") if awaiting else None,
    )


@dataclasses.dataclass(frozen=True, slots=True)
class PhaseAuthorizationCheck:
    ok: bool
    reason: str = ""


def verify_phase_authorization(
    build_state: BuildStateFields, authorized_phase: str, approves_phase: str
) -> PhaseAuthorizationCheck:
    """AUTHORIZED_PHASE/APPROVES_PHASE are never trusted blindly.

    - Same-phase remediation (`APPROVES_PHASE: NONE`) is allowed only when
      `AUTHORIZED_PHASE == current_phase`.
    - Advancing to the immediate successor phase requires
      `APPROVES_PHASE == current_phase`, `last_completed_phase ==
      current_phase`, `awaiting_orchestrator_review == true`, and
      `AUTHORIZED_PHASE` to be the *immediate* successor of `current_phase`
      in `PHASE_SEQUENCE` -- no skipping a phase or sub-phase (e.g. Phase
      1.5 cannot be skipped on the way from 1 to 2).
    """
    if build_state.current_phase is None:
        return PhaseAuthorizationCheck(
            ok=False, reason=f"could not read current_phase from {BUILD_STATE_RELPATH}"
        )
    cur_idx = _phase_index(build_state.current_phase)
    if cur_idx is None:
        return PhaseAuthorizationCheck(
            ok=False,
            reason=f"current_phase {build_state.current_phase!r} is not a recognized phase in PHASE_SEQUENCE",
        )

    auth_idx = _phase_index(authorized_phase)
    if auth_idx is None:
        return PhaseAuthorizationCheck(
            ok=False,
            reason=f"AUTHORIZED_PHASE {authorized_phase!r} is not a recognized phase identifier",
        )

    if approves_phase == "NONE":
        if authorized_phase != build_state.current_phase:
            return PhaseAuthorizationCheck(
                ok=False,
                reason=(
                    f"APPROVES_PHASE is NONE (same-phase remediation) but AUTHORIZED_PHASE "
                    f"{authorized_phase!r} != current_phase {build_state.current_phase!r}"
                ),
            )
        return PhaseAuthorizationCheck(ok=True)

    appr_idx = _phase_index(approves_phase)
    if appr_idx is None:
        return PhaseAuthorizationCheck(
            ok=False,
            reason=f"APPROVES_PHASE {approves_phase!r} is not NONE or a recognized phase identifier",
        )
    if approves_phase != build_state.current_phase:
        return PhaseAuthorizationCheck(
            ok=False,
            reason=(
                f"APPROVES_PHASE {approves_phase!r} must equal current_phase "
                f"{build_state.current_phase!r} to advance"
            ),
        )
    if build_state.last_completed_phase != build_state.current_phase:
        return PhaseAuthorizationCheck(
            ok=False,
            reason=(
                f"last_completed_phase {build_state.last_completed_phase!r} does not equal "
                f"current_phase {build_state.current_phase!r}; phase is not complete"
            ),
        )
    if build_state.awaiting_orchestrator_review is not True:
        return PhaseAuthorizationCheck(
            ok=False, reason="awaiting_orchestrator_review is not true; nothing is pending approval"
        )
    if auth_idx != cur_idx + 1:
        return PhaseAuthorizationCheck(
            ok=False,
            reason=(
                f"AUTHORIZED_PHASE {authorized_phase!r} is not the immediate successor of "
                f"current_phase {build_state.current_phase!r} in the canonical phase sequence "
                "(no skipping a phase or sub-phase)"
            ),
        )
    return PhaseAuthorizationCheck(ok=True)


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


def git_commits_in_range(repo_root: Path, from_ref: str, to_ref: str) -> list[str]:
    result = _run_git(["rev-list", f"{from_ref}..{to_ref}"], cwd=repo_root)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def git_path_exists_at(repo_root: Path, ref: str, relpath: str) -> bool:
    result = _run_git(["cat-file", "-e", f"{ref}:{relpath}"], cwd=repo_root)
    return result.returncode == 0


def git_path_status_in_range(
    repo_root: Path, from_ref: str, to_ref: str, relpath: str
) -> str | None:
    result = _run_git(["diff", "--name-status", from_ref, to_ref, "--", relpath], cwd=repo_root)
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[-1] == relpath:
            return parts[0][:1]
    return None


def git_blob_at(repo_root: Path, ref: str, relpath: str) -> str | None:
    result = _run_git(["rev-parse", "--verify", f"{ref}:{relpath}"], cwd=repo_root)
    return result.stdout.strip() if result.returncode == 0 else None


def git_hash_object(repo_root: Path, relpath: str) -> str | None:
    full = repo_root / relpath
    if not full.exists():
        return None
    result = _run_git(["hash-object", "--", str(full)], cwd=repo_root)
    return result.stdout.strip() if result.returncode == 0 else None


_TRAILER_RECORD_SEP = "\x1e"
_TRAILER_FIELD_SEP = "\x1f"


def git_commit_bodies_in_range(
    repo_root: Path, from_ref: str, to_ref: str
) -> list[tuple[str, str]]:
    result = _run_git(
        ["log", f"--format=%H{_TRAILER_FIELD_SEP}%B{_TRAILER_RECORD_SEP}", f"{from_ref}..{to_ref}"],
        cwd=repo_root,
    )
    if result.returncode != 0:
        return []
    out: list[tuple[str, str]] = []
    for record in result.stdout.split(_TRAILER_RECORD_SEP):
        if not record.strip("\n"):
            continue
        if _TRAILER_FIELD_SEP not in record:
            continue
        sha, body = record.split(_TRAILER_FIELD_SEP, 1)
        out.append((sha.strip(), body))
    return out


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
class AncestryCheck:
    ok: bool
    reason: str = ""


def verify_run_ancestry_and_attribution(
    repo_root: Path, head_before: str | None, head_after: str | None, instruction_id: str
) -> AncestryCheck:
    """Section 4: branch movement / unattributed-commit detection.

    Post-run HEAD must descend linearly (no rewritten ancestry, no
    non-fast-forward movement, no merge commits) from pre-launch HEAD, and
    every commit in that range must carry the exact
    ``ARGUS-INSTRUCTION-ID: <instruction_id>`` trailer -- a substring or
    differently-worded trailer does not count.
    """
    if head_before is None:
        return AncestryCheck(ok=False, reason="could not resolve HEAD before launch")
    if head_after is None:
        return AncestryCheck(ok=False, reason="could not resolve HEAD after run")
    if head_after == head_before:
        return AncestryCheck(ok=False, reason="no new commits were made during this run")
    if not git_is_ancestor(repo_root, head_before, head_after):
        return AncestryCheck(
            ok=False,
            reason="post-run HEAD does not descend from pre-launch HEAD (rewritten ancestry or non-fast-forward movement)",
        )
    merges = _run_git(["rev-list", "--merges", f"{head_before}..{head_after}"], cwd=repo_root)
    if merges.returncode == 0 and merges.stdout.strip():
        return AncestryCheck(ok=False, reason="a merge commit is present in the run's commit range")

    expected_trailer = f"ARGUS-INSTRUCTION-ID: {instruction_id}"
    for sha, body in git_commit_bodies_in_range(repo_root, head_before, head_after):
        trailer_lines = {line.strip() for line in body.splitlines()}
        if expected_trailer not in trailer_lines:
            return AncestryCheck(
                ok=False,
                reason=(
                    f"commit {sha[:12]} in the run's commit range is missing the exact trailer "
                    f"{expected_trailer!r}"
                ),
            )
    return AncestryCheck(ok=True)


@dataclasses.dataclass(frozen=True, slots=True)
class InstructionsUnchangedCheck:
    ok: bool
    reason: str = ""


def verify_instructions_unchanged(
    repo_root: Path, blob_before: str | None
) -> InstructionsUnchangedCheck:
    """Section 5: mechanically prevent implementation-agent self-authorization.

    The bytes/blob of orchestration/ORCHESTRATOR_INSTRUCTIONS.md after the
    run must exactly equal the pre-launch version -- checked against the
    live working-tree file (via `git hash-object`), not just the last
    commit, so an edit that was never committed is caught too.
    """
    if blob_before is None:
        return InstructionsUnchangedCheck(
            ok=False, reason="could not resolve pre-launch orchestration instructions blob"
        )
    current = git_hash_object(repo_root, INSTRUCTIONS_RELPATH.as_posix())
    if current is None:
        return InstructionsUnchangedCheck(
            ok=False, reason="orchestration/ORCHESTRATOR_INSTRUCTIONS.md is missing after the run"
        )
    if current != blob_before:
        return InstructionsUnchangedCheck(
            ok=False,
            reason=(
                "orchestration/ORCHESTRATOR_INSTRUCTIONS.md was modified during the run "
                "(the implementation agent must not modify this file)"
            ),
        )
    return InstructionsUnchangedCheck(ok=True)


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


# --------------------------------------------------------------------------
# Evidence (checkpoint/bundle) structural validation -- section 3.
# --------------------------------------------------------------------------

CHECKPOINT_START_MARKER = "================ ARGUS ORCHESTRATOR CHECKPOINT ================"
CHECKPOINT_END_MARKER = "================ END ARGUS CHECKPOINT ========================="

_GIT_COMMIT_FIELD_RE = re.compile(r"^GIT_COMMIT:\s*(\S+)", re.MULTILINE)

_CHECKPOINT_REQUIRED_LITERAL = ("PROJECT: ARGUS", "STATUS:", "GIT_COMMIT:")
_CHECKPOINT_REQUIRED_CI = (
    "commands actually run",
    "test results",
    "acceptance criteria",
    "deviation",
    "known bug",
    "security state",
)


def validate_checkpoint_content(text: str) -> tuple[bool, str]:
    stripped = text.strip()
    if not stripped:
        return False, "checkpoint file is empty"
    lines = stripped.splitlines()
    if CHECKPOINT_START_MARKER not in lines[0]:
        return False, "checkpoint is missing the standard start marker on its first line"
    if CHECKPOINT_END_MARKER not in lines[-1]:
        return False, "checkpoint is missing the standard end marker on its last line"
    for required in _CHECKPOINT_REQUIRED_LITERAL:
        if required not in stripped:
            return False, f"checkpoint missing required field {required!r}"
    lowered = stripped.lower()
    for required_ci in _CHECKPOINT_REQUIRED_CI:
        if required_ci not in lowered:
            return False, f"checkpoint missing a section covering {required_ci!r}"
    if "scope" not in lowered and "phase" not in lowered:
        return False, "checkpoint does not identify an authorized phase or operational scope"
    if "stop" not in lowered and "next" not in lowered:
        return False, "checkpoint missing a next-action/STOP statement"
    return True, ""


def validate_bundle_content(text: str) -> tuple[bool, str]:
    stripped = text.strip()
    if not stripped:
        return False, "bundle file is empty"
    if len(stripped.splitlines()) < 5:
        return False, "bundle is too short to contain the required review sections/evidence"
    if CHECKPOINT_START_MARKER not in stripped or CHECKPOINT_END_MARKER not in stripped:
        return False, "bundle does not contain the checkpoint"
    lowered = stripped.lower()
    for required_ci in ("status", "git_commit", "test"):
        if required_ci not in lowered:
            return False, f"bundle missing required evidence referencing {required_ci!r}"
    return True, ""


def _evidence_path_error(raw: str, allowed_dir: str, allowed_suffix: str) -> str:
    if not raw or raw != raw.strip():
        return "path is empty or has surrounding whitespace"
    if raw.startswith("/") or raw.startswith("~"):
        return "absolute paths are not allowed"
    parts = PurePosixPath(raw).parts
    if ".." in parts:
        return "path traversal ('..') is not allowed"
    if not raw.startswith(f"{allowed_dir}/") or raw == f"{allowed_dir}/":
        return f"path must be a file inside {allowed_dir}/"
    if not raw.endswith(allowed_suffix):
        return f"path must end with {allowed_suffix}"
    return ""


def _validate_evidence_path(
    repo_root: Path,
    raw: str,
    *,
    allowed_dir: str,
    allowed_suffix: str,
    head_before: str,
    head_after: str,
    content_validator: Callable[[str], tuple[bool, str]],
) -> tuple[bool, str]:
    err = _evidence_path_error(raw, allowed_dir, allowed_suffix)
    if err:
        return False, err

    full = repo_root / raw
    if full.is_symlink():
        return False, "symlink evidence paths are not allowed"
    if not full.exists() or not full.is_file():
        return False, "evidence path does not exist as a regular file"
    try:
        full.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False, "resolved path escapes the repository root"

    if git_path_exists_at(repo_root, head_before, raw):
        return False, "evidence path already existed at pre-launch HEAD (stale, not newly added)"
    status = git_path_status_in_range(repo_root, head_before, head_after, raw)
    if status != "A":
        return False, (
            f"evidence path was not newly added by this run's commits (git diff status: {status!r})"
        )

    text = full.read_text(encoding="utf-8", errors="replace")
    ok, reason = content_validator(text)
    if not ok:
        return False, reason
    return True, ""


@dataclasses.dataclass(frozen=True, slots=True)
class HandoffCheck:
    ok: bool
    reason: str = ""


def verify_handoff(
    repo_root: Path,
    handoff_path: Path,
    instruction_id: str,
    handoff_id_before: str | None,
    head_before: str | None,
    head_after: str | None,
) -> HandoffCheck:
    """Verify AGENT_HANDOFF.md and its referenced evidence are genuine,
    current, complete, and structurally valid (section 3)."""
    if head_before is None or head_after is None:
        return HandoffCheck(ok=False, reason="could not resolve this run's commit range")
    if not handoff_path.exists():
        return HandoffCheck(ok=False, reason="AGENT_HANDOFF.md does not exist")

    text = handoff_path.read_text(encoding="utf-8")
    fields, duplicates = _parse_fields_strict(text, HANDOFF_FIELD_NAMES)
    if duplicates:
        return HandoffCheck(
            ok=False, reason=f"AGENT_HANDOFF.md has duplicate field(s): {', '.join(duplicates)}"
        )
    missing = [name for name in HANDOFF_FIELD_NAMES if not fields.get(name)]
    if missing:
        return HandoffCheck(
            ok=False, reason=f"AGENT_HANDOFF.md missing required field(s): {', '.join(missing)}"
        )

    new_handoff_id = fields["HANDOFF_ID"]
    if new_handoff_id == (handoff_id_before or ""):
        return HandoffCheck(
            ok=False, reason="AGENT_HANDOFF.md HANDOFF_ID was not updated (reused id)"
        )

    last_instruction = fields["LAST_ORCHESTRATOR_INSTRUCTION_ID"].strip()
    if last_instruction != instruction_id:
        return HandoffCheck(
            ok=False,
            reason=(
                f"AGENT_HANDOFF.md LAST_ORCHESTRATOR_INSTRUCTION_ID ({last_instruction!r}) "
                f"does not exactly match {instruction_id!r}"
            ),
        )

    commits_in_range = set(git_commits_in_range(repo_root, head_before, head_after))
    commits_in_range.add(head_after)

    current_commit = git_resolve_commit(repo_root, fields["CURRENT_COMMIT"])
    if current_commit is None:
        return HandoffCheck(
            ok=False,
            reason=f"CURRENT_COMMIT {fields['CURRENT_COMMIT']!r} does not resolve to a known commit",
        )
    if current_commit not in commits_in_range:
        return HandoffCheck(
            ok=False, reason="CURRENT_COMMIT does not resolve to a commit created during this run"
        )

    checkpoint_ok, checkpoint_reason = _validate_evidence_path(
        repo_root,
        fields["CHECKPOINT_PATH"],
        allowed_dir="orchestration/checkpoints",
        allowed_suffix=".md",
        head_before=head_before,
        head_after=head_after,
        content_validator=validate_checkpoint_content,
    )
    if not checkpoint_ok:
        return HandoffCheck(ok=False, reason=f"CHECKPOINT_PATH invalid: {checkpoint_reason}")

    bundle_ok, bundle_reason = _validate_evidence_path(
        repo_root,
        fields["BUNDLE_PATH"],
        allowed_dir="orchestration/bundles",
        allowed_suffix=".txt",
        head_before=head_before,
        head_after=head_after,
        content_validator=validate_bundle_content,
    )
    if not bundle_ok:
        return HandoffCheck(ok=False, reason=f"BUNDLE_PATH invalid: {bundle_reason}")

    checkpoint_text = (repo_root / fields["CHECKPOINT_PATH"]).read_text(
        encoding="utf-8", errors="replace"
    )
    git_commit_match = _GIT_COMMIT_FIELD_RE.search(checkpoint_text)
    if not git_commit_match:
        return HandoffCheck(ok=False, reason="checkpoint file has no GIT_COMMIT field")
    checkpoint_commit = git_resolve_commit(repo_root, git_commit_match.group(1))
    if checkpoint_commit is None:
        return HandoffCheck(
            ok=False, reason="checkpoint GIT_COMMIT does not resolve to a known commit"
        )
    if checkpoint_commit not in commits_in_range:
        return HandoffCheck(
            ok=False,
            reason="checkpoint GIT_COMMIT does not resolve to a commit created during this run",
        )

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


def build_claude_command(config: WatcherConfig, instruction_id: str) -> list[str]:
    return [config.claude_bin, "-p", build_claude_prompt(instruction_id), *config.claude_extra_args]


def launch_claude(
    config: WatcherConfig, instruction_id: str, runner: Runner = subprocess.run
) -> subprocess.CompletedProcess[str]:
    cmd = build_claude_command(config, instruction_id)
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
    """Run one watch iteration. Returns the resulting state.

    State-loss handling is deliberately two-staged: whether a missing state
    file may be safely initialized depends on the *post-pull* ACTIVE
    instruction (if any), which isn't known until after fetch/dirty-check/
    pull succeed. Until that's resolved, early-return branches below persist
    nothing when the on-disk state was missing, so ``read_state_safe``
    reports ``MISSING`` again next tick and the eventual resolution (a
    fresh-and-safe init, a handoff-confirmed skip, or a fail-closed block)
    still gets to run instead of being silently pre-empted by a premature
    write.
    """
    now = datetime.now(UTC).isoformat()
    load = read_state_safe(config.state_path)

    if load.outcome == "INVALID":
        # Fail closed without touching the file: we cannot safely interpret
        # it, so we must not silently "fix" it either -- that could hide the
        # very corruption an operator needs to see. The bad file stays in
        # place, so every subsequent tick fails closed the same way until a
        # human resolves it.
        log_event(config, "STATE_INVALID", load.reason)
        return WatcherState(
            current_status="FAILED", last_check_at=now, last_failure_reason=load.reason
        )

    state_was_missing = load.outcome == "MISSING"
    state = load.state if load.state is not None else WatcherState()
    state.last_check_at = now

    def _return(persist: bool = True) -> WatcherState:
        if persist:
            write_state(config.state_path, state)
        return state

    # A RUNNING or CLAIMED state found at rest means a previous watcher
    # process crashed mid-transition. Never blindly re-execute either state
    # -- require a human/orchestrator decision (a new INSTRUCTION_ID). Only
    # reachable when state existed on disk (a freshly-initialized state is
    # always IDLE).
    if state.current_status in {"RUNNING", "CLAIMED"}:
        reason = (
            f"stale {state.current_status} state found for "
            f"instruction_id={state.current_instruction_id!r} (watcher crashed mid-run); "
            "not auto-retrying"
        )
        log_event(config, "RUN_FAILED", reason)
        state.current_status = "FAILED"
        state.last_failure_reason = reason
        return _return()

    if config.pause_path.exists():
        log_event(config, "WATCHER_PAUSED", f"pause file present at {PAUSE_RELPATH}")
        return _return(persist=not state_was_missing)

    if not git_fetch(config.repo_root, config.branch):
        log_event(config, "GIT_PULL_FAILED", "git fetch failed")
        return _return(persist=not state_was_missing)

    if is_worktree_dirty(config.repo_root):
        log_event(config, "DIRTY_WORKTREE", "local worktree has uncommitted changes; not pulling")
        return _return(persist=not state_was_missing)

    if not git_pull_ff_only(config.repo_root, config.branch):
        log_event(config, "GIT_PULL_FAILED", "git pull --ff-only failed")
        return _return(persist=not state_was_missing)

    parsed = read_instructions(config.instructions_path)
    if not parsed.ok:
        log_event(config, "INSTRUCTIONS_INVALID", parsed.reason)
        return _return(persist=not state_was_missing)
    instructions = parsed.fields

    if instructions is None or instructions.status != "ACTIVE":
        log_event(
            config,
            "NO_ACTIVE_INSTRUCTION",
            f"status={instructions.status if instructions else 'MISSING'!r}",
        )
        # STATUS other than ACTIVE (including "no instructions file at
        # all") is exactly the "clearly safe condition" in which a missing
        # state file may be initialized fresh.
        return _return()

    instruction_id = instructions.instruction_id

    if state_was_missing:
        # Cross-check the current handoff so loss of local state cannot
        # replay an instruction already recorded as completed/handed off --
        # and otherwise fail closed rather than assume first execution.
        # This fully resolves the missing-state condition one way or the
        # other, so it is always persisted.
        handoff_before = read_handoff_fields_lenient(config.handoff_path)
        already_recorded_complete = (
            handoff_before.get("LAST_ORCHESTRATOR_INSTRUCTION_ID", "").strip() == instruction_id
        )
        if already_recorded_complete:
            log_event(
                config,
                "STATE_REBUILT_FROM_HANDOFF",
                f"instruction_id={instruction_id!r} already recorded complete in "
                "AGENT_HANDOFF.md; not relaunching",
            )
            state.last_processed_instruction_id = instruction_id
            state.current_status = "IDLE"
            return _return()
        reason = (
            f"state file missing while ACTIVE instruction_id={instruction_id!r} is present and "
            "AGENT_HANDOFF.md does not confirm completion; refusing to assume first execution. "
            "A new INSTRUCTION_ID is required to retry."
        )
        log_event(config, "STATE_MISSING_FAIL_CLOSED", reason)
        state.current_instruction_id = instruction_id
        state.current_status = "FAILED"
        state.last_failure_reason = reason
        return _return()

    if instruction_id == state.last_processed_instruction_id:
        return _return()

    if instruction_id == state.current_instruction_id and state.current_status in {
        "CLAIMED",
        "RUNNING",
        "FAILED",
        "COMPLETED",
    }:
        # Already attempted (or mid-claim/mid-run) this exact instruction id.
        # Never auto-retry an ambiguous or previously handled instruction --
        # a retry requires a new INSTRUCTION_ID.
        return _return()

    target_check = verify_target_commit(config.repo_root, instructions.target_commit)
    if not target_check.ok:
        log_event(config, "TARGET_COMMIT_MISMATCH", target_check.reason)
        write_state(config.state_path, state)
        return state

    build_state = read_build_state(config.build_state_path)
    phase_check = verify_phase_authorization(
        build_state, instructions.authorized_phase, instructions.approves_phase
    )
    if not phase_check.ok:
        log_event(config, "PHASE_AUTHORIZATION_INVALID", phase_check.reason)
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
    state.last_failure_reason = None
    write_state(config.state_path, state)

    head_before = git_head(config.repo_root)
    remote_before = git_remote_head(config.repo_root, config.branch)
    if head_before is None or remote_before is None or head_before != remote_before:
        reason = "local HEAD does not match origin HEAD immediately before launch"
        log_event(config, "RUN_FAILED", reason)
        state.current_status = "FAILED"
        state.last_failure_reason = reason
        write_state(config.state_path, state)
        return state

    handoff_id_before = read_handoff_fields_lenient(config.handoff_path).get("HANDOFF_ID")
    instructions_blob_before = git_blob_at(
        config.repo_root, head_before, INSTRUCTIONS_RELPATH.as_posix()
    )

    state.current_status = "RUNNING"
    state.last_launch_at = datetime.now(UTC).isoformat()
    write_state(config.state_path, state)
    log_event(config, "CLAUDE_STARTED", f"instruction_id={instruction_id!r}")

    exit_code: int | None
    diagnostic = ""
    try:
        result = launch_claude(config, instruction_id, runner=claude_runner)
        exit_code = result.returncode
        diagnostic = _bounded_diagnostic(f"{result.stdout or ''}\n{result.stderr or ''}")
        log_event(config, "CLAUDE_EXITED", f"exit_code={exit_code}")
    except subprocess.TimeoutExpired:
        exit_code = None
        diagnostic = f"timed out after {config.claude_timeout_seconds}s"
        log_event(config, "CLAUDE_EXITED", diagnostic)
    except OSError as exc:
        exit_code = None
        diagnostic = _bounded_diagnostic(f"{exc.__class__.__name__}: {exc}")
        log_event(config, "CLAUDE_EXITED", f"launch exception: {diagnostic}")

    state.last_exit_code = exit_code

    def _fail(event: str, reason: str) -> WatcherState:
        log_event(config, event, reason)
        state.current_status = "FAILED"
        state.last_failure_reason = reason[:500]
        write_state(config.state_path, state)
        return state

    # Conservative verification order (section 8):
    # 1. process exit success.
    if exit_code != 0:
        return _fail(
            "RUN_FAILED",
            f"claude process did not exit successfully (exit_code={exit_code}); {diagnostic}",
        )

    head_after = git_head(config.repo_root)

    # 2. pre/post ancestry and commit attribution.
    ancestry_check = verify_run_ancestry_and_attribution(
        config.repo_root, head_before, head_after, instruction_id
    )
    if not ancestry_check.ok:
        return _fail("RUN_FAILED", f"ancestry/attribution check failed: {ancestry_check.reason}")

    # 3. instruction file unchanged.
    instructions_check = verify_instructions_unchanged(config.repo_root, instructions_blob_before)
    if not instructions_check.ok:
        return _fail(
            "RUN_FAILED", f"instructions-file integrity check failed: {instructions_check.reason}"
        )

    # 4. complete handoff and new evidence structure.
    handoff_check = verify_handoff(
        config.repo_root,
        config.handoff_path,
        instruction_id,
        handoff_id_before,
        head_before,
        head_after,
    )
    if not handoff_check.ok:
        return _fail("RUN_FAILED", f"handoff verification failed: {handoff_check.reason}")
    log_event(config, "HANDOFF_VERIFIED", f"instruction_id={instruction_id!r}")

    # 5. clean worktree and exact pushed remote HEAD.
    push_check = verify_push_clean(config.repo_root, config.branch)
    if not push_check.ok:
        return _fail("RUN_FAILED", f"push verification failed: {push_check.reason}")

    log_event(config, "RUN_COMPLETED", f"instruction_id={instruction_id!r}")
    state.current_status = "COMPLETED"
    state.last_processed_instruction_id = instruction_id
    state.current_instruction_id = None
    state.last_failure_reason = None
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
            try:
                tick(config)
            except Exception as exc:  # noqa: BLE001 - one bad tick must not crash the watcher
                log_event(
                    config,
                    "TICK_EXCEPTION",
                    _bounded_diagnostic(f"{exc.__class__.__name__}: {exc}"),
                )
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
