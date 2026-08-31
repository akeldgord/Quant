"""Configuration loading + hashing (MASTER_SPEC.md CORE-004, section 98).

Every meaningful decision ARGUS makes must be traceable to an exact
``config_hash`` and, transitively, to the exact MASTER_SPEC.md contract it
was built against. This module is the single place that:

- loads YAML config files from ``config/`` plus environment overrides,
- computes a stable, reproducible hash of the *effective* configuration,
- computes a hash of MASTER_SPEC.md itself so every checkpoint can prove
  which version of the contract the running code corresponds to.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
MASTER_SPEC_PATH = REPO_ROOT / "MASTER_SPEC.md"

DEFAULT_CONFIG_FILES: tuple[str, ...] = (
    "argus.default.yaml",
    "providers.yaml",
    "scoring_v1.yaml",
    "signals_v1.yaml",
    "risk.default.yaml",
)


def _stable_hash(payload: Any) -> str:
    """SHA-256 of a canonical JSON encoding — stable across dict ordering."""
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def hash_file(path: Path) -> str:
    """SHA-256 of a file's raw bytes, e.g. for MASTER_SPEC.md (section 104)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def master_spec_hash(path: Path = MASTER_SPEC_PATH) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"MASTER_SPEC.md not found at {path} — it must be saved verbatim at the repo root."
        )
    return hash_file(path)


GIT_COMMIT_UNAVAILABLE = "GIT_COMMIT_UNAVAILABLE"


def git_commit_sha(repo_root: Path = REPO_ROOT) -> str:
    """Phase 1 remediation round 3, finding #5: the git identity CORE-004
    requires every meaningful decision to record, e.g. on a durable parse
    attempt (``argus.ingestion.parse_ledger.ParseAttemptIdentity``).

    Runs ``git rev-parse HEAD`` against ``repo_root``. Never raises: a
    missing ``git`` binary, a non-repository checkout, or any other
    failure returns the explicit sentinel ``GIT_COMMIT_UNAVAILABLE``
    rather than fabricating a commit SHA -- this is a best-effort
    identity capture, not something that may ever abort the durable write
    it is attached to.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return GIT_COMMIT_UNAVAILABLE
    sha = result.stdout.strip()
    return sha if sha else GIT_COMMIT_UNAVAILABLE


class GitIdentityUnavailableError(RuntimeError):
    """Raised by :func:`resolve_production_git_commit` when a validated,
    exact point-in-time git commit identity cannot be established (Phase
    1 remediation round 4, finding #7). Production ingestion/reparse must
    fail closed here rather than silently recording the best-effort
    ``GIT_COMMIT_UNAVAILABLE`` sentinel as if it were a real identity --
    that sentinel is only ever acceptable from an explicit, non-production
    caller (``allow_unverified=True``: --test-mode, or a unit test)."""


GIT_BUILD_COMMIT_ENV_VAR = "ARGUS_BUILD_GIT_COMMIT"
_FULL_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class _GitCheckoutState(enum.Enum):
    """Phase 1 remediation round 6, finding #1. Round 5's
    ``_is_dirty_checkout`` returned ``None`` for *every* ``git status``
    failure and the resolver treated that as "no git checkout" -- so a
    corrupt, unreadable, permission-denied, or otherwise broken checkout
    (git metadata present, but unverifiable) was indistinguishable from a
    directory that was never a git repository at all, and a build-time
    override was accepted in both cases. These four states are always
    distinguished explicitly; only ``ABSENT`` may ever fall back to an
    override."""

    ABSENT = "GIT_ABSENT"
    PRESENT_CLEAN = "GIT_PRESENT_CLEAN"
    PRESENT_DIRTY = "GIT_PRESENT_DIRTY"
    PRESENT_UNVERIFIABLE = "GIT_PRESENT_UNVERIFIABLE"


def _git_metadata_present(repo_root: Path) -> bool:
    """Whether git metadata is detectable at ``repo_root`` at all: a
    ``.git`` directory (a normal checkout) or a ``.git`` *file* (a linked
    worktree, which stores a ``gitdir: <path>`` pointer instead of the
    metadata itself). This is a pure filesystem check, independent of
    whether the ``git`` binary is installed or the repository is
    otherwise healthy -- it is exactly the signal that decides whether a
    later failure to run a git command means "no checkout" (an override
    may substitute) or "unverifiable checkout" (must fail closed)."""
    return (repo_root / ".git").exists()


def _probe_git_checkout_state(repo_root: Path) -> _GitCheckoutState:
    """Classifies ``repo_root`` into exactly one of the four
    :class:`_GitCheckoutState` values. A failed git command is *never*,
    by itself, evidence that git metadata is absent -- only a missing
    ``.git`` path is."""
    if not _git_metadata_present(repo_root):
        return _GitCheckoutState.ABSENT
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return _GitCheckoutState.PRESENT_UNVERIFIABLE
    dirty = bool(result.stdout.strip())
    return _GitCheckoutState.PRESENT_DIRTY if dirty else _GitCheckoutState.PRESENT_CLEAN


def resolve_production_git_commit(
    *,
    repo_root: Path = REPO_ROOT,
    env: dict[str, str] | None = None,
    allow_unverified: bool = False,
) -> str:
    """The exact, reproducible point-in-time git commit identity required
    for production ingestion/reparse parse-attempt evidence (MASTER_SPEC.md
    CORE-004; Phase 1 remediation round 4, finding #7; round 5, finding
    #7 fixed an override-precedence defect in round 4's implementation;
    round 6, finding #1 fixed round 5's remaining fail-open gap for a
    present-but-unverifiable checkout).

    Unlike :func:`git_commit_sha` (best-effort, never raises), this fails
    closed by default: a dirty or unverifiable checkout, a missing git
    checkout with no override, an override that disagrees with a real
    checkout's HEAD, or a malformed override all raise
    :class:`GitIdentityUnavailableError` rather than silently degrading to
    the ``GIT_COMMIT_UNAVAILABLE`` sentinel. Resolution order:

    1. ``ARGUS_BUILD_GIT_COMMIT`` env var, if set, is first validated as a
       full 40-character lowercase hex SHA -- an invalid value always
       raises immediately, even with ``allow_unverified=True``; a
       malformed override is a configuration bug, never silently
       downgraded.
    2. ``repo_root`` is classified into exactly one of four
       :class:`_GitCheckoutState` values *before* the override is ever
       trusted: ``ABSENT`` (no ``.git`` metadata at all), ``PRESENT_CLEAN``,
       ``PRESENT_DIRTY``, or ``PRESENT_UNVERIFIABLE`` (metadata is present
       but ``git status`` could not be run or failed -- a corrupt,
       permission-denied, or otherwise broken checkout). A failed git
       command is *never*, by itself, evidence that git metadata is
       absent -- round 5's implementation returned ``None`` for every
       ``git status`` failure and treated that identically to "no
       checkout," so a broken-but-present checkout could still be
       represented by an arbitrary override SHA. Only a genuinely missing
       ``.git`` path yields ``ABSENT``.
    3. If the state is **ABSENT**, a well-formed override is the only
       possible source of an identity (there's a real checkout to verify a
       live HEAD against) and is returned directly -- this is the one case
       a build-time override (e.g. baked in at image build time for a
       checkout with no ``.git`` directory present at runtime) is actually
       used.
    4. If the state is **PRESENT_UNVERIFIABLE** or **PRESENT_DIRTY**, the
       call fails closed unconditionally -- an override can never
       substitute for either. Only when the state is **PRESENT_CLEAN** is
       the real ``git rev-parse HEAD`` resolved; a supplied override must
       then exactly equal that HEAD or the call fails closed. An override
       is never used to silently override or diverge from what the
       checkout actually contains.

    ``allow_unverified=True`` is the explicit non-production escape hatch
    (``--test-mode``, or a unit test that isn't itself testing this
    fail-closed behavior): every failure mode *except* a malformed
    override then returns ``GIT_COMMIT_UNAVAILABLE`` instead of raising --
    it never turns a supplied-but-unverifiable, dirty-checkout, or
    unverifiable-checkout identity into a value that looks like a verified
    production SHA.
    """
    environ = env if env is not None else dict(os.environ)
    override = environ.get(GIT_BUILD_COMMIT_ENV_VAR, "").strip()
    if override and not _FULL_GIT_SHA_RE.match(override):
        raise GitIdentityUnavailableError(
            f"{GIT_BUILD_COMMIT_ENV_VAR} is set but is not a valid 40-character "
            f"lowercase hex git commit SHA: {override!r}"
        )

    state = _probe_git_checkout_state(repo_root)

    if state is _GitCheckoutState.ABSENT:
        # No git metadata at all: nothing exists to verify a live HEAD
        # against, so a well-formed override is the only possible source.
        if override:
            return override
        if allow_unverified:
            return GIT_COMMIT_UNAVAILABLE
        raise GitIdentityUnavailableError(
            f"no git checkout detected at {repo_root} and no valid "
            f"{GIT_BUILD_COMMIT_ENV_VAR} build-time override is set -- production "
            "ingestion cannot establish a validated git identity"
        )

    # Git metadata is present -- a failed git command from here on is
    # never treated as if metadata were absent (Phase 1 remediation round
    # 6, finding #1). Clean state and the real HEAD are always verified
    # before an override is ever trusted.
    if state is _GitCheckoutState.PRESENT_UNVERIFIABLE:
        if allow_unverified:
            return GIT_COMMIT_UNAVAILABLE
        raise GitIdentityUnavailableError(
            f"git metadata is present at {repo_root} but its clean/dirty state "
            "could not be verified -- git status failed, or the checkout is "
            "corrupt, unreadable, or otherwise broken. Production ingestion "
            "cannot establish a validated git identity, and "
            f"{GIT_BUILD_COMMIT_ENV_VAR} is never accepted as a substitute for "
            "an unverifiable checkout -- an override is only used when git "
            "metadata is genuinely absent."
        )

    if state is _GitCheckoutState.PRESENT_DIRTY:
        if allow_unverified:
            return GIT_COMMIT_UNAVAILABLE
        raise GitIdentityUnavailableError(
            f"git checkout at {repo_root} has uncommitted changes -- production "
            "ingestion requires an exact, reproducible git identity; commit or "
            f"stash before running. {GIT_BUILD_COMMIT_ENV_VAR} is never accepted "
            "as a substitute for a dirty checkout -- an override is only used "
            "when no git checkout is present at all."
        )

    sha = git_commit_sha(repo_root)
    if sha == GIT_COMMIT_UNAVAILABLE:
        if allow_unverified:
            return GIT_COMMIT_UNAVAILABLE
        raise GitIdentityUnavailableError(
            f"git rev-parse HEAD failed at {repo_root} even though the checkout "
            "appeared clean -- production ingestion cannot establish a validated "
            "git identity"
        )

    if override and override != sha:
        if allow_unverified:
            return GIT_COMMIT_UNAVAILABLE
        raise GitIdentityUnavailableError(
            f"{GIT_BUILD_COMMIT_ENV_VAR} ({override}) does not match the resolved "
            f"git HEAD ({sha}) at {repo_root} -- an override present alongside a "
            "real git checkout must exactly equal HEAD, never silently diverge "
            "from what the checkout actually contains"
        )
    return sha


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass
class ArgusConfig:
    """Effective, merged ARGUS configuration."""

    values: dict[str, Any] = field(default_factory=dict)
    sources: tuple[Path, ...] = field(default_factory=tuple)
    env: dict[str, str] = field(default_factory=dict)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self.values
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def config_hash(self) -> str:
        """Reproducible hash of the effective config (files + relevant env).

        Only *non-secret* environment overrides that were actually applied are
        included, keyed by name only when relevant to config shape — secret
        values themselves are never hashed alongside plaintext in a way that
        would leak them into a checkpoint; the checkpoint only ever prints the
        hash, never the inputs.
        """
        return _stable_hash({"values": self.values, "source_files": [str(p) for p in self.sources]})

    @property
    def spec_hash(self) -> str:
        return master_spec_hash()


def load_config(
    config_dir: Path = CONFIG_DIR,
    files: tuple[str, ...] = DEFAULT_CONFIG_FILES,
    env_file: Path | None = None,
    environ: dict[str, str] | None = None,
) -> ArgusConfig:
    """Load and merge YAML config files in a fixed, deterministic order.

    Later files in ``files`` override earlier ones. This does not apply
    environment-variable substitution beyond loading ``.env`` (via
    ``python-dotenv``) into :attr:`ArgusConfig.env` for callers that need
    secrets/connection info — those values deliberately do NOT participate in
    ``config_hash`` computation of the YAML config tree itself, since
    ``config_hash`` exists to identify *behavioral* configuration, not
    credentials.
    """
    merged: dict[str, Any] = {}
    sources: list[Path] = []
    for name in files:
        path = config_dir / name
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Config file {path} must contain a YAML mapping at the top level")
        merged = _deep_merge(merged, loaded)
        sources.append(path)

    env_values: dict[str, str] = {}
    dotenv_path = env_file if env_file is not None else REPO_ROOT / ".env"
    if dotenv_path.exists():
        env_values.update({k: v for k, v in dotenv_values(dotenv_path).items() if v is not None})
    env_values.update(
        {k: v for k, v in (environ or dict(os.environ)).items() if k.startswith("ARGUS_")}
    )

    return ArgusConfig(values=merged, sources=tuple(sources), env=env_values)
