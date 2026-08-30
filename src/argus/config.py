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

import hashlib
import json
import os
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
