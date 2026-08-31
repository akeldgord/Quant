"""Tests for `argus.ingestion.parse_ledger`'s build/config/MASTER_SPEC/git
identity capture (Phase 1 remediation round 3, finding #5).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from argus.config import ArgusConfig
from argus.ingestion.parse_ledger import ParseAttemptIdentity, capture_parse_identity
from argus.parsing.generic_parser import PARSER_BUILD_HASH


def _config() -> ArgusConfig:
    return ArgusConfig(values={"x": 1}, sources=(Path("dummy.yaml"),), env={"SECRET": "s3cr3t"})


def test_capture_parse_identity_every_field_non_empty() -> None:
    identity = capture_parse_identity(_config())
    assert identity.build_hash
    assert identity.config_hash
    assert identity.master_spec_hash
    assert identity.git_commit


def test_capture_parse_identity_uses_the_parser_module_build_hash() -> None:
    identity = capture_parse_identity(_config())
    assert identity.build_hash == PARSER_BUILD_HASH


def test_capture_parse_identity_config_hash_matches_the_config_object() -> None:
    config = _config()
    identity = capture_parse_identity(config)
    assert identity.config_hash == config.config_hash


def test_capture_parse_identity_reflects_config_changes() -> None:
    config_a = ArgusConfig(values={"x": 1}, sources=(Path("a.yaml"),), env={})
    config_b = ArgusConfig(values={"x": 2}, sources=(Path("a.yaml"),), env={})
    identity_a = capture_parse_identity(config_a)
    identity_b = capture_parse_identity(config_b)
    assert identity_a.config_hash != identity_b.config_hash
    # Everything else (build/spec/git) is process-global, not config-tree
    # derived, so it is correctly identical across the two captures.
    assert identity_a.build_hash == identity_b.build_hash
    assert identity_a.master_spec_hash == identity_b.master_spec_hash
    assert identity_a.git_commit == identity_b.git_commit


def test_parser_build_hash_is_a_reproducible_sha256_of_the_parser_source() -> None:
    import hashlib

    from argus.parsing import generic_parser

    expected = hashlib.sha256(Path(generic_parser.__file__).read_bytes()).hexdigest()
    assert expected == PARSER_BUILD_HASH
    assert len(PARSER_BUILD_HASH) == 64


def test_parse_attempt_identity_is_a_frozen_value_object() -> None:
    identity = ParseAttemptIdentity(
        build_hash="a", config_hash="b", master_spec_hash="c", git_commit="d"
    )
    assert identity.build_hash == "a"
    with pytest.raises(AttributeError):
        identity.build_hash = "changed"  # type: ignore[misc]
