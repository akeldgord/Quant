"""Deterministic, generic balance-delta transaction parser.

MASTER_SPEC.md section 21 (GENERIC TRANSACTION/SWAP PARSER): start with
deterministic wallet-owned pre/post balance-delta reconstruction; do not
build a separate parser for every DEX. Given a raw Solana
``getTransaction`` response (as returned by any RPC provider -- this module
never depends on a provider-specific object, only the standard Solana JSON
RPC transaction shape) and the wallet address being tracked, this module:

1. obtains and preserves raw transaction evidence (the caller stores it
   verbatim in ``chain_events.raw_payload`` -- this module only reads it);
2. identifies wallet-owned accounts (SOL via ``accountKeys`` index, tokens
   via each token-balance entry's ``owner`` field);
3. canonicalizes native SOL and wrapped SOL into a single logical asset;
4. calculates net native/token deltas for the tracked wallet;
5. accounts for the network fee (only charged to the fee payer, account
   index 0);
6. identifies meaningful asset inflow/outflow;
7. classifies deterministically into one of the seven canonical
   ``Classification`` values;
8. emits a confidence score and this module's ``PARSER_VERSION``.

Classification is a pure decision tree over signed, non-zero balance
deltas -- no DEX-program-ID special-casing. Two of the seven values
(``TOKEN_CREATE``, ``LP_ACTION``) rely on documented heuristics, not
instruction parsing, since a purely balance-delta parser cannot always
distinguish "created a new token account" or "added/removed liquidity"
from the raw account-level deltas alone; both are architecturally free to
be superseded by an instruction-aware parser in a later phase without
requiring any Phase 1 schema change (``parser_version`` exists exactly to
make different parser generations distinguishable in the ledger, per
CORE-002/CORE-003 -- re-parsing never rewrites raw evidence).

Any transaction that fails on-chain (``meta.err`` set), or whose deltas
don't fit a confident pattern, is classified ``UNKNOWN``: preserved for
research (MASTER_SPEC section 21) but never copy-eligible (see
``ParsedTransaction.is_copy_eligible``).

Phase 1 remediation round 5, finding #4 -- fail-closed v1 eligibility
semantics, since a purely balance-delta parser cannot *prove* a route is a
genuine fungible-asset trade, only observe a shape consistent with one:

- a failed transaction, or one whose deltas don't fit a confident single-
  asset-in/single-asset-out or pure-inflow/pure-outflow pattern, is
  ``UNKNOWN`` and never eligible;
- two or more *distinct* assets moving in the same direction with nothing
  offsetting them (e.g. a native-SOL rent refund alongside an unrelated
  token release in the same instruction) is genuinely ambiguous -- this is
  now its own ``UNKNOWN`` case, not silently collapsed into
  ``TRANSFER_IN``/``TRANSFER_OUT`` by picking the largest leg;
- ``LP_ACTION`` (two or more non-SOL assets moving together) and
  ``SWAP_COMPLEX`` (assets moving on both sides, more than one per side)
  both preserve real research evidence but are never copy-eligible in v1
  -- balance deltas alone cannot prove which leg is the "real" trade route
  through a multi-hop or liquidity action;
- a "clean" one-for-one ``SWAP_SIMPLE`` is still never automatically
  eligible if either leg is a decimals-zero (non-fungible/NFT-shaped)
  asset movement -- a one-for-one balance-delta shape looks identical for
  "bought a fungible token" and "bought an NFT", and only the latter is
  never a fungible copy-trade signal.

Only ``SWAP_SIMPLE`` with both legs having nonzero decimals, at or above
the confidence floor, is copy-eligible -- and, since v2 (Phase 1.5
remediation round 1, positive semantic proof gate), only when canonical
instruction-level evidence positively identifies the transaction as
having actually routed through a supported trade venue. Balance shape
alone (one asset given up, one received) is deliberately insufficient:
many genuine, non-trade DeFi actions -- a lending-market withdrawal/
redemption, a staking deposit, a vault claim -- produce exactly that
same one-in/one-out shape without being a swap at all. v1 treated any
such shape as a confident ``SWAP_SIMPLE`` regardless of *what
instruction actually executed*.

v2 (round 1) required only that *some* instruction in the transaction
invoke an allowlisted program -- but the same program that supports
swaps also executes non-trade instructions (e.g. Orca Whirlpool's
``DecreaseLiquidity``/``CollectFees``/``ClosePosition``, proven by this
project's own ``real_mainnet_orca_close_position_multi_account.json``
evidence), so "program appeared somewhere" was not proof a swap
happened. v3 (Phase 1.5 remediation round 2) closes that gap: a
positive match now binds the resolved program ID, the instruction's own
raw ``data`` bytes, and an exact versioned discriminator allowed for
*that same program*, all on one canonical top-level or inner
instruction object (see ``_SWAP_INSTRUCTION_REGISTRY``/
``_matched_swap_instruction()`` and ``ParsedTransaction.
is_copy_eligible``). Instruction ``data`` is base58 text in raw RPC
evidence; ``_decode_base58_strict()`` is a small local decoder (no new
dependency) that fails closed -- returns no bytes at all -- on anything
absent, non-string, oversized, outside the fixed Solana base58 alphabet,
or that does not round-trip back to the exact original text. Program
log lines are corroboration only and are never consulted: a different
invoked program can emit arbitrary log text, so eligibility rests
solely on the matched instruction's own program ID and decoded data.

This remains a narrow allowlist/proof gate, not a full per-program
instruction parser: an unmatched program or instruction never becomes
ineligible by name (there is no denylist), it simply lacks the positive
evidence required to promote a balance-shape-only guess into an
automatic copy signal, and correctly stays research-only
(``is_copy_eligible = False``) until a specific (program ID,
discriminator) pair is added to the registry with a citation to an
authentic committed swap fixture's exact instruction object -- never
from memory, documentation alone, a synthetic fixture, or a non-swap
fixture. A program may have zero accepted pairs until such evidence
exists.
"""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal

PARSER_VERSION: Final[str] = "generic_balance_delta_v3"

# Phase 1 remediation round 3, finding #5: a reproducible content hash of
# this exact algorithm's source, computed once at import time. Distinct
# from PARSER_VERSION (a human-assigned label above that can be forgotten
# to bump when this file changes) and from a git commit SHA (which
# changes on any commit anywhere in the repo, not just here, and does not
# reflect uncommitted local edits during development) -- this hash always
# changes exactly when, and only when, this file's bytes change, so a
# durable ``parse_attempts`` row stamped with it can always be checked
# against the exact code that produced it.
PARSER_BUILD_HASH: Final[str] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

NATIVE_SOL_ASSET: Final[str] = "SOL"
WRAPPED_SOL_MINT: Final[str] = "So11111111111111111111111111111111111111112"
NATIVE_SOL_DECIMALS: Final[int] = 9

Classification = Literal[
    "SWAP_SIMPLE",
    "SWAP_COMPLEX",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "TOKEN_CREATE",
    "LP_ACTION",
    "UNKNOWN",
]

# Classifications a copy-trading consumer may ever treat as an executable
# trade signal. Deliberately narrow: TRANSFER_IN/OUT/TOKEN_CREATE/LP_ACTION
# are not trades to mirror, and UNKNOWN is never eligible regardless of
# confidence (MASTER_SPEC section 21: "no automatic copy trade" for
# ambiguous transactions). Phase 1 remediation round 5, finding #4:
# SWAP_COMPLEX is deliberately excluded here too -- balance deltas alone
# cannot prove which leg of a multi-hop route is the "real" trade, only
# report the largest one as a heuristic; it stays a real, useful
# classification for research evidence, but is never copy-eligible in v1
# absent a separate, deterministic, fixture-demonstrated proof rule.
_COPY_ELIGIBLE_CLASSIFICATIONS: Final[frozenset[str]] = frozenset({"SWAP_SIMPLE"})
_MIN_COPY_ELIGIBLE_CONFIDENCE: Final[Decimal] = Decimal("0.500")

# Phase 1.5 remediation round 2 -- strict, bounded, local base58 decoding
# of raw Solana instruction `data` (base58 text in every raw RPC evidence
# shape this project has seen). No repository dependency already declares
# a base58 codec (checked: pyproject.toml/uv.lock), and this gate does not
# warrant pulling in a broad Solana SDK, so this is a small, self-contained
# decoder using the fixed Solana/Bitcoin base58 alphabet (no 0/O/I/l).
_BASE58_ALPHABET: Final[str] = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX: Final[dict[str, int]] = {ch: i for i, ch in enumerate(_BASE58_ALPHABET)}

# Conservative bound on *encoded* base58 text length. Real Solana
# instruction `data` is at most ~1232 bytes (the whole-transaction size
# limit), which base58-encodes to well under this; this bound exists to
# fail closed on a pathological/oversized value rather than to accept
# every theoretically valid Solana instruction.
_MAX_BASE58_DATA_CHARS: Final[int] = 4096


def _encode_base58(raw: bytes) -> str:
    """The canonical base58 encoding of ``raw`` -- used only internally by
    :func:`_decode_base58_strict` to verify a round trip, never called on
    untrusted input directly."""
    n_leading_zeros = len(raw) - len(raw.lstrip(b"\x00"))
    num = int.from_bytes(raw, "big")
    digits: list[str] = []
    while num > 0:
        num, rem = divmod(num, 58)
        digits.append(_BASE58_ALPHABET[rem])
    return ("1" * n_leading_zeros) + "".join(reversed(digits))


def _decode_base58_strict(data: Any) -> bytes | None:
    """Strict, bounded, fail-closed base58 decode of a Solana instruction
    ``data`` value. Returns ``None`` -- never raises -- for anything that
    is not an unambiguous, safely-sized, exactly-canonical encoding:

    - not a string (including ``None``, absent, or a non-string type);
    - empty, or longer than :data:`_MAX_BASE58_DATA_CHARS`;
    - containing any character outside the fixed Solana base58 alphabet;
    - one whose decoded bytes do not re-encode to the exact original text
      (the canonical-round-trip check: guards against a decoder defect
      silently accepting a malformed value rather than proving no such
      value is otherwise constructible under this correct, bijective
      leading-zero-to-leading-'1' mapping).

    Malformed input is never coerced (e.g. via ``str()``) into a match --
    only a genuine ``str`` is ever considered."""
    if not isinstance(data, str):
        return None
    if not data or len(data) > _MAX_BASE58_DATA_CHARS:
        return None
    if any(ch not in _BASE58_INDEX for ch in data):
        return None

    num = 0
    for ch in data:
        num = num * 58 + _BASE58_INDEX[ch]
    body = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    n_leading_ones = len(data) - len(data.lstrip("1"))
    decoded = (b"\x00" * n_leading_ones) + body

    if _encode_base58(decoded) != data:
        return None
    return decoded


@dataclasses.dataclass(frozen=True, slots=True)
class _SwapInstructionEvidence:
    """One accepted (program ID, instruction discriminator) pair in the
    positive semantic proof gate's registry -- see
    ``_SWAP_INSTRUCTION_REGISTRY`` for the full citation requirement."""

    program_id: str
    discriminator: bytes
    semantic_label: str
    citation_fixture: str
    citation_location: str


# Phase 1.5 remediation round 2 -- the positive semantic proof gate's
# program-AND-instruction-discriminator registry, replacing round 1's
# program-only allowlist (`_SUPPORTED_SWAP_PROGRAM_IDS`), which proved
# only that *some* instruction invoked an allowlisted program -- not that
# the invoked instruction was itself a trade. The same programs below also
# execute genuine non-trade instructions (proven by this project's own
# `real_mainnet_orca_close_position_multi_account.json`, whose Orca
# Whirlpool `DecreaseLiquidity`/`CollectFees`/`ClosePosition` instructions
# carry discriminators `a026d06f685b2c01`/`a498cf631eba13b6`/
# `7b86510031446262` -- all deliberately absent below), so a positive
# match now binds the resolved program ID to the SAME instruction
# object's own decoded `data` discriminator, not merely "this program
# appeared somewhere in the transaction."
#
# Every pair below is independently derived by decoding the cited
# fixture's own raw base58 `data` field for the named instruction
# location (never taken from program documentation, memory, a synthetic
# fixture, or a non-swap fixture) and cross-checked against that
# instruction's own program log text where present. A program may have
# zero accepted pairs -- and Flash/Titan/every other unlisted program
# correctly do -- until similar authentic evidence exists; this is a
# narrow allowlist, not a protocol parser, and never a denylist.
_SWAP_INSTRUCTION_REGISTRY: Final[tuple[_SwapInstructionEvidence, ...]] = (
    # Jupiter Aggregator V6 -- 8-byte Anchor discriminator for
    # `shared_accounts_route` (sha256("global:shared_accounts_route")[:8]),
    # decoded from the fixture's own instruction `data`; the fixture's own
    # captured logs corroborate with "Program log: Instruction:
    # SharedAccountsRoute".
    _SwapInstructionEvidence(
        program_id="JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
        discriminator=bytes.fromhex("c1209b3341d69c81"),
        semantic_label="shared_accounts_route",
        citation_fixture=(
            "tests/golden/fixtures/real/sources/"
            "91f3b3675779c6a4fb0a994ef0ff1e91b9e79283.source.json"
            " (real_mainnet_token_to_usdc_swap)"
        ),
        citation_location=(
            "top-level instruction index 2; signature "
            "rNMFZpBmbr6R8g4hStbC5qAictmWvGFQVTwQyXoCY6QDrcq9UV2QfHJ6oARNuS1VaUh3HVe799CDn44dWQReAye"
        ),
    ),
    # Raydium Liquidity Pool V4 -- a legacy (non-Anchor) 1-byte instruction
    # tag; byte 0x09 decoded independently from TWO distinct authentic
    # fixtures at their respective Raydium instruction, both agreeing.
    # This project's own real evidence does not by itself name the
    # instruction "SwapBaseIn" (the fixtures' captured logs only show the
    # inner SPL-token legs, not a Raydium-emitted instruction name) --
    # `swap_base_in` is recorded here as the conventional public label for
    # Raydium AMM V4 instruction tag 9, not as evidence this parser
    # independently derived; the byte value itself is fully independently
    # derived twice.
    _SwapInstructionEvidence(
        program_id="675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
        discriminator=bytes.fromhex("09"),
        semantic_label="swap_base_in",
        citation_fixture=(
            "tests/golden/fixtures/real/sources/"
            "eb7e24823b36abbcfd049942b3fcf6b27763fa12.source.json"
            " (real_mainnet_partial_sell) and "
            "tests/golden/fixtures/real/sources/"
            "fa277c7d4ff997f320c38f8e15e8e02ec49983cb.source.json"
            " (real_mainnet_token_to_sol_swap)"
        ),
        citation_location=(
            "real_mainnet_partial_sell top-level instruction index 3 "
            "(signature 2XgzfkWeDeua4oemWXrj3JzhxVsV4mGsqVZfETSbhn6hGFuLvi2fjdK2TGcmuQQnZSEjUmMmPjUnCFWDebGJcgWQ); "
            "real_mainnet_token_to_sol_swap top-level instruction index 4 "
            "(signature 3aQZsNRUbNXpH54GQEaxFpWZsmL554cYGGtWqqoypz8b6LUDYprbRd9AwgivXRLtFBYCU6MU6e9ANurwP8dCMV6)"
        ),
    ),
    # Orca Whirlpool -- 8-byte Anchor discriminator for `swap`
    # (sha256("global:swap")[:8]), decoded from a genuine inner-instruction
    # invocation of the Whirlpool program inside a real DFlow-routed swap
    # already committed as Phase 1.5 evidence; corroborated by that
    # transaction's own captured logs: "Program
    # whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc invoke [2]" immediately
    # followed by "Program log: Instruction: Swap". The SAME program's
    # authentic non-swap instructions (DecreaseLiquidity/CollectFees/
    # ClosePosition, see real_mainnet_orca_close_position_multi_account.json)
    # carry different discriminators and are deliberately NOT accepted.
    _SwapInstructionEvidence(
        program_id="whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        discriminator=bytes.fromhex("f8c69e91e17587c8"),
        semantic_label="swap",
        citation_fixture=("orchestration/phase_1_5/evidence/raw/suppl_11_dflow_swap_with_fee.json"),
        citation_location=(
            "inner instruction of top-level instruction index 3, position 25 "
            "within that inner-instruction group; signature "
            "627zjqXdMpkogJFCxhcnVTtFCUHWpkAWXoMQPCwQKWnpCJcAzqeg5kx29p8cxmTKHAhXorxEjAVF8Rc1xryyyT7B"
        ),
    ),
    # pump.fun bonding-curve program -- 8-byte Anchor discriminator for
    # `buy` (sha256("global:buy")[:8]), decoded from the fixture's own
    # instruction `data`; corroborated by that fixture's own captured
    # log "Program log: Instruction: Buy". No authentic `sell` evidence is
    # committed anywhere in this project yet, so pump.fun `sell` is
    # deliberately absent -- not assumed from the `buy` discriminator or
    # program documentation.
    _SwapInstructionEvidence(
        program_id="6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        discriminator=bytes.fromhex("66063d1201daebea"),
        semantic_label="buy",
        citation_fixture=(
            "tests/golden/fixtures/real/sources/"
            "d8f98b52dda0de05f9868ddb0605a25e818beaef.source.json"
            " (real_mainnet_sol_to_token_swap)"
        ),
        citation_location=(
            "top-level instruction index 2; signature "
            "4U8kypMuCUCkR6teu2Vn8ujaEJUR3dcUU5QExZxSMMeJ5fRTvYfWs5M5AB9yNjjHKAQ4w433QVyUivc3Pp8gvG1R"
        ),
    ),
)

# Grouped by program ID for deterministic, bounded lookup -- iteration
# order within each program's tuple is exactly registry declaration order
# (stable, never set-based), so matching never depends on hash iteration.
_REGISTRY_BY_PROGRAM: Final[dict[str, tuple[_SwapInstructionEvidence, ...]]] = {}
for _entry in _SWAP_INSTRUCTION_REGISTRY:
    _REGISTRY_BY_PROGRAM.setdefault(_entry.program_id, ())
    _REGISTRY_BY_PROGRAM[_entry.program_id] = (*_REGISTRY_BY_PROGRAM[_entry.program_id], _entry)
del _entry


@dataclasses.dataclass(frozen=True, slots=True)
class _MatchedSwapInstruction:
    """The complete positive-evidence bundle bound to one canonical
    instruction object -- exactly the three fields
    ``ParsedTransaction.is_copy_eligible`` requires in addition to every
    existing gate."""

    program_id: str
    semantic_label: str
    discriminator_hex: str


def _resolve_program_id(ix: dict[str, Any], keys: list[str]) -> str | None:
    """The program ID this single instruction object invokes, or ``None``
    if it cannot be resolved from canonical evidence. Handles both raw RPC
    instruction encodings seen in this project's real-chain evidence:
    index-based (``programIdIndex`` resolved against ``accountKeys``) and
    ``jsonParsed``-style (``programId`` given directly as a pubkey
    string). A ``programIdIndex`` must be a real, non-``bool`` integer
    that resolves within the canonical key list; ``bool`` is rejected even
    though it is an ``int`` subclass in Python, since ``True``/``False``
    are never a meaningful account index. A direct ``programId`` must be a
    non-empty string."""
    program_id = ix.get("programId")
    if isinstance(program_id, str) and program_id:
        return program_id
    idx = ix.get("programIdIndex")
    if isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < len(keys):
        return keys[idx]
    return None


def _iter_candidate_instructions(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Every top-level and inner instruction object in this transaction,
    in deterministic (document) order -- top-level instructions first,
    then each inner-instruction group in its own listed order. Never
    assumes only one instruction encoding; non-``dict`` entries (malformed
    evidence) are skipped rather than raising."""
    instructions: list[dict[str, Any]] = []
    for ix in raw["transaction"]["message"].get("instructions") or []:
        if isinstance(ix, dict):
            instructions.append(ix)
    for group in raw.get("meta", {}).get("innerInstructions") or []:
        if isinstance(group, dict):
            for ix in group.get("instructions") or []:
                if isinstance(ix, dict):
                    instructions.append(ix)
    return instructions


def _matched_swap_instruction(raw: dict[str, Any]) -> _MatchedSwapInstruction | None:
    """Positive semantic proof: the one canonical instruction object (if
    any) whose resolved program ID AND decoded ``data`` discriminator
    together match a single ``_SWAP_INSTRUCTION_REGISTRY`` entry -- the
    sole source of evidence :class:`ParsedTransaction.is_copy_eligible`
    requires in addition to balance shape. A recognized discriminator
    under the wrong program, or a recognized program with unmatched/
    missing/malformed data, produces no match. Deterministic: candidates
    are gathered in canonical instruction order and, if more than one
    genuinely matches, the lexicographically-least (program_id,
    semantic_label, discriminator_hex) tuple is returned -- never
    dependent on set/dict iteration order."""
    keys = _account_keys(raw)
    candidates: list[_MatchedSwapInstruction] = []

    for ix in _iter_candidate_instructions(raw):
        program_id = _resolve_program_id(ix, keys)
        if program_id is None:
            continue
        entries = _REGISTRY_BY_PROGRAM.get(program_id)
        if not entries:
            continue
        decoded = _decode_base58_strict(ix.get("data"))
        if decoded is None:
            continue
        for entry in entries:
            n = len(entry.discriminator)
            if len(decoded) >= n and decoded[:n] == entry.discriminator:
                candidates.append(
                    _MatchedSwapInstruction(
                        program_id=entry.program_id,
                        semantic_label=entry.semantic_label,
                        discriminator_hex=entry.discriminator.hex(),
                    )
                )

    if not candidates:
        return None
    candidates.sort(key=lambda m: (m.program_id, m.semantic_label, m.discriminator_hex))
    return candidates[0]


@dataclasses.dataclass(frozen=True, slots=True)
class AssetMove:
    asset: str  # "SOL" or a mint address
    amount_raw: int  # signed; negative = outflow, positive = inflow
    decimals: int


@dataclasses.dataclass(frozen=True, slots=True)
class AccountAssetDelta:
    """One wallet-owned *account*'s net balance change, preserved before
    :func:`compute_asset_deltas`'s by-mint aggregation collapses distinct
    accounts of the same mint together (Phase 1 remediation round 6,
    finding #3). By-mint aggregation is exactly right for classification
    (a wallet's net economic position in an asset is what matters for
    "did it trade X for Y"), but it is the wrong oracle for proving a
    *multiple-token-account* transaction happened at all: two accounts of
    the same mint moving in opposite directions can net to zero and
    vanish entirely from :func:`compute_asset_deltas`'s output, even
    though two genuinely distinct, materially-relevant token accounts
    were involved. ``account_index`` is the account's own position in
    ``transaction.message.accountKeys`` (the SPL Token Program's
    ``accountIndex`` field for a token-balance entry, or the wallet's own
    index for the native-SOL row); ``account_identifier`` is that index's
    resolved pubkey."""

    account_identifier: str
    account_index: int
    owner: str
    mint: str  # "SOL" (canonical) or a mint address
    pre_raw_amount: int
    post_raw_amount: int
    net_raw_delta: int
    decimals: int
    ui_delta: str  # exact decimal string


@dataclasses.dataclass(frozen=True, slots=True)
class ParsedTransaction:
    classification: Classification
    confidence: Decimal
    parser_version: str
    reason: str

    wallet_address: str
    slot: int
    block_time: datetime | None

    input_mint: str | None
    input_amount_raw: int | None
    input_amount_ui: Decimal | None
    input_decimals: int | None

    output_mint: str | None
    output_amount_raw: int | None
    output_amount_ui: Decimal | None
    output_decimals: int | None

    network_fee_raw: int

    # Phase 1.5 remediation round 1 (program only), extended round 2
    # (program AND instruction discriminator): the exact
    # _SWAP_INSTRUCTION_REGISTRY entry this transaction's own canonical
    # instruction evidence positively demonstrated was invoked -- all
    # three fields bound to the SAME matched instruction object, or all
    # None if no supported trade instruction was found. Always computed
    # from raw evidence at parse time (never inferred from
    # classification); default to None so existing direct-construction
    # call sites for non-swap classifications remain valid.
    matched_swap_program_id: str | None = None
    matched_semantic_label: str | None = None
    matched_discriminator_hex: str | None = None

    @property
    def is_copy_eligible(self) -> bool:
        """Mechanical gate: an ambiguous/UNKNOWN, low-confidence, or
        decimals-zero (non-fungible/NFT-shaped) leg can never create a
        live-copy signal, regardless of what any downstream code does or
        forgets to check (Phase 1 remediation round 5, finding #4).

        Phase 1.5 remediation round 1: balance shape alone (exactly one
        asset given up, one received) is no longer sufficient by itself.
        A lending withdrawal/redemption, a staking deposit, or any other
        genuine non-trade DeFi action can produce the identical one-in/
        one-out shape without being a swap.

        Phase 1.5 remediation round 2: "some instruction invoked an
        allowlisted program" is likewise insufficient -- the same program
        also executes non-trade instructions. All three match-evidence
        fields (bound to one canonical instruction object by
        ``_matched_swap_instruction``) must be present; any missing or
        unknown field means ineligible. Unmatched/unsupported programs or
        instructions preserve their research classification but are never
        automatically copy eligible."""
        if self.classification not in _COPY_ELIGIBLE_CLASSIFICATIONS:
            return False
        if self.confidence < _MIN_COPY_ELIGIBLE_CONFIDENCE:
            return False
        if (
            self.matched_swap_program_id is None
            or self.matched_semantic_label is None
            or self.matched_discriminator_hex is None
        ):
            return False
        # A one-for-one balance-delta shape looks identical whether the
        # asset received is a fungible token or a single non-fungible
        # unit (decimals == 0) -- never automatically a fungible
        # copy-trade swap signal.
        return self.input_decimals != 0 and self.output_decimals != 0


def _canonical_asset(mint: str) -> str:
    return NATIVE_SOL_ASSET if mint == WRAPPED_SOL_MINT else mint


def _account_keys(raw: dict[str, Any]) -> list[str]:
    message = raw["transaction"]["message"]
    keys = message["accountKeys"]
    # Some RPC shapes return account keys as {"pubkey": "..."} objects
    # (e.g. jsonParsed encoding); accept both forms deterministically.
    return [k["pubkey"] if isinstance(k, dict) else k for k in keys]


def _sol_deltas(raw: dict[str, Any], wallet_address: str) -> dict[str, int]:
    keys = _account_keys(raw)
    if wallet_address not in keys:
        return {}
    idx = keys.index(wallet_address)
    meta = raw["meta"]
    pre = meta["preBalances"][idx]
    post = meta["postBalances"][idx]
    delta = post - pre
    if idx == 0:
        # Only the fee payer (account index 0) pays the network fee; add it
        # back so the fee is accounted for separately (step 5) rather than
        # being misread as an asset the wallet "swapped away".
        delta += meta.get("fee", 0)
    return {NATIVE_SOL_ASSET: delta} if delta != 0 else {}


def _token_deltas(
    raw: dict[str, Any], wallet_address: str
) -> tuple[dict[str, int], dict[str, int]]:
    """Returns (deltas_by_asset, decimals_by_asset). Wrapped SOL is folded
    into the native SOL bucket per canonicalization (step 3)."""
    meta = raw["meta"]
    pre_by_key: dict[tuple[int, str], int] = {}
    decimals_by_mint: dict[str, int] = {}
    for entry in meta.get("preTokenBalances", []) or []:
        if entry.get("owner") != wallet_address:
            continue
        key = (entry["accountIndex"], entry["mint"])
        pre_by_key[key] = int(entry["uiTokenAmount"]["amount"])
        decimals_by_mint[entry["mint"]] = entry["uiTokenAmount"]["decimals"]

    post_by_key: dict[tuple[int, str], int] = {}
    for entry in meta.get("postTokenBalances", []) or []:
        if entry.get("owner") != wallet_address:
            continue
        key = (entry["accountIndex"], entry["mint"])
        post_by_key[key] = int(entry["uiTokenAmount"]["amount"])
        decimals_by_mint[entry["mint"]] = entry["uiTokenAmount"]["decimals"]

    deltas_by_asset: dict[str, int] = {}
    for key in set(pre_by_key) | set(post_by_key):
        _, mint = key
        delta = post_by_key.get(key, 0) - pre_by_key.get(key, 0)
        if delta == 0:
            continue
        asset = _canonical_asset(mint)
        decimals = NATIVE_SOL_DECIMALS if asset == NATIVE_SOL_ASSET else decimals_by_mint[mint]
        decimals_by_mint.setdefault(asset, decimals)
        deltas_by_asset[asset] = deltas_by_asset.get(asset, 0) + delta

    decimals_out = {
        asset: (NATIVE_SOL_DECIMALS if asset == NATIVE_SOL_ASSET else decimals_by_mint[asset])
        for asset in deltas_by_asset
    }
    return deltas_by_asset, decimals_out


def _newly_created_wallet_accounts(raw: dict[str, Any], wallet_address: str) -> set[str]:
    """Mint addresses that gained a wallet-owned token account in this
    transaction where none existed before (used by the TOKEN_CREATE
    heuristic)."""
    meta = raw["meta"]
    pre_mints = {
        e["mint"]
        for e in (meta.get("preTokenBalances", []) or [])
        if e.get("owner") == wallet_address
    }
    post_mints = {
        e["mint"]
        for e in (meta.get("postTokenBalances", []) or [])
        if e.get("owner") == wallet_address
    }
    return post_mints - pre_mints


def _ui_amount(raw_amount: int, decimals: int) -> Decimal:
    return Decimal(raw_amount).scaleb(-decimals)


def _combined_deltas(
    raw: dict[str, Any], wallet_address: str
) -> tuple[dict[str, int], dict[str, int]]:
    """The complete set of net wallet-owned balance deltas (SOL +
    tokens, wrapped SOL canonicalized into the native bucket) and each
    asset's decimals -- the single source of truth both
    :func:`parse_transaction`'s classification and
    :func:`compute_asset_deltas`'s independent public view are built
    from, so the two can never silently diverge."""
    sol_deltas = _sol_deltas(raw, wallet_address)
    token_deltas, token_decimals = _token_deltas(raw, wallet_address)

    deltas: dict[str, int] = dict(token_deltas)
    for asset, amount in sol_deltas.items():
        deltas[asset] = deltas.get(asset, 0) + amount
    deltas = {asset: amount for asset, amount in deltas.items() if amount != 0}

    decimals_by_asset = dict(token_decimals)
    decimals_by_asset.setdefault(NATIVE_SOL_ASSET, NATIVE_SOL_DECIMALS)
    return deltas, decimals_by_asset


def compute_asset_deltas(raw: dict[str, Any], wallet_address: str) -> tuple[AssetMove, ...]:
    """The complete, ordered (sorted by asset identifier) set of net
    wallet-owned balance deltas this transaction produced -- the same
    deltas the classifier computes internally, exposed publicly so a
    golden-fixture reviewer's own independent expectation (Phase 1
    remediation round 5, finding #1) can be checked against every asset
    that actually moved, not only the single primary in/out leg
    :class:`ParsedTransaction` reports. Returns an empty tuple for a
    failed transaction (``meta.err`` set) or one with no wallet-relevant
    delta at all, matching :func:`parse_transaction`'s own UNKNOWN cases."""
    if raw["meta"].get("err") is not None:
        return ()
    deltas, decimals_by_asset = _combined_deltas(raw, wallet_address)
    return tuple(
        AssetMove(asset=asset, amount_raw=deltas[asset], decimals=decimals_by_asset[asset])
        for asset in sorted(deltas)
    )


def compute_account_level_deltas(
    raw: dict[str, Any], wallet_address: str
) -> tuple[AccountAssetDelta, ...]:
    """The complete, ordered (by ``account_index``, then ``mint``) set of
    net wallet-owned *account*-level balance changes this transaction
    produced -- one row per materially-changed account, never aggregated
    by mint (Phase 1 remediation round 6, finding #3). This is the
    account-level ground truth an independent golden-fixture reviewer
    needs to prove a genuine multiple-token-account/LP-style transaction:
    :func:`compute_asset_deltas`'s by-mint view can make two distinct
    accounts of the same mint moving in opposite directions net to zero
    and vanish entirely, discarding exactly the evidence the oracle needs.
    Returns an empty tuple for a failed transaction (``meta.err`` set),
    matching :func:`compute_asset_deltas`."""
    if raw["meta"].get("err") is not None:
        return ()

    keys = _account_keys(raw)
    meta = raw["meta"]
    rows: list[AccountAssetDelta] = []

    if wallet_address in keys:
        idx = keys.index(wallet_address)
        pre = meta["preBalances"][idx]
        post = meta["postBalances"][idx]
        delta = post - pre
        if idx == 0:
            # Same fee-inclusion convention as _sol_deltas: the fee payer's
            # net delta is reported before deducting the network fee, which
            # is accounted for separately.
            delta += meta.get("fee", 0)
        if delta != 0:
            rows.append(
                AccountAssetDelta(
                    account_identifier=wallet_address,
                    account_index=idx,
                    owner=wallet_address,
                    mint=NATIVE_SOL_ASSET,
                    pre_raw_amount=pre,
                    post_raw_amount=post,
                    net_raw_delta=delta,
                    decimals=NATIVE_SOL_DECIMALS,
                    ui_delta=str(_ui_amount(delta, NATIVE_SOL_DECIMALS)),
                )
            )

    pre_by_key: dict[tuple[int, str], tuple[int, int]] = {}
    for entry in meta.get("preTokenBalances", []) or []:
        if entry.get("owner") != wallet_address:
            continue
        key = (entry["accountIndex"], entry["mint"])
        pre_by_key[key] = (
            int(entry["uiTokenAmount"]["amount"]),
            entry["uiTokenAmount"]["decimals"],
        )

    post_by_key: dict[tuple[int, str], tuple[int, int]] = {}
    for entry in meta.get("postTokenBalances", []) or []:
        if entry.get("owner") != wallet_address:
            continue
        key = (entry["accountIndex"], entry["mint"])
        post_by_key[key] = (
            int(entry["uiTokenAmount"]["amount"]),
            entry["uiTokenAmount"]["decimals"],
        )

    for account_index, mint in sorted(set(pre_by_key) | set(post_by_key)):
        key = (account_index, mint)
        pre_amount, pre_decimals = pre_by_key.get(key, (0, None))
        post_amount, post_decimals = post_by_key.get(key, (0, None))
        delta = post_amount - pre_amount
        if delta == 0:
            continue
        asset = _canonical_asset(mint)
        source_decimals = post_decimals if post_decimals is not None else pre_decimals
        assert source_decimals is not None  # at least one side always has an entry here
        row_decimals = NATIVE_SOL_DECIMALS if asset == NATIVE_SOL_ASSET else source_decimals
        rows.append(
            AccountAssetDelta(
                account_identifier=(
                    keys[account_index]
                    if 0 <= account_index < len(keys)
                    else f"index:{account_index}"
                ),
                account_index=account_index,
                owner=wallet_address,
                mint=asset,
                pre_raw_amount=pre_amount,
                post_raw_amount=post_amount,
                net_raw_delta=delta,
                decimals=row_decimals,
                ui_delta=str(_ui_amount(delta, row_decimals)),
            )
        )

    rows.sort(key=lambda r: (r.account_index, r.mint))
    return tuple(rows)


def parse_transaction(
    raw: dict[str, Any],
    *,
    wallet_address: str,
    slot: int,
    block_time: datetime | None,
) -> ParsedTransaction:
    """Deterministically classify one raw Solana transaction from the
    perspective of ``wallet_address``. Never raises on well-formed input
    (including a failed on-chain transaction); malformed/missing required
    fields raise ``KeyError``/``ValueError`` so a structurally broken raw
    payload is never silently misclassified as UNKNOWN."""
    meta = raw["meta"]
    fee = int(meta.get("fee", 0))
    account_keys = _account_keys(raw)
    is_fee_payer = bool(account_keys) and account_keys[0] == wallet_address
    network_fee_raw = fee if is_fee_payer else 0
    matched_instruction = _matched_swap_instruction(raw)

    def _result(
        classification: Classification,
        confidence: str,
        reason: str,
        *,
        input_asset: str | None = None,
        input_amount: int | None = None,
        output_asset: str | None = None,
        output_amount: int | None = None,
        decimals_by_asset: dict[str, int] | None = None,
    ) -> ParsedTransaction:
        decimals_by_asset = decimals_by_asset or {}

        def _decimals(asset: str) -> int:
            return NATIVE_SOL_DECIMALS if asset == NATIVE_SOL_ASSET else decimals_by_asset[asset]

        return ParsedTransaction(
            classification=classification,
            confidence=Decimal(confidence),
            parser_version=PARSER_VERSION,
            reason=reason,
            wallet_address=wallet_address,
            slot=slot,
            block_time=block_time,
            input_mint=input_asset,
            input_amount_raw=abs(input_amount) if input_amount is not None else None,
            input_amount_ui=(
                _ui_amount(abs(input_amount), _decimals(input_asset))
                if input_amount is not None and input_asset is not None
                else None
            ),
            input_decimals=(_decimals(input_asset) if input_asset is not None else None),
            output_mint=output_asset,
            output_amount_raw=output_amount if output_amount is not None else None,
            output_amount_ui=(
                _ui_amount(output_amount, _decimals(output_asset))
                if output_amount is not None and output_asset is not None
                else None
            ),
            output_decimals=(_decimals(output_asset) if output_asset is not None else None),
            network_fee_raw=network_fee_raw,
            matched_swap_program_id=(
                matched_instruction.program_id if matched_instruction is not None else None
            ),
            matched_semantic_label=(
                matched_instruction.semantic_label if matched_instruction is not None else None
            ),
            matched_discriminator_hex=(
                matched_instruction.discriminator_hex if matched_instruction is not None else None
            ),
        )

    if meta.get("err") is not None:
        return _result("UNKNOWN", "0.000", "transaction failed on-chain (meta.err set)")

    deltas, decimals_by_asset = _combined_deltas(raw, wallet_address)

    if not deltas:
        return _result("UNKNOWN", "0.000", "no wallet-relevant balance change found")

    negatives = {a: d for a, d in deltas.items() if d < 0}
    positives = {a: d for a, d in deltas.items() if d > 0}

    # TOKEN_CREATE heuristic: a brand-new wallet-owned token account
    # appeared this transaction (post-only mint) with a zero resulting
    # balance (so it never enters `deltas` at all -- a delta of 0 is
    # filtered out above), the wallet paid SOL (rent-exemption) to do it,
    # and no asset was actually received. This deliberately does NOT match
    # "bought a token for the first time via a swap": that case has a
    # *nonzero* delta for the newly-seen mint, which shows up in `positives`
    # and correctly falls through to the swap classification below instead.
    new_accounts = _newly_created_wallet_accounts(raw, wallet_address)
    if (
        new_accounts
        and not (set(deltas) & new_accounts)
        and set(negatives) <= {NATIVE_SOL_ASSET}
        and not positives
    ):
        return _result(
            "TOKEN_CREATE",
            "0.600",
            "new wallet-owned token account created with zero balance; "
            "SOL paid for rent, no asset actually received",
            decimals_by_asset=decimals_by_asset,
        )

    non_sol_negatives = {a: d for a, d in negatives.items() if a != NATIVE_SOL_ASSET}
    non_sol_positives = {a: d for a, d in positives.items() if a != NATIVE_SOL_ASSET}

    # LP_ACTION heuristic: two or more non-SOL assets move in the SAME
    # direction together (both given up, or both received) -- characteristic
    # of adding/removing liquidity, unlike a swap where one side decreases
    # while the other increases.
    if len(non_sol_negatives) >= 2 and not non_sol_positives:
        return _result(
            "LP_ACTION",
            "0.600",
            "two or more non-SOL assets given up together with no offsetting asset received "
            "(liquidity-add pattern)",
            decimals_by_asset=decimals_by_asset,
        )
    if len(non_sol_positives) >= 2 and not non_sol_negatives:
        return _result(
            "LP_ACTION",
            "0.600",
            "two or more non-SOL assets received together with no offsetting asset given up "
            "(liquidity-remove pattern)",
            decimals_by_asset=decimals_by_asset,
        )

    if len(negatives) == 1 and len(positives) == 1:
        (in_asset, in_amount) = next(iter(negatives.items()))
        (out_asset, out_amount) = next(iter(positives.items()))
        return _result(
            "SWAP_SIMPLE",
            "1.000",
            "exactly one asset given up and exactly one asset received",
            input_asset=in_asset,
            input_amount=in_amount,
            output_asset=out_asset,
            output_amount=out_amount,
            decimals_by_asset=decimals_by_asset,
        )

    if negatives and positives:
        # More than one asset moved on at least one side -- multi-hop swap.
        in_asset, in_amount = max(negatives.items(), key=lambda kv: abs(kv[1]))
        out_asset, out_amount = max(positives.items(), key=lambda kv: kv[1])
        return _result(
            "SWAP_COMPLEX",
            "0.700",
            "multiple assets moved on both sides; largest outflow/inflow reported as primary leg",
            input_asset=in_asset,
            input_amount=in_amount,
            output_asset=out_asset,
            output_amount=out_amount,
            decimals_by_asset=decimals_by_asset,
        )

    if positives and not negatives:
        # Phase 1 remediation round 5, finding #4: two or more DISTINCT
        # assets received together with nothing given up (e.g. a
        # native-SOL rent refund alongside an unrelated released token in
        # the same instruction) is genuinely ambiguous -- not caught by
        # the LP_ACTION heuristic above, which only looks at non-SOL
        # assets, so "SOL + exactly one non-SOL asset" fell through here
        # and was previously silently collapsed into TRANSFER_IN by
        # picking the largest leg. Real multi-asset ambiguity must
        # surface as UNKNOWN, never as a confident single-asset guess.
        if len(positives) >= 2:
            return _result(
                "UNKNOWN",
                "0.000",
                "ambiguous multi-asset inflow: two or more distinct assets received "
                "together with no offsetting outflow -- cannot be resolved to a single "
                "confident inflow without instruction-level evidence",
                decimals_by_asset=decimals_by_asset,
            )
        out_asset, out_amount = next(iter(positives.items()))
        return _result(
            "TRANSFER_IN",
            "1.000",
            "only inflow(s), no offsetting outflow",
            output_asset=out_asset,
            output_amount=out_amount,
            decimals_by_asset=decimals_by_asset,
        )

    if negatives and not positives:
        if len(negatives) >= 2:
            return _result(
                "UNKNOWN",
                "0.000",
                "ambiguous multi-asset outflow: two or more distinct assets given up "
                "together with no offsetting inflow -- cannot be resolved to a single "
                "confident outflow without instruction-level evidence",
                decimals_by_asset=decimals_by_asset,
            )
        in_asset, in_amount = next(iter(negatives.items()))
        return _result(
            "TRANSFER_OUT",
            "1.000",
            "only outflow(s), no offsetting inflow",
            input_asset=in_asset,
            input_amount=in_amount,
            decimals_by_asset=decimals_by_asset,
        )

    return _result(
        "UNKNOWN", "0.000", "balance deltas did not match any known pattern"
    )  # pragma: no cover
