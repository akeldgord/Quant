"""argus.executor.live_signing — MASTER_SPEC.md section 70 (LIVE
EXECUTION SECURITY MODEL) and section 71 (OS-LEVEL KEY ISOLATION), FSR-01
(``argus-final-spec-recovery-001``).

The ONE module in this codebase that may ever load real Solana signing
material, and only at runtime, inside the executor process, from an
external operator-controlled file path named by an environment variable
(:data:`ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR`) -- never a literal in
code, config, or this coding session's own conversation. Nothing in this
module logs, prints, persists, or returns the raw key bytes; only
:class:`FileKeypairSigner`'s ``public_key`` (already public information)
and its signatures ever leave the loaded ``solders.keypair.Keypair``.

Implements the same :class:`argus.executor.signing.Signer` Protocol as
``FakeSigner``/``RaisingSigner`` -- ``DispatchGuard`` (``dispatch.py``)
cannot tell the difference at the type level, which is exactly the point:
every non-executor code path is proven (by
``tests/unit/test_fsr01_live_signer_isolation_boundary.py``, mirroring
``test_phase6_p6_02_signer_isolation_boundary.py``'s own AST-based
mechanism) to never import this module at all, so it structurally cannot
ever construct a real signer regardless of what ``Signer`` looks like.

Fails closed on every problem (missing env var, missing/unreadable file,
malformed JSON, wrong shape, wrong byte length) -- never proceeds with a
degraded/partial key, matching ``argus.providers.credentials``'s
``LOCAL CREDENTIAL REQUIRED`` fail-closed convention for external secrets.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from solders.keypair import Keypair

ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR = "ARGUS_EXECUTOR_SIGNER_KEY_PATH"

_EXPECTED_KEYPAIR_BYTE_LENGTH = 64


class SignerKeyLoadError(RuntimeError):
    """Raised instead of silently proceeding without (or with malformed)
    real signing material. Callers must surface this as a fail-closed
    startup failure, never catch-and-substitute a fake/no-op signer while
    claiming live-capable status."""


class TransactionSigningError(RuntimeError):
    """Raised instead of signing a malformed transaction or one this
    keypair is not a required signer for."""


def _fail_closed(reason: str) -> SignerKeyLoadError:
    return SignerKeyLoadError(
        f"EXECUTOR SIGNING KEY REQUIRED: {reason}. Set "
        f"{ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR} to a local, operator-controlled "
        "keypair file path (solana-keygen JSON format: a 64-byte array). This value "
        "is never committed to this repository and this coding session never reads, "
        "prints, or logs its contents."
    )


class FileKeypairSigner:
    """Production-capable :class:`argus.executor.signing.Signer` --
    loads a real Solana ed25519 keypair from an external JSON file (the
    standard ``solana-keygen``/CLI wallet format: a 64-element byte array,
    seed followed by public key) and signs with it via ``solders`` (the
    real, widely-used Solana Python SDK -- deliberately not a hand-rolled
    byte-level signer/transaction implementation).

    The raw key bytes never leave the wrapped ``Keypair`` object: this
    class exposes only ``public_key`` (inherently public) and
    ``sign_transaction`` (returns signed transaction bytes, never the key
    itself)."""

    def __init__(self, keypair: Keypair) -> None:
        self._keypair = keypair

    @classmethod
    def from_path(cls, path: Path) -> FileKeypairSigner:
        """Read-only over ``path`` -- never writes it. Fails closed on
        every problem: missing file, unreadable file, malformed JSON,
        wrong shape, or wrong byte length."""
        if not path.exists():
            raise _fail_closed(f"key file not found at {path}")
        try:
            raw = path.read_text()
        except OSError as exc:
            raise _fail_closed(f"key file at {path} unreadable: {exc}") from exc
        try:
            keypair = Keypair.from_json(raw)
        except Exception as exc:  # noqa: BLE001 - any parse/format failure fails closed
            raise _fail_closed(
                f"key file at {path} is not a valid {_EXPECTED_KEYPAIR_BYTE_LENGTH}-byte "
                f"solana-keygen JSON keypair array: {type(exc).__name__}"
            ) from exc
        return cls(keypair)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> FileKeypairSigner:
        """Fail-closed resolution of the operator-controlled key path
        from the environment (never a hardcoded/default path) -- mirrors
        ``argus.providers.credentials.require_env_credential``'s
        no-fallback discipline."""
        raw_path = env.get(ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR)
        if not raw_path:
            raise _fail_closed(
                f"{ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR} is not set in the executor "
                "process's own environment"
            )
        return cls.from_path(Path(raw_path))

    @property
    def public_key(self) -> str:
        return str(self._keypair.pubkey())

    def sign_transaction(self, unsigned_transaction_bytes: bytes) -> bytes:
        """Parses ``unsigned_transaction_bytes`` as a Solana
        ``VersionedTransaction``, re-signs its message with the loaded
        keypair via ``solders``'s own verified constructor (never a
        hand-rolled signature-splice), and returns the fully signed wire
        bytes. Raises if this keypair is not among the transaction's
        required signers -- fails closed rather than submit a
        transaction attested for a different signer."""
        from solders.transaction import VersionedTransaction

        try:
            parsed = VersionedTransaction.from_bytes(unsigned_transaction_bytes)
        except Exception as exc:  # noqa: BLE001 - malformed input fails closed
            raise TransactionSigningError(
                f"sign_transaction: not a valid Solana VersionedTransaction: {type(exc).__name__}"
            ) from exc
        try:
            signed = VersionedTransaction(parsed.message, [self._keypair])
        except Exception as exc:  # noqa: BLE001 - wrong/extra required signer fails closed
            raise TransactionSigningError(
                f"sign_transaction: this keypair cannot sign the given transaction: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        return bytes(signed)
