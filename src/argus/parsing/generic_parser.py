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
the confidence floor, is copy-eligible in v1 (see
``ParsedTransaction.is_copy_eligible``).
"""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal

PARSER_VERSION: Final[str] = "generic_balance_delta_v1"

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

    @property
    def is_copy_eligible(self) -> bool:
        """Mechanical gate: an ambiguous/UNKNOWN, low-confidence, or
        decimals-zero (non-fungible/NFT-shaped) leg can never create a
        live-copy signal, regardless of what any downstream code does or
        forgets to check (Phase 1 remediation round 5, finding #4)."""
        if self.classification not in _COPY_ELIGIBLE_CLASSIFICATIONS:
            return False
        if self.confidence < _MIN_COPY_ELIGIBLE_CONFIDENCE:
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
