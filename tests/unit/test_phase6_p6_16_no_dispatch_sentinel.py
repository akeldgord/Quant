"""P6-16 (SAFETY_OR_INTEGRITY_BLOCKING): Phase 6 cannot accidentally
perform live network execution -- MASTER_SPEC.md sections 70/78,
orchestrator instruction ``argus-phase-6-001``.

The ``argus executor readiness`` CLI path is run end-to-end through the
same Typer app a human operator uses, with its output scanned for any
fake-secret-shaped value -- proving no credential-shaped content ever
appears in report output. A second test proves the default guard's
submission/signing seam always raises when reached (never a silent
no-op that could mask an accidental real call).
"""

from __future__ import annotations

import re

from typer.testing import CliRunner

from argus.cli import app
from argus.executor.dispatch import DispatchGuard, DispatchNeverCalledError, raising_submission
from argus.executor.signing import RaisingSigner, SignerNeverCalledError

runner = CliRunner()

# Deliberately fake-secret-shaped values that must never appear in any
# report/CLI output -- if one of these literal-looking patterns shows up,
# something started fabricating or leaking credential-shaped content.
_FAKE_SECRET_PATTERNS = (
    re.compile(r"[1-9A-HJ-NP-Za-km-z]{87,88}"),  # base58 64-byte keypair length
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def test_executor_readiness_cli_never_dispatches_and_has_no_secret_shaped_output() -> None:
    result = runner.invoke(app, ["executor", "readiness"])
    assert result.exit_code == 0, result.output
    for pattern in _FAKE_SECRET_PATTERNS:
        assert not pattern.search(result.output), (
            f"fake-secret-shaped value matched {pattern.pattern!r} in CLI output"
        )
    assert '"LIVE_CANARY_PASSED": false' in result.output
    assert '"LIVE_ARMED": false' in result.output


def test_guarded_signer_seam_raises_when_reached() -> None:
    guard = DispatchGuard(signer=RaisingSigner())
    try:
        _ = guard.signer.public_key
        raised = False
    except SignerNeverCalledError:
        raised = True
    assert raised is True


def test_guarded_submission_seam_raises_when_reached() -> None:
    guard = DispatchGuard(signer=RaisingSigner())
    try:
        guard.submit("would-be-a-real-transaction")
        raised = False
    except DispatchNeverCalledError:
        raised = True
    assert raised is True


def test_raising_submission_is_the_guards_own_default() -> None:
    guard = DispatchGuard(signer=RaisingSigner())
    assert guard.submit is raising_submission
