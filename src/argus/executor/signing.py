"""argus.executor.signing — MASTER_SPEC.md section 70 (LIVE EXECUTION
SECURITY MODEL) and section 71 (OS-LEVEL KEY ISOLATION), Phase 6
(``argus-phase-6-001``).

Defines the ONE interface boundary through which signing may ever be
requested (:class:`Signer`). MASTER_SPEC.md section 70's absolute
prohibition on requesting/reading/printing/persisting a real seed
phrase or private key applies to this coding session as much as to any
runtime code it writes -- so no real on-disk-keypair implementation
exists anywhere in this module or this package; only the interface plus
two inert test doubles:

- :class:`FakeSigner` -- deterministic fake bytes, never touches a real
  key. Used by tests that need signing to actually "succeed."
- :class:`RaisingSigner` -- always raises. Used by P6-16's no-dispatch
  tests to prove a code path (report/readiness/dry-run) never calls a
  signer at all.

No module outside this package ever imports this module --
``argus.copyability``, ``argus.scoring``, and every non-executor CLI
command have no signer/key dependency at all, proven by
``tests/unit/test_phase6_p6_02_signer_isolation_boundary.py``.
"""

from __future__ import annotations

from typing import Protocol


class Signer(Protocol):
    @property
    def public_key(self) -> str: ...

    def sign_transaction(self, unsigned_transaction_bytes: bytes) -> bytes: ...


class FakeSigner:
    """Inert test double -- returns deterministic fake bytes derived
    from the input, never touches a real key."""

    def __init__(self, *, public_key: str = "FAKE_SIGNER_PUBLIC_KEY") -> None:
        self._public_key = public_key

    @property
    def public_key(self) -> str:
        return self._public_key

    def sign_transaction(self, unsigned_transaction_bytes: bytes) -> bytes:
        return b"FAKE_SIGNATURE:" + unsigned_transaction_bytes


class SignerNeverCalledError(RuntimeError):
    """Raised by :class:`RaisingSigner` -- proves a code path under test
    never dispatches to a signer."""


class RaisingSigner:
    """Sentinel signer: every method raises :class:`SignerNeverCalledError`.
    Used by P6-16's no-dispatch tests."""

    @property
    def public_key(self) -> str:
        raise SignerNeverCalledError("public_key accessed on RaisingSigner")

    def sign_transaction(self, unsigned_transaction_bytes: bytes) -> bytes:
        raise SignerNeverCalledError("sign_transaction called on RaisingSigner")
