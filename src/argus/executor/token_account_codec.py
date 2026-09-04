"""argus.executor.token_account_codec — static SPL Token account layout
decoding, R2-01 (``argus-final-spec-recovery-002``).

A real (not fabricated) way to recover which mint/owner/amount a raw
on-chain account's bytes represent, using the SPL Token program's fixed,
publicly documented 165-byte account layout (mint: 32 bytes @ offset 0,
owner: 32 bytes @ offset 32, amount: little-endian u64 @ offset 64).
This is pure, offline byte decoding -- it needs no network access and is
the same layout every Solana explorer/wallet/SDK decodes against.

Used by ``argus.executor.tx_deserialize`` to reconstruct a real
:class:`~argus.executor.attestation.UnsignedTransactionShape` from actual
pre/post simulation account snapshots, rather than trusting a provider's
own quote/response as a substitute for what the transaction bytes
actually do.
"""

from __future__ import annotations

from dataclasses import dataclass

from solders.pubkey import Pubkey

# The canonical SPL Token program id -- an account is only a token
# account if it is OWNED (at the account level, i.e. the program that
# controls it) by this program. Never inferred from data shape alone.
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

# Wrapped-SOL's mint address -- native SOL, once wrapped, behaves like
# any other SPL token account. Needed so fee computation can net out a
# wrap/unwrap leg's own lamport movement from the executor wallet's
# native balance delta (see ``tx_deserialize.py``).
NATIVE_SOL_MINT = "So11111111111111111111111111111111111111112"

_TOKEN_ACCOUNT_LEN = 165
_MINT_OFFSET = 0
_OWNER_OFFSET = 32
_AMOUNT_OFFSET = 64
_AMOUNT_LEN = 8


class TokenAccountDecodeError(RuntimeError):
    """Raised instead of silently guessing when raw bytes are not a
    well-formed 165-byte SPL Token account."""


@dataclass(frozen=True)
class DecodedTokenAccount:
    mint: str
    owner: str
    amount_raw: int


def decode_token_account(data: bytes) -> DecodedTokenAccount:
    """Decodes ``data`` as an SPL Token account. Fails closed
    (:class:`TokenAccountDecodeError`) on anything shorter than the fixed
    165-byte layout rather than reading past the end or guessing."""
    if len(data) < _TOKEN_ACCOUNT_LEN:
        raise TokenAccountDecodeError(
            f"expected at least {_TOKEN_ACCOUNT_LEN} bytes for an SPL Token account, "
            f"got {len(data)}"
        )
    mint = str(Pubkey(bytes(data[_MINT_OFFSET : _MINT_OFFSET + 32])))
    owner = str(Pubkey(bytes(data[_OWNER_OFFSET : _OWNER_OFFSET + 32])))
    amount = int.from_bytes(
        data[_AMOUNT_OFFSET : _AMOUNT_OFFSET + _AMOUNT_LEN], byteorder="little", signed=False
    )
    return DecodedTokenAccount(mint=mint, owner=owner, amount_raw=amount)
