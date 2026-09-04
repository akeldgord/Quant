"""FSR-01 (``argus-final-spec-recovery-001``): production-capable local
signer adapter -- fail-closed key loading and real (test-only, ephemeral,
never-committed) keypair sign/verify round trip.

Every keypair used in this file is generated fresh in-process by
``solders.keypair.Keypair()`` (a cryptographically random, unfunded,
never-persisted-to-disk-outside-``tmp_path`` test key) -- never a real
operator key, never a literal in this file, matching this recovery's own
prohibition on ever touching real signing material.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction

from argus.executor.live_signing import (
    ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR,
    FileKeypairSigner,
    SignerKeyLoadError,
    TransactionSigningError,
)


def _write_keypair(tmp_path: Path, keypair: Keypair) -> Path:
    path = tmp_path / "test-keypair.json"
    path.write_text(keypair.to_json())
    return path


def test_missing_env_var_fails_closed() -> None:
    with pytest.raises(SignerKeyLoadError, match="not set"):
        FileKeypairSigner.from_env({})


def test_missing_key_file_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(SignerKeyLoadError, match="not found"):
        FileKeypairSigner.from_env({ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR: str(missing)})


def test_malformed_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not valid json{{{")
    with pytest.raises(SignerKeyLoadError, match="not a valid"):
        FileKeypairSigner.from_path(path)


def test_wrong_shape_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "wrong-shape.json"
    path.write_text('{"not": "a keypair array"}')
    with pytest.raises(SignerKeyLoadError, match="not a valid"):
        FileKeypairSigner.from_path(path)


def test_wrong_length_byte_array_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "wrong-length.json"
    path.write_text("[1, 2, 3]")
    with pytest.raises(SignerKeyLoadError, match="not a valid"):
        FileKeypairSigner.from_path(path)


def test_valid_ephemeral_test_keypair_loads_and_exposes_only_public_key(tmp_path: Path) -> None:
    keypair = Keypair()
    path = _write_keypair(tmp_path, keypair)
    signer = FileKeypairSigner.from_env({ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR: str(path)})
    assert signer.public_key == str(keypair.pubkey())


def test_sign_transaction_produces_a_verifiable_signature(tmp_path: Path) -> None:
    keypair = Keypair()
    recipient = Keypair()
    path = _write_keypair(tmp_path, keypair)
    signer = FileKeypairSigner.from_env({ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR: str(path)})

    ix = transfer(
        TransferParams(from_pubkey=keypair.pubkey(), to_pubkey=recipient.pubkey(), lamports=1_000)
    )
    from solders.hash import Hash

    message = MessageV0.try_compile(keypair.pubkey(), [ix], [], Hash.default())
    unsigned = VersionedTransaction.populate(message, [Signature.default()])

    signed_bytes = signer.sign_transaction(bytes(unsigned))
    signed = VersionedTransaction.from_bytes(signed_bytes)
    # verify_and_hash_message raises if the signature doesn't check out --
    # a clean return proves this is a real, cryptographically valid
    # signature over the exact message bytes, not a stub/echo.
    signed.verify_and_hash_message()


def test_sign_transaction_rejects_a_transaction_this_key_cannot_sign(tmp_path: Path) -> None:
    """Fail closed: a transaction whose fee-payer is a DIFFERENT pubkey
    must never be silently signed as if it belonged to this key."""
    keypair = Keypair()
    other = Keypair()
    recipient = Keypair()
    path = _write_keypair(tmp_path, keypair)
    signer = FileKeypairSigner.from_env({ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR: str(path)})

    from solders.hash import Hash

    ix = transfer(
        TransferParams(from_pubkey=other.pubkey(), to_pubkey=recipient.pubkey(), lamports=1_000)
    )
    message = MessageV0.try_compile(other.pubkey(), [ix], [], Hash.default())
    unsigned = VersionedTransaction.populate(message, [Signature.default()])

    with pytest.raises(TransactionSigningError):
        signer.sign_transaction(bytes(unsigned))


def test_sign_transaction_rejects_malformed_bytes(tmp_path: Path) -> None:
    keypair = Keypair()
    path = _write_keypair(tmp_path, keypair)
    signer = FileKeypairSigner.from_env({ARGUS_EXECUTOR_SIGNER_KEY_PATH_ENV_VAR: str(path)})
    with pytest.raises(TransactionSigningError):
        signer.sign_transaction(b"not a real transaction")
