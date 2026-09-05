"""argus.executor.canary — Clarification-002
(``argus-final-spec-recovery-002-clarification-002``) section 2: the
explicit, machine-checkable human-canary execution mode.

The frozen contract requires that a future Phase 6.5 human canary be
executable WITHOUT another code change, while ``canary_passed`` must stay
impossible for ordinary live operation before Phase 6.5 succeeds. This
module is the external, human-authored, hash/expiry-validated
authorization gate for exactly that first pre-pass canary attempt --
mirroring ``argus.executor.arm``'s own architecture for the arm file, not
inventing a second one: read-only, fails closed on any problem, and bound
to BOTH the running build/config identity (an authorization approved for
a different git commit/executor build/risk config can never authorize
this running build) AND the exact intent it authorizes (an authorization
can never be silently reused for a different, later intent).

This is never sourced from the operator's generic single-intent params
file (``argus.executor.main``'s own ``_LIVE_RISK_INPUTS_REAL_ONLY_
FIELDS`` already forbids that file from ever supplying ``canary_passed``
directly) -- it is a wholly separate artifact, at a separate path, an
operator must explicitly create.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from argus.executor.arm import ApprovedIdentity

_REQUIRED_STRING_FIELDS: tuple[str, ...] = (
    "intent_id",
    "expires_at",
    "approved_git_commit",
    "approved_executor_build_hash",
    "approved_risk_config_hash",
)


@dataclass(frozen=True)
class CanaryAuthorizationResult:
    authorized: bool
    reason: str | None = None


def validate_canary_authorization_file(
    path: Path, *, approved: ApprovedIdentity, now: datetime, intent_id: uuid.UUID
) -> CanaryAuthorizationResult:
    """Read-only -- never writes ``path``. Fails closed
    (``authorized=False``) on any problem: missing file, unreadable file,
    malformed JSON, wrong shape, missing/invalid field, expiry, an
    ``intent_id`` that does not match the SPECIFIC intent being
    authorized, or any ``approved_*`` mismatch. Never treats a
    generic/reusable boolean as authorization -- every field must
    independently validate."""
    if not path.exists():
        return CanaryAuthorizationResult(
            authorized=False, reason="canary authorization file missing"
        )
    try:
        raw = path.read_text()
    except OSError as exc:
        return CanaryAuthorizationResult(
            authorized=False, reason=f"canary authorization file unreadable: {exc}"
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return CanaryAuthorizationResult(
            authorized=False, reason=f"canary authorization file malformed JSON: {exc}"
        )
    if not isinstance(data, dict):
        return CanaryAuthorizationResult(
            authorized=False, reason="canary authorization file is not a JSON object"
        )

    if data.get("canary_authorized") is not True:
        return CanaryAuthorizationResult(
            authorized=False,
            reason="canary authorization file 'canary_authorized' is not literal true",
        )

    for field in _REQUIRED_STRING_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value:
            return CanaryAuthorizationResult(
                authorized=False, reason=f"missing/invalid field: {field}"
            )

    if data["intent_id"] != str(intent_id):
        return CanaryAuthorizationResult(
            authorized=False,
            reason=(
                f"canary authorization intent_id {data['intent_id']!r} does not match the "
                f"intent being executed {intent_id!s}"
            ),
        )

    try:
        expires_at = datetime.fromisoformat(str(data["expires_at"]))
    except ValueError:
        return CanaryAuthorizationResult(
            authorized=False, reason="expires_at is not valid ISO-8601"
        )
    if expires_at.tzinfo is None:
        return CanaryAuthorizationResult(
            authorized=False, reason="expires_at is not timezone-aware"
        )
    if expires_at <= now:
        return CanaryAuthorizationResult(authorized=False, reason="canary authorization expired")

    if data["approved_git_commit"] != approved.git_commit:
        return CanaryAuthorizationResult(authorized=False, reason="approved_git_commit mismatch")
    if data["approved_executor_build_hash"] != approved.executor_build_hash:
        return CanaryAuthorizationResult(
            authorized=False, reason="approved_executor_build_hash mismatch"
        )
    if data["approved_risk_config_hash"] != approved.risk_config_hash:
        return CanaryAuthorizationResult(
            authorized=False, reason="approved_risk_config_hash mismatch"
        )

    return CanaryAuthorizationResult(authorized=True)
