from __future__ import annotations

import functools
import subprocess
from pathlib import Path

import pytest

from argus.config import (
    GIT_COMMIT_UNAVAILABLE,
    GitIdentityUnavailableError,
    git_commit_sha,
    hash_file,
    load_config,
    master_spec_hash,
    resolve_production_git_commit,
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


# --- Phase 1 remediation round 4, finding #7: production git identity ---
# --- fails closed rather than silently accepting the sentinel -----------


def _init_git_repo(repo_root: Path, *, dirty: bool = False, untracked: bool = False) -> str:
    """Creates a real, minimal git repository with exactly one commit at
    ``repo_root`` and returns its HEAD SHA. ``dirty=True`` modifies the
    committed file afterward without committing; ``untracked=True`` adds
    a new, never-added file instead -- both real repository states,
    exercised against real ``git`` subprocess calls rather than mocked,
    for the same reason every other git-identity test in this project
    prefers a real repository over mocking the git CLI."""
    run = functools.partial(
        subprocess.run, cwd=repo_root, capture_output=True, text=True, check=True
    )
    run(["git", "init", "-q"])
    run(["git", "config", "user.email", "test@example.invalid"])
    run(["git", "config", "user.name", "Test"])
    (repo_root / "committed.txt").write_text("v1\n")
    run(["git", "add", "committed.txt"])
    run(["git", "commit", "-q", "-m", "initial"])
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    if dirty:
        (repo_root / "committed.txt").write_text("v2 -- uncommitted change\n")
    if untracked:
        (repo_root / "untracked.txt").write_text("never added\n")
    return head


def test_resolve_production_git_commit_clean_checkout_returns_real_sha(tmp_path: Path) -> None:
    head = _init_git_repo(tmp_path)
    assert resolve_production_git_commit(repo_root=tmp_path, env={}) == head


def test_resolve_production_git_commit_dirty_tracked_file_raises(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, dirty=True)
    with pytest.raises(GitIdentityUnavailableError, match="uncommitted changes"):
        resolve_production_git_commit(repo_root=tmp_path, env={})


def test_resolve_production_git_commit_untracked_file_raises(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, untracked=True)
    with pytest.raises(GitIdentityUnavailableError, match="uncommitted changes"):
        resolve_production_git_commit(repo_root=tmp_path, env={})


def test_resolve_production_git_commit_missing_git_repo_raises(tmp_path: Path) -> None:
    with pytest.raises(GitIdentityUnavailableError, match="no git checkout detected"):
        resolve_production_git_commit(repo_root=tmp_path, env={})


def test_resolve_production_git_commit_allow_unverified_returns_sentinel_on_dirty(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path, dirty=True)
    assert (
        resolve_production_git_commit(repo_root=tmp_path, env={}, allow_unverified=True)
        == GIT_COMMIT_UNAVAILABLE
    )


def test_resolve_production_git_commit_allow_unverified_returns_sentinel_on_missing_repo(
    tmp_path: Path,
) -> None:
    assert (
        resolve_production_git_commit(repo_root=tmp_path, env={}, allow_unverified=True)
        == GIT_COMMIT_UNAVAILABLE
    )


def test_resolve_production_git_commit_no_git_checkout_valid_override_used(tmp_path: Path) -> None:
    override = "a" * 40
    result = resolve_production_git_commit(
        repo_root=tmp_path,  # not even a git repository -- the override never needs one
        env={"ARGUS_BUILD_GIT_COMMIT": override},
    )
    assert result == override


# --- Phase 1 remediation round 5, finding #7: round 4's implementation --
# --- checked the override BEFORE checking dirty/HEAD at all, so a -------
# --- dirty checkout could hand back any valid-looking override SHA, ----
# --- and a clean checkout's override could silently diverge from its ---
# --- real HEAD. Both are now impossible: git metadata presence and ----
# --- clean/HEAD are always resolved first; an override is only ever ----
# --- trusted when no git checkout exists at all, or when it exactly ----
# --- equals a clean checkout's real HEAD. -------------------------------


def test_resolve_production_git_commit_dirty_checkout_with_override_raises(
    tmp_path: Path,
) -> None:
    """dirty + an override that happens to equal the real (uncommitted)
    HEAD -- a dirty checkout fails closed unconditionally; the override
    can never substitute for it."""
    head = _init_git_repo(tmp_path, dirty=True)
    with pytest.raises(GitIdentityUnavailableError, match="uncommitted changes"):
        resolve_production_git_commit(repo_root=tmp_path, env={"ARGUS_BUILD_GIT_COMMIT": head})


def test_resolve_production_git_commit_dirty_checkout_with_mismatched_override_raises(
    tmp_path: Path,
) -> None:
    """dirty + an override that does NOT match HEAD either -- same
    fail-closed outcome as the matching-override case above; dirty state
    alone is dispositive."""
    _init_git_repo(tmp_path, dirty=True)
    override = "b" * 40
    with pytest.raises(GitIdentityUnavailableError, match="uncommitted changes"):
        resolve_production_git_commit(repo_root=tmp_path, env={"ARGUS_BUILD_GIT_COMMIT": override})


def test_resolve_production_git_commit_dirty_checkout_override_never_returned_even_unverified(
    tmp_path: Path,
) -> None:
    """The explicit non-production escape hatch returns the honest
    sentinel, never the (unverified) override value -- "may not turn a
    supplied or dirty identity into a verified production SHA"."""
    _init_git_repo(tmp_path, dirty=True)
    override = "c" * 40
    result = resolve_production_git_commit(
        repo_root=tmp_path, env={"ARGUS_BUILD_GIT_COMMIT": override}, allow_unverified=True
    )
    assert result == GIT_COMMIT_UNAVAILABLE
    assert result != override


def test_resolve_production_git_commit_clean_checkout_matching_override_returns_sha(
    tmp_path: Path,
) -> None:
    head = _init_git_repo(tmp_path)
    result = resolve_production_git_commit(repo_root=tmp_path, env={"ARGUS_BUILD_GIT_COMMIT": head})
    assert result == head


def test_resolve_production_git_commit_clean_checkout_mismatched_override_raises(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path)
    override = "d" * 40
    with pytest.raises(GitIdentityUnavailableError, match="does not match the resolved"):
        resolve_production_git_commit(repo_root=tmp_path, env={"ARGUS_BUILD_GIT_COMMIT": override})


def test_resolve_production_git_commit_clean_checkout_mismatched_override_unverified_sentinel(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path)
    override = "e" * 40
    result = resolve_production_git_commit(
        repo_root=tmp_path, env={"ARGUS_BUILD_GIT_COMMIT": override}, allow_unverified=True
    )
    assert result == GIT_COMMIT_UNAVAILABLE
    assert result != override


@pytest.mark.parametrize("bad_override", ["not-a-sha", "a" * 39, "a" * 41, "A" * 40])
def test_resolve_production_git_commit_invalid_override_always_raises(
    tmp_path: Path, bad_override: str
) -> None:
    with pytest.raises(GitIdentityUnavailableError, match="not a valid"):
        resolve_production_git_commit(
            repo_root=tmp_path, env={"ARGUS_BUILD_GIT_COMMIT": bad_override}
        )


def test_resolve_production_git_commit_invalid_override_raises_even_with_allow_unverified(
    tmp_path: Path,
) -> None:
    # A malformed override is a configuration bug, never silently
    # downgraded to the sentinel even in the explicit non-production
    # escape hatch.
    with pytest.raises(GitIdentityUnavailableError, match="not a valid"):
        resolve_production_git_commit(
            repo_root=tmp_path,
            env={"ARGUS_BUILD_GIT_COMMIT": "not-a-sha"},
            allow_unverified=True,
        )


def test_resolve_production_git_commit_empty_override_env_var_is_treated_as_unset(
    tmp_path: Path,
) -> None:
    head = _init_git_repo(tmp_path)
    assert (
        resolve_production_git_commit(repo_root=tmp_path, env={"ARGUS_BUILD_GIT_COMMIT": ""})
        == head
    )


# --- Phase 1 remediation round 6, finding #1: round 5's implementation --
# --- returned None from _is_dirty_checkout for *every* `git status` -----
# --- failure and treated that identically to "no checkout at all," so a --
# --- corrupt/unreadable/permission-denied-but-*present* checkout could ---
# --- still accept an arbitrary override SHA. GIT_ABSENT, GIT_PRESENT_ ----
# --- CLEAN, GIT_PRESENT_DIRTY, and GIT_PRESENT_UNVERIFIABLE are now ------
# --- always distinguished explicitly; only genuinely-absent metadata -----
# --- (no `.git` path at all) may fall back to an override. ---------------


def test_resolve_production_git_commit_metadata_present_but_status_fails_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.git` exists (metadata is present) but every git subprocess call
    fails -- e.g. a corrupt or unreadable checkout. This must fail closed
    exactly like a dirty checkout, never fall through to "no checkout"."""
    (tmp_path / ".git").mkdir()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated: git status failed against a broken checkout")

    monkeypatch.setattr("argus.config.subprocess.run", _boom)
    with pytest.raises(GitIdentityUnavailableError, match="could not be verified"):
        resolve_production_git_commit(repo_root=tmp_path, env={})


def test_resolve_production_git_commit_metadata_present_status_fails_override_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a well-formed override present alongside an unverifiable-but-
    present checkout must not be accepted -- an override only ever
    substitutes for a genuinely *absent* checkout."""
    (tmp_path / ".git").mkdir()
    override = "f" * 40

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated")

    monkeypatch.setattr("argus.config.subprocess.run", _boom)
    with pytest.raises(GitIdentityUnavailableError, match="could not be verified"):
        resolve_production_git_commit(repo_root=tmp_path, env={"ARGUS_BUILD_GIT_COMMIT": override})


def test_resolve_production_git_commit_metadata_present_status_fails_allow_unverified_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated")

    monkeypatch.setattr("argus.config.subprocess.run", _boom)
    result = resolve_production_git_commit(repo_root=tmp_path, env={}, allow_unverified=True)
    assert result == GIT_COMMIT_UNAVAILABLE


def test_resolve_production_git_commit_status_ok_but_rev_parse_head_fails_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`git status --porcelain` succeeds and reports a clean tree, but the
    subsequent `git rev-parse HEAD` call itself fails (e.g. a repository
    with a corrupted refs database). This is also PRESENT_UNVERIFIABLE in
    effect and must fail closed -- never silently accept an override."""
    (tmp_path / ".git").mkdir()

    def _fake_run(
        cmd: list[str], *args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd[:2] == ["git", "rev-parse"]:
            raise OSError("simulated: rev-parse HEAD failed")
        raise AssertionError(f"unexpected git subprocess call: {cmd}")

    monkeypatch.setattr("argus.config.subprocess.run", _fake_run)
    override = "1" * 40
    with pytest.raises(GitIdentityUnavailableError, match="rev-parse HEAD failed"):
        resolve_production_git_commit(repo_root=tmp_path, env={"ARGUS_BUILD_GIT_COMMIT": override})


def test_resolve_production_git_commit_status_ok_rev_parse_fails_allow_unverified_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()

    def _fake_run(
        cmd: list[str], *args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd[:2] == ["git", "rev-parse"]:
            raise OSError("simulated")
        raise AssertionError(f"unexpected git subprocess call: {cmd}")

    monkeypatch.setattr("argus.config.subprocess.run", _fake_run)
    result = resolve_production_git_commit(repo_root=tmp_path, env={}, allow_unverified=True)
    assert result == GIT_COMMIT_UNAVAILABLE


def test_resolve_production_git_commit_worktree_gitfile_present_but_unverifiable_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A linked worktree has a `.git` *file* (not directory) pointing at
    the real gitdir elsewhere -- still git metadata being present. A
    failing git command against it must still fail closed, simulating a
    permission-denied/corrupt-worktree scenario."""
    (tmp_path / ".git").write_text("gitdir: /nonexistent/elsewhere\n")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("simulated: permission denied reading worktree metadata")

    monkeypatch.setattr("argus.config.subprocess.run", _boom)
    with pytest.raises(GitIdentityUnavailableError, match="could not be verified"):
        resolve_production_git_commit(repo_root=tmp_path, env={})
