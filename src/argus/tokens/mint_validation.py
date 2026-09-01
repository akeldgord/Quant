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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

ALGORITHM_VERSION: Final[str] = "token_mint_validation_v2"
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

# Token-2022's extensible account format (see the SPL Token-2022 program):
# any account WITHOUT extensions serializes as exactly the base struct size
# (82 bytes for a Mint, 165 for a Token Account -- identical to the legacy
# SPL Token program). An account WITH extensions is padded with zero bytes
# up to 165 (the base-Account size, chosen specifically so a Mint-with-
# extensions can never collide byte-for-byte with a bare legacy Account),
# then a single ``AccountType`` discriminator byte, then TLV-encoded
# extension data. This means the minimum possible length for ANY
# Token-2022 account carrying extensions is 166 bytes, and a length of
# exactly 165 can therefore never be a valid Mint-with-extensions layout
# -- it is either a bare legacy/Token-2022 TokenAccount (no extensions) or
# malformed. Discriminating on this fixed byte (never on "length >= 82"
# alone, the pre-remediation defect) is what lets a genuine 165-byte
# legacy token-account payload be rejected even when its own incidental
# bytes 44/45 happen to resemble a plausible decimals/is_initialized pair.
_ACCOUNT_TYPE_OFFSET: Final[int] = 165
_ACCOUNT_TYPE_MINT: Final[int] = 1
_ACCOUNT_TYPE_ACCOUNT: Final[int] = 2

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
    chain_time: datetime | None = None
    commitment: str | None = None


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


def _classify_mint_account_layout(decoded: bytes, *, owner: str) -> str | None:
    """Returns ``None`` when ``decoded`` is a genuine SPL Token or
    Token-2022 Mint account layout (safe to read the base struct's
    ``decimals``/``is_initialized`` bytes), or a human-readable rejection
    reason otherwise.

    P2-R1 fix: the pre-remediation check only asked "is this at least 82
    bytes," which a 165-byte legacy SPL Token *Account* (or a 355-byte
    multisig account, or any other incidentally-long payload) satisfies
    just as well as a genuine Mint -- silently promoting whatever bytes
    happened to land at offsets 44/45 into a false decimals/is_initialized
    reading. This function instead requires EITHER the exact base Mint
    size (no Token-2022 extensions) OR a structurally valid Token-2022
    extended layout (own ``AccountType`` discriminator byte confirming
    ``Mint``, never ``Account`` or anything else) -- see the module-level
    comment on ``_ACCOUNT_TYPE_OFFSET`` for why length alone is never
    sufficient to tell these apart."""
    length = len(decoded)
    if length == _MINT_ACCOUNT_LAYOUT_LEN:
        return None
    if length <= _ACCOUNT_TYPE_OFFSET:
        return (
            f"account data length {length} is neither the base SPL Token Mint layout "
            f"({_MINT_ACCOUNT_LAYOUT_LEN} bytes) nor long enough to carry a Token-2022 "
            f"extended-account discriminator (> {_ACCOUNT_TYPE_OFFSET} bytes) -- not a "
            "recognized Mint account shape (this length range includes, but is not "
            "limited to, a bare legacy SPL Token Account's own 165-byte size, which is "
            "never a valid Mint)"
        )
    if owner != SPL_TOKEN_2022_PROGRAM_ID:
        return (
            f"account data length {length} exceeds the base SPL Token Mint layout "
            f"({_MINT_ACCOUNT_LAYOUT_LEN} bytes), which is only ever valid for a "
            f"Token-2022 extended account, but owner is {owner!r} -- the legacy SPL "
            f"Token program's own Mint accounts are always exactly "
            f"{_MINT_ACCOUNT_LAYOUT_LEN} bytes with no extensions"
        )
    account_type = decoded[_ACCOUNT_TYPE_OFFSET]
    if account_type != _ACCOUNT_TYPE_MINT:
        kind = "Account" if account_type == _ACCOUNT_TYPE_ACCOUNT else f"type {account_type}"
        return (
            f"Token-2022 extended-account discriminator byte at offset "
            f"{_ACCOUNT_TYPE_OFFSET} is {account_type} ({kind}), not "
            f"{_ACCOUNT_TYPE_MINT} (Mint) -- this is a different Token-2022 account "
            "kind, not a Mint"
        )
    return None


def validate_from_account_info(
    raw: dict[str, Any] | None,
    *,
    mint: str,
    evidence_reference: str,
    commitment: str | None = None,
) -> MintValidationResult:
    """Validate against a genuine Solana ``getAccountInfo`` response
    shape: ``{"value": {"owner": ..., "data": [b64, "base64"], ...} |
    None}`` (the ``result`` envelope already unwrapped by the caller, same
    convention ``argus.providers.helius`` uses elsewhere). ``raw = None``
    or a response whose ``value`` is ``None`` means the provider itself
    reported the account does not exist on-chain -- a real, evidence-
    backed ``INVALID``, not an ``UNAVAILABLE``. ``commitment`` is the
    caller-supplied commitment level the live RPC call itself was made
    at (a live account snapshot carries no historical chain time of its
    own, so it is the only provenance field this evidence path can
    honestly persist -- P2-R8)."""
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
    layout_error = _classify_mint_account_layout(decoded, owner=owner)
    if layout_error is not None:
        return MintValidationResult(
            STATUS_INVALID, SOURCE_ACCOUNT_INFO, layout_error, None, owner, evidence_reference
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
        STATUS_VALID,
        SOURCE_ACCOUNT_INFO,
        None,
        decimals,
        owner,
        evidence_reference,
        chain_time=None,
        commitment=commitment,
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

    # P2-R1/R8 (item 8's "failed/unsupported evidence... must return a
    # non-VALID result"): a failed on-chain transaction's own balance
    # entries do not reliably reflect genuine post-execution state, so
    # this evidence class is never usable for validation, regardless of
    # what its preTokenBalances/postTokenBalances otherwise contain.
    if meta.get("err") is not None:
        return MintValidationResult(
            STATUS_UNAVAILABLE,
            SOURCE_TOKEN_BALANCE_EVIDENCE,
            "the cited transaction failed on-chain (meta.err is set) -- its own "
            "token-balance entries are not usable evidence for mint validation",
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

    # P2-R1 (item 8): evaluate EVERY matching entry, not merely the
    # first -- a genuine multi-account transaction can carry more than
    # one balance entry for the same mint (e.g. the bonding-curve
    # reserve account and the buyer's own account in the same pump.fun
    # buy instruction), and conflicting decimals/owner-program across
    # them means the evidence itself is internally inconsistent and
    # must never be silently resolved by picking whichever entry
    # happened to come first.
    decimals_seen: set[int] = set()
    owner_programs_seen: set[str] = set()
    for entry in entries:
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
        if (
            not isinstance(decimals, int)
            or isinstance(decimals, bool)
            or not (0 <= decimals <= 255)
        ):
            return MintValidationResult(
                STATUS_UNAVAILABLE,
                SOURCE_TOKEN_BALANCE_EVIDENCE,
                "malformed transaction evidence: missing/invalid uiTokenAmount.decimals",
                None,
                owner_program,
                evidence_reference,
            )
        decimals_seen.add(decimals)
        owner_programs_seen.add(owner_program)

    if len(decimals_seen) > 1:
        return MintValidationResult(
            STATUS_UNAVAILABLE,
            SOURCE_TOKEN_BALANCE_EVIDENCE,
            f"conflicting decimals across this transaction's own token-balance entries "
            f"for this mint: {sorted(decimals_seen)!r} -- internally inconsistent evidence",
            None,
            None,
            evidence_reference,
        )
    if len(owner_programs_seen) > 1:
        return MintValidationResult(
            STATUS_UNAVAILABLE,
            SOURCE_TOKEN_BALANCE_EVIDENCE,
            "conflicting owner program across this transaction's own token-balance "
            f"entries for this mint: {sorted(owner_programs_seen)!r} -- internally "
            "inconsistent evidence",
            None,
            None,
            evidence_reference,
        )

    decimals = decimals_seen.pop()
    owner_program = owner_programs_seen.pop()

    # P2-R8: persist chain time whenever the committed transaction
    # evidence carries it (blockTime), rather than always None.
    # ``commitment`` genuinely has no analogue in a getTransaction
    # response (that concept lives in getSignatureStatuses), so it stays
    # honestly None for this evidence path rather than being fabricated.
    block_time_raw = raw_transaction.get("blockTime")
    chain_time: datetime | None = None
    if block_time_raw is not None:
        if (
            isinstance(block_time_raw, bool)
            or not isinstance(block_time_raw, int)
            or block_time_raw < 0
        ):
            return MintValidationResult(
                STATUS_UNAVAILABLE,
                SOURCE_TOKEN_BALANCE_EVIDENCE,
                f"malformed transaction evidence: 'blockTime' {block_time_raw!r} is not "
                "a non-negative integer",
                None,
                owner_program,
                evidence_reference,
            )
        try:
            chain_time = datetime.fromtimestamp(block_time_raw, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return MintValidationResult(
                STATUS_UNAVAILABLE,
                SOURCE_TOKEN_BALANCE_EVIDENCE,
                f"malformed transaction evidence: 'blockTime' {block_time_raw!r} cannot "
                "be represented as a UTC timestamp",
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
        chain_time=chain_time,
        commitment=None,
    )
