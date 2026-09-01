"""Deterministic early-buyer extraction (MASTER_SPEC.md section 33
EARLY-BUYER EXTRACTION; Phase 2 build item 7; required-implementation
item 5).

Never calls into ``argus.parsing.generic_parser`` (that module answers
"what did ONE tracked wallet do in this transaction," a different
question from "which wallets, of any identity, received this mint net-
positive in this transaction") -- :func:`net_token_deltas_by_owner`
independently re-derives per-owner net token deltas straight from
``meta.preTokenBalances``/``postTokenBalances``, the same raw fields
``generic_parser`` itself reads, so this module's own arithmetic is a
genuine independent path, not a wrapper.

:func:`extract_early_buyers` is a pure function over an already-fetched
list of raw transactions: it re-derives each wallet's globally-earliest
net-positive receipt of ``mint`` (by ``(slot, signature)``, a total,
input-order-independent ordering) and returns at most ``max_candidates``
rows in that stable order. Required test P2-T5: feeding the exact same
transactions twice, or in a different list order, must reproduce
byte-identical output -- guaranteed here because the function sorts by
the evidence's own ``(slot, signature)`` identity, never by input
position, and a failed on-chain transaction (``meta.err`` set) never
contributes a candidate.
"""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Final

ALGORITHM_VERSION: Final[str] = "early_buyer_extraction_v1"
BUILD_HASH: Final[str] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclasses.dataclass(frozen=True, slots=True)
class RawTransactionEvidence:
    """One raw transaction plus the identity fields extraction needs but
    cannot always safely re-derive from the payload alone (some raw
    shapes nest the signature/slot differently)."""

    raw: dict[str, Any]
    signature: str
    slot: int
    block_time: datetime | None
    evidence_reference: str


@dataclasses.dataclass(frozen=True, slots=True)
class BuyerCandidate:
    wallet_address: str
    first_buy_slot: int
    first_buy_time: datetime | None
    sequence_number: int
    amount_raw: int
    amount_decimals: int
    evidence_reference: str
    possible_deployer: bool = False


def net_token_deltas_by_owner(raw: dict[str, Any], *, mint: str) -> dict[str, int]:
    """Every distinct token-account owner's net raw balance change for
    ``mint`` in this one transaction, derived independently from
    ``meta.preTokenBalances``/``postTokenBalances`` (never from
    ``argus.parsing.generic_parser``). A failed transaction
    (``meta.err`` set) contributes nothing."""
    meta = raw.get("meta")
    if not isinstance(meta, dict) or meta.get("err") is not None:
        return {}

    pre: dict[str, int] = {}
    for entry in meta.get("preTokenBalances") or []:
        if isinstance(entry, dict) and entry.get("mint") == mint:
            owner = entry.get("owner")
            amount = entry.get("uiTokenAmount", {})
            if isinstance(owner, str) and isinstance(amount, dict):
                pre[owner] = pre.get(owner, 0) + int(amount.get("amount", 0))

    post: dict[str, int] = {}
    for entry in meta.get("postTokenBalances") or []:
        if isinstance(entry, dict) and entry.get("mint") == mint:
            owner = entry.get("owner")
            amount = entry.get("uiTokenAmount", {})
            if isinstance(owner, str) and isinstance(amount, dict):
                post[owner] = post.get(owner, 0) + int(amount.get("amount", 0))

    owners = set(pre) | set(post)
    return {owner: post.get(owner, 0) - pre.get(owner, 0) for owner in owners}


def _decimals_for_mint(raw: dict[str, Any], *, mint: str) -> int | None:
    meta = raw.get("meta") or {}
    for key in ("postTokenBalances", "preTokenBalances"):
        for entry in meta.get(key) or []:
            if isinstance(entry, dict) and entry.get("mint") == mint:
                amount = entry.get("uiTokenAmount")
                if isinstance(amount, dict) and isinstance(amount.get("decimals"), int):
                    return amount["decimals"]
    return None


def extract_early_buyers(
    transactions: list[RawTransactionEvidence],
    *,
    mint: str,
    max_candidates: int = 100,
    deployer_wallet: str | None = None,
) -> list[BuyerCandidate]:
    """Every distinct wallet's globally-earliest net-positive receipt of
    ``mint`` across ``transactions``, ordered deterministically by
    ``(slot, signature)`` -- independent of the order ``transactions``
    was given in, and stable across repeated/paginated replay (P2-T5).
    Never invents a buyer beyond what the evidence supports; never
    excludes ``deployer_wallet`` (or any wallet) from the result -- it is
    only tagged, per MASTER_SPEC.md section 33's explicit "tag, do not
    delete" rule."""
    first_seen: dict[str, tuple[int, str, int, datetime | None, int | None, str]] = {}

    for tx in transactions:
        deltas = net_token_deltas_by_owner(tx.raw, mint=mint)
        decimals = _decimals_for_mint(tx.raw, mint=mint)
        for owner, delta in deltas.items():
            if delta <= 0:
                continue
            candidate_key = (tx.slot, tx.signature)
            existing = first_seen.get(owner)
            if existing is None or candidate_key < (existing[0], existing[1]):
                first_seen[owner] = (
                    tx.slot,
                    tx.signature,
                    delta,
                    tx.block_time,
                    decimals,
                    tx.evidence_reference,
                )

    ordered = sorted(first_seen.items(), key=lambda kv: (kv[1][0], kv[1][1]))

    candidates: list[BuyerCandidate] = []
    for index, (wallet, (slot, _sig, amount, block_time, decimals, evidence_ref)) in enumerate(
        ordered[:max_candidates], start=1
    ):
        candidates.append(
            BuyerCandidate(
                wallet_address=wallet,
                first_buy_slot=slot,
                first_buy_time=block_time,
                sequence_number=index,
                amount_raw=amount,
                amount_decimals=decimals if decimals is not None else 0,
                evidence_reference=evidence_ref,
                possible_deployer=(deployer_wallet is not None and wallet == deployer_wallet),
            )
        )
    return candidates
