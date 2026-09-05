"""Clarification-002 section 2 (``argus-final-spec-recovery-002-
clarification-002``): ``argus.executor.canary.validate_canary_
authorization_file`` -- the external, human-authored, hash/expiry/
intent-bound authorization gate for the very first Phase 6.5 canary
attempt. Mirrors ``argus.executor.arm``'s own test discipline: every
failure mode fails closed with a specific reason, never silently.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from argus.executor.arm import ApprovedIdentity
from argus.executor.canary import CanaryAuthorizationResult, validate_canary_authorization_file

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_INTENT_ID = uuid.uuid4()


def _approved() -> ApprovedIdentity:
    return ApprovedIdentity(
        git_commit="a" * 40,
        executor_build_hash="buildhash",
        risk_config_hash="confighash",
        strategy_versions=frozenset({"v1"}),
    )


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "canary_authorized": True,
        "intent_id": str(_INTENT_ID),
        "expires_at": (_NOW + timedelta(hours=1)).isoformat(),
        "approved_git_commit": "a" * 40,
        "approved_executor_build_hash": "buildhash",
        "approved_risk_config_hash": "confighash",
    }
    payload.update(overrides)
    return payload


def _validate(path: Path) -> CanaryAuthorizationResult:
    return validate_canary_authorization_file(
        path, approved=_approved(), now=_NOW, intent_id=_INTENT_ID
    )


def _reason(result: CanaryAuthorizationResult) -> str:
    assert result.reason is not None
    return result.reason


def test_valid_authorization_is_authorized(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    path.write_text(json.dumps(_valid_payload()))
    assert _validate(path).authorized is True


def test_missing_file_fails_closed(tmp_path: Path) -> None:
    result = _validate(tmp_path / "does-not-exist.json")
    assert result.authorized is False
    assert "missing" in _reason(result)


def test_malformed_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    path.write_text("{not valid json")
    result = _validate(path)
    assert result.authorized is False
    assert "malformed" in _reason(result)


def test_non_object_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    path.write_text(json.dumps([1, 2, 3]))
    assert _validate(path).authorized is False


def test_canary_authorized_not_literal_true_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    path.write_text(json.dumps(_valid_payload(canary_authorized="true")))
    result = _validate(path)
    assert result.authorized is False
    assert "canary_authorized" in _reason(result)


def test_missing_required_field_fails_closed(tmp_path: Path) -> None:
    for field in (
        "intent_id",
        "expires_at",
        "approved_git_commit",
        "approved_executor_build_hash",
        "approved_risk_config_hash",
    ):
        payload = _valid_payload()
        del payload[field]
        path = tmp_path / f"canary-{field}.json"
        path.write_text(json.dumps(payload))
        result = _validate(path)
        assert result.authorized is False, field
        assert field in _reason(result), field


def test_intent_id_mismatch_fails_closed(tmp_path: Path) -> None:
    """The exact defect the frozen contract forbids: an authorization
    file must never be silently reusable for a different, later intent."""
    path = tmp_path / "canary.json"
    path.write_text(json.dumps(_valid_payload(intent_id=str(uuid.uuid4()))))
    result = _validate(path)
    assert result.authorized is False
    assert "intent_id" in _reason(result)


def test_expired_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    path.write_text(
        json.dumps(_valid_payload(expires_at=(_NOW - timedelta(seconds=1)).isoformat()))
    )
    result = _validate(path)
    assert result.authorized is False
    assert "expired" in _reason(result)


def test_expires_at_naive_datetime_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    path.write_text(json.dumps(_valid_payload(expires_at="2025-06-01T13:00:00")))
    result = _validate(path)
    assert result.authorized is False
    assert "timezone" in _reason(result)


def test_expires_at_invalid_format_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    path.write_text(json.dumps(_valid_payload(expires_at="not-a-date")))
    assert _validate(path).authorized is False


def test_git_commit_mismatch_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    path.write_text(json.dumps(_valid_payload(approved_git_commit="b" * 40)))
    result = _validate(path)
    assert result.authorized is False
    assert "git_commit" in _reason(result)


def test_build_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    path.write_text(json.dumps(_valid_payload(approved_executor_build_hash="wrong")))
    result = _validate(path)
    assert result.authorized is False
    assert "build_hash" in _reason(result)


def test_config_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    path.write_text(json.dumps(_valid_payload(approved_risk_config_hash="wrong")))
    result = _validate(path)
    assert result.authorized is False
    assert "config_hash" in _reason(result)
