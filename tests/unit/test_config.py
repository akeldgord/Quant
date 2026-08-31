from __future__ import annotations

from pathlib import Path

import pytest

from argus.config import (
    GIT_COMMIT_UNAVAILABLE,
    git_commit_sha,
    hash_file,
    load_config,
    master_spec_hash,
)


def _write_yaml(path: Path, content: str) -> None:
    path.write_text(content)


def test_load_config_merges_files_in_order(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(config_dir / "a.yaml", "top: 1\nnested:\n  x: 1\n")
    _write_yaml(config_dir / "b.yaml", "nested:\n  y: 2\n")

    config = load_config(config_dir=config_dir, files=("a.yaml", "b.yaml"), environ={})

    assert config.get("top") == 1
    assert config.get("nested.x") == 1
    assert config.get("nested.y") == 2
    assert len(config.sources) == 2


def test_load_config_later_file_overrides_earlier(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(config_dir / "a.yaml", "value: from_a\n")
    _write_yaml(config_dir / "b.yaml", "value: from_b\n")

    config = load_config(config_dir=config_dir, files=("a.yaml", "b.yaml"), environ={})

    assert config.get("value") == "from_b"


def test_config_hash_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(config_dir / "a.yaml", "value: 1\n")

    c1 = load_config(config_dir=config_dir, files=("a.yaml",), environ={})
    c2 = load_config(config_dir=config_dir, files=("a.yaml",), environ={})
    assert c1.config_hash == c2.config_hash

    _write_yaml(config_dir / "a.yaml", "value: 2\n")
    c3 = load_config(config_dir=config_dir, files=("a.yaml",), environ={})
    assert c3.config_hash != c1.config_hash


def test_config_hash_ignores_env_secrets(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(config_dir / "a.yaml", "value: 1\n")

    c1 = load_config(config_dir=config_dir, files=("a.yaml",), environ={})
    c2 = load_config(
        config_dir=config_dir,
        files=("a.yaml",),
        environ={"ARGUS_DB_INGEST_PASSWORD": "super-secret"},
    )
    # config_hash reflects behavioral YAML config only, not env/secrets.
    assert c1.config_hash == c2.config_hash
    # but the secret is still available to callers that actually need it.
    assert c2.env["ARGUS_DB_INGEST_PASSWORD"] == "super-secret"


def test_master_spec_hash_reproducible(tmp_path: Path) -> None:
    spec_path = tmp_path / "MASTER_SPEC.md"
    spec_path.write_text("hello world")

    h1 = hash_file(spec_path)
    h2 = master_spec_hash(spec_path)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex digest


def test_master_spec_hash_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        master_spec_hash(tmp_path / "does_not_exist.md")


def test_real_master_spec_file_hashes_successfully() -> None:
    # The real repo-root MASTER_SPEC.md must exist and be hashable —
    # this is part of the Phase 0 acceptance criteria ("MASTER_SPEC hash
    # generated").
    h = master_spec_hash()
    assert len(h) == 64


# --- Phase 1 remediation round 3, finding #5: git commit identity -------


def test_git_commit_sha_returns_the_real_repo_head() -> None:
    sha = git_commit_sha()
    assert sha != GIT_COMMIT_UNAVAILABLE
    assert len(sha) == 40  # a real git commit SHA-1 hex digest
    assert all(c in "0123456789abcdef" for c in sha)


def test_git_commit_sha_is_stable_across_repeated_calls() -> None:
    assert git_commit_sha() == git_commit_sha()


def test_git_commit_sha_returns_sentinel_when_not_a_git_repository(tmp_path: Path) -> None:
    # tmp_path is never a git checkout -- `git rev-parse HEAD` fails, and
    # this must never raise or fabricate a commit SHA, only return the
    # explicit sentinel.
    assert git_commit_sha(repo_root=tmp_path) == GIT_COMMIT_UNAVAILABLE


def test_git_commit_sha_returns_sentinel_when_git_binary_missing(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("PATH", "")
    assert git_commit_sha() == GIT_COMMIT_UNAVAILABLE
