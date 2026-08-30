"""Orchestrator review bundle generation (MASTER_SPEC.md section 105).

``argus checkpoint bundle --phase <N>`` runs a fixed set of read-only
introspection commands against the actual repository/environment and writes
their real output to ``runtime/reports/orchestrator_bundle_phase_<N>.txt``.
Nothing here is allowed to fabricate a result: every section is either the
literal captured stdout/stderr of a command, or an explicit
``"not available: <reason>"`` line.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from argus.config import REPO_ROOT, ArgusConfig, load_config, master_spec_hash

REPORTS_DIR = REPO_ROOT / "runtime" / "reports"


@dataclass
class CommandResult:
    command: str
    output: str
    ok: bool


def run(cmd: list[str], cwd: Path = REPO_ROOT, timeout: int = 120) -> CommandResult:
    display = " ".join(cmd)
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
        output = proc.stdout
        if proc.stderr:
            output += ("\n" if output else "") + proc.stderr
        return CommandResult(command=display, output=output.strip(), ok=proc.returncode == 0)
    except FileNotFoundError as exc:
        return CommandResult(command=display, output=f"not available: {exc}", ok=False)
    except subprocess.TimeoutExpired:
        return CommandResult(command=display, output="not available: command timed out", ok=False)


def _section(title: str, result: CommandResult) -> str:
    status = "ok" if result.ok else "non-zero exit / unavailable"
    body = result.output if result.output else "(no output)"
    return f"--- {title} ({status}) ---\n$ {result.command}\n{body}\n"


def repo_tree(max_depth: int = 3) -> str:
    result = run(
        [
            "find",
            ".",
            "-maxdepth",
            str(max_depth),
            "-not",
            "-path",
            "./.git*",
            "-not",
            "-path",
            "*/__pycache__*",
        ]
    )
    lines = sorted(line for line in result.output.splitlines() if line)
    return "\n".join(lines)


def build_bundle_text(phase: int, checkpoint_text: str | None = None) -> str:
    parts: list[str] = []
    now = datetime.now(UTC).isoformat()
    parts.append(f"ARGUS ORCHESTRATOR REVIEW BUNDLE — Phase {phase}\nGenerated: {now}\n")

    if checkpoint_text:
        parts.append("=== CHECKPOINT ===\n" + checkpoint_text.strip() + "\n")
    else:
        parts.append("=== CHECKPOINT ===\nnot available: no --checkpoint-file provided\n")

    parts.append(_section("git status --porcelain", run(["git", "status", "--porcelain"])))
    parts.append(_section("git log -5 --oneline", run(["git", "log", "-5", "--oneline"])))
    parts.append(_section("git diff --stat HEAD", run(["git", "diff", "--stat", "HEAD"])))
    parts.append(
        _section("git diff --name-status HEAD", run(["git", "diff", "--name-status", "HEAD"]))
    )

    parts.append("--- repository tree (depth 3) ---\n" + repo_tree() + "\n")

    parts.append(_section("dependency summary (uv pip list)", run(["uv", "pip", "list"])))
    parts.append(
        _section(
            "compose service summary",
            run(["docker", "compose", "config", "--services"]),
        )
    )
    parts.append(
        _section(
            "alembic head",
            run(["uv", "run", "alembic", "current"]),
        )
    )

    try:
        spec_hash = master_spec_hash()
    except FileNotFoundError as exc:
        spec_hash = f"not available: {exc}"
    parts.append(f"--- MASTER_SPEC hash ---\n{spec_hash}\n")

    build_state_path = REPO_ROOT / "docs" / "BUILD_STATE.md"
    parts.append(
        "--- BUILD_STATE.md ---\n"
        + (build_state_path.read_text() if build_state_path.exists() else "not available: missing")
        + "\n"
    )

    decision_log_path = REPO_ROOT / "docs" / "DECISION_LOG.md"
    parts.append(
        "--- DECISION_LOG.md ---\n"
        + (
            decision_log_path.read_text()
            if decision_log_path.exists()
            else "not available: missing"
        )
        + "\n"
    )

    return "\n".join(parts)


def write_bundle(phase: int, checkpoint_text: str | None = None) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    text = build_bundle_text(phase=phase, checkpoint_text=checkpoint_text)
    out_path = REPORTS_DIR / f"orchestrator_bundle_phase_{phase}.txt"
    out_path.write_text(text)
    return out_path


def load_config_for_checkpoint() -> ArgusConfig:
    return load_config()
