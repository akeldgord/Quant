"""Deterministic on-chain Solana token-mint validation (MASTER_SPEC.md
Phase 2 build item 14; required-implementation item 2).

Address shape alone (a plausible-looking base58 string) is never proof a
mint exists on-chain. This module supports two independent evidence
paths, both requiring genuine committed chain evidence before a mint may
ever be reported ``VALID``:

1. :func:`validate_from_account_info` -- the real production path, over a
   genuine Solana ``getAccountInfo`` response. Decodes the fixed 82-byte
   SPL Token ``Mint`` account layout locally (mint_authority_option(4) +
   mint_authority(32) + supply(8) + decimals(1) + is_initialized(1) +
   freeze_authority_option(4) + freeze_authority(32) = 82 bytes -- the
   same well-known layout every SPL Token client uses; Token-2022 mints
   share this identical prefix, with TLV extension bytes appended after
   it). Requires the account's ``owner`` to be the SPL Token or
   Token-2022 program, the data to decode to at least 82 bytes, and
   ``is_initialized`` to be set.
2. :func:`validate_from_token_balance_evidence` -- the free-first path
   this sandbox actually has: a genuine, already-committed
   ``getTransaction`` response whose own ``meta.preTokenBalances``/
   ``postTokenBalances`` include an entry for the target mint. The
   Solana validator that produced the block would not have populated a
   token-balance entry for a non-existent or malformed mint, so a
   present, owner-program-tagged entry is itself real on-chain evidence
   -- distinct from (weaker than) a direct account-info fetch, and
   always reported with ``validation_source =
   "committed_transaction_token_balance_evidence"`` so it is never
   confused with a live ``getAccountInfo`` validation.

Malformed, missing, conflicting, wrong-owner, or non-mint evidence
produces :data:`STATUS_INVALID`. A provider-capacity or environmental
miss (unreachable provider, malformed/contract-violating provider
response, or evidence that simply does not cover this mint) produces
:data:`STATUS_UNAVAILABLE` -- explicitly never silently promoted to
``VALID``. Only genuine, decoded, initialized-mint evidence produces
:data:`STATUS_VALID`.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import hashlib
from pathlib import Path
from typing import Any, Final

ALGORITHM_VERSION: Final[str] = "token_mint_validation_v1"
BUILD_HASH: Final[str] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

STATUS_VALID: Final[str] = "VALID"
STATUS_INVALID: Final[str] = "INVALID"
STATUS_UNAVAILABLE: Final[str] = "UNAVAILABLE"

SPL_TOKEN_PROGRAM_ID: Final[str] = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
SPL_TOKEN_2022_PROGRAM_ID: Final[str] = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
_MINT_OWNER_PROGRAMS: Final[frozenset[str]] = frozenset(
    {SPL_TOKEN_PROGRAM_ID, SPL_TOKEN_2022_PROGRAM_ID}
)

_MINT_ACCOUNT_LAYOUT_LEN: Final[int] = 82
_DECIMALS_OFFSET: Final[int] = 44
_IS_INITIALIZED_OFFSET: Final[int] = 45

_BASE58_ALPHABET: Final[str] = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_MIN_PUBKEY_B58_LEN: Final[int] = 32
_MAX_PUBKEY_B58_LEN: Final[int] = 44

SOURCE_ACCOUNT_INFO: Final[str] = "helius_get_account_info"
SOURCE_TOKEN_BALANCE_EVIDENCE: Final[str] = "committed_transaction_token_balance_evidence"


@dataclasses.dataclass(frozen=True, slots=True)
class MintValidationResult:
    """The outcome of one mint-validation attempt -- everything
    ``argus.domain.token_mint_validations.TokenMintValidation`` needs to
    persist an honest, evidence-cited row."""

    status: str
    validation_source: str
    reason: str | None
    decimals: int | None
    owner_program: str | None
    evidence_reference: str


def mint_address_shape_error(mint: str) -> str | None:
    """A cheap, evidence-free precondition check only -- passing this
    NEVER by itself makes a mint valid, it only screens out addresses too
    malformed to be worth fetching evidence for at all."""
    if not isinstance(mint, str) or not mint:
        return "mint address is empty or not a string"
    if not (_MIN_PUBKEY_B58_LEN <= len(mint) <= _MAX_PUBKEY_B58_LEN):
        return f"mint address length {len(mint)} is outside the valid pubkey range"
    if any(ch not in _BASE58_ALPHABET for ch in mint):
        return "mint address contains characters outside the base58 alphabet"
    return None


def _decode_mint_account_data(data_field: Any) -> bytes | None:
    """``getAccountInfo``'s ``value.data`` is ``[base64_str, "base64"]``
    for the encoding this validator requires. Returns ``None`` (never
    raises) for anything that doesn't match that exact, unambiguous
    shape."""
    if (
        not isinstance(data_field, list)
        or len(data_field) != 2
        or data_field[1] != "base64"
        or not isinstance(data_field[0], str)
    ):
        return None
    try:
        return base64.b64decode(data_field[0], validate=True)
    except (binascii.Error, ValueError):
        return None


def validate_from_account_info(
    raw: dict[str, Any] | None, *, mint: str, evidence_reference: str
) -> MintValidationResult:
    """Validate against a genuine Solana ``getAccountInfo`` response
    shape: ``{"value": {"owner": ..., "data": [b64, "base64"], ...} |
    None}`` (the ``result`` envelope already unwrapped by the caller, same
    convention ``argus.providers.helius`` uses elsewhere). ``raw = None``
    or a response whose ``value`` is ``None`` means the provider itself
    reported the account does not exist on-chain -- a real, evidence-
    backed ``INVALID``, not an ``UNAVAILABLE``."""
    shape_error = mint_address_shape_error(mint)
    if shape_error is not None:
        return MintValidationResult(
            STATUS_INVALID, SOURCE_ACCOUNT_INFO, shape_error, None, None, evidence_reference
        )

    if raw is None or not isinstance(raw, dict):
        return MintValidationResult(
            STATUS_UNAVAILABLE,
            SOURCE_ACCOUNT_INFO,
            "no provider response available",
            None,
            None,
            evidence_reference,
        )
    if "value" not in raw:
        return MintValidationResult(
            STATUS_UNAVAILABLE,
            SOURCE_ACCOUNT_INFO,
            "malformed provider response: missing 'value'",
            None,
            None,
            evidence_reference,
        )

    value = raw["value"]
    if value is None:
        return MintValidationResult(
            STATUS_INVALID,
            SOURCE_ACCOUNT_INFO,
            "account does not exist on-chain",
            None,
            None,
            evidence_reference,
        )
    if not isinstance(value, dict):
        return MintValidationResult(
            STATUS_UNAVAILABLE,
            SOURCE_ACCOUNT_INFO,
            "malformed provider response: 'value' is not an object",
            None,
            None,
            evidence_reference,
        )

    owner = value.get("owner")
    if not isinstance(owner, str) or owner not in _MINT_OWNER_PROGRAMS:
        return MintValidationResult(
            STATUS_INVALID,
            SOURCE_ACCOUNT_INFO,
            f"account owner {owner!r} is not the SPL Token or Token-2022 program",
            None,
            owner if isinstance(owner, str) else None,
            evidence_reference,
        )

    decoded = _decode_mint_account_data(value.get("data"))
    if decoded is None:
        return MintValidationResult(
            STATUS_UNAVAILABLE,
            SOURCE_ACCOUNT_INFO,
            "malformed provider response: account data is not valid base64",
            None,
            owner,
            evidence_reference,
        )
    if len(decoded) < _MINT_ACCOUNT_LAYOUT_LEN:
        return MintValidationResult(
            STATUS_INVALID,
            SOURCE_ACCOUNT_INFO,
            f"account data length {len(decoded)} is shorter than the SPL Token Mint "
            f"layout ({_MINT_ACCOUNT_LAYOUT_LEN} bytes) -- not a mint account",
            None,
            owner,
            evidence_reference,
        )

    is_initialized = decoded[_IS_INITIALIZED_OFFSET]
    if is_initialized != 1:
        return MintValidationResult(
            STATUS_INVALID,
            SOURCE_ACCOUNT_INFO,
            "mint account is not initialized (is_initialized byte != 1)",
            None,
            owner,
            evidence_reference,
        )

    decimals = decoded[_DECIMALS_OFFSET]
    return MintValidationResult(
        STATUS_VALID, SOURCE_ACCOUNT_INFO, None, decimals, owner, evidence_reference
    )


def validate_from_token_balance_evidence(
    raw_transaction: dict[str, Any], *, mint: str, evidence_reference: str
) -> MintValidationResult:
    """Validate a mint using a genuine, already-committed
    ``getTransaction`` response's own ``meta.preTokenBalances``/
    ``postTokenBalances`` -- the free-first evidence this sandbox
    actually has (no live ``getAccountInfo`` access; see this module's
    docstring). Weaker than :func:`validate_from_account_info` (it proves
    the mint had at least one real token-balance entry the validator
    itself produced, not a direct account fetch), so always reported
    under a distinct ``validation_source`` that can never be confused
    with a live account-info validation."""
    shape_error = mint_address_shape_error(mint)
    if shape_error is not None:
        return MintValidationResult(
            STATUS_INVALID,
            SOURCE_TOKEN_BALANCE_EVIDENCE,
            shape_error,
            None,
            None,
            evidence_reference,
        )

    meta = raw_transaction.get("meta") if isinstance(raw_transaction, dict) else None
    if not isinstance(meta, dict):
        return MintValidationResult(
            STATUS_UNAVAILABLE,
            SOURCE_TOKEN_BALANCE_EVIDENCE,
            "malformed transaction evidence: missing 'meta'",
            None,
            None,
            evidence_reference,
        )

    entries: list[dict[str, Any]] = []
    for key in ("postTokenBalances", "preTokenBalances"):
        for entry in meta.get(key) or []:
            if isinstance(entry, dict) and entry.get("mint") == mint:
                entries.append(entry)

    if not entries:
        return MintValidationResult(
            STATUS_UNAVAILABLE,
            SOURCE_TOKEN_BALANCE_EVIDENCE,
            "this transaction's token-balance evidence does not reference this mint",
            None,
            None,
            evidence_reference,
        )

    entry = entries[0]
    owner_program = entry.get("programId")
    if not isinstance(owner_program, str) or owner_program not in _MINT_OWNER_PROGRAMS:
        return MintValidationResult(
            STATUS_UNAVAILABLE,
            SOURCE_TOKEN_BALANCE_EVIDENCE,
            "token-balance evidence does not record a recognized owner program "
            "for this mint (cannot confirm from this evidence alone)",
            None,
            owner_program if isinstance(owner_program, str) else None,
            evidence_reference,
        )

    ui_amount = entry.get("uiTokenAmount")
    decimals = ui_amount.get("decimals") if isinstance(ui_amount, dict) else None
    if not isinstance(decimals, int) or isinstance(decimals, bool):
        return MintValidationResult(
            STATUS_UNAVAILABLE,
            SOURCE_TOKEN_BALANCE_EVIDENCE,
            "malformed transaction evidence: missing/invalid uiTokenAmount.decimals",
            None,
            owner_program,
            evidence_reference,
        )

    return MintValidationResult(
        STATUS_VALID,
        SOURCE_TOKEN_BALANCE_EVIDENCE,
        None,
        decimals,
        owner_program,
        evidence_reference,
    )
