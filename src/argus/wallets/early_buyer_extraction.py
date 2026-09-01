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
net-positive receipt of ``mint`` (by ``(slot, signature, wallet_address)``,
a total, input-order-independent ordering -- P2-R3: the explicit
``wallet_address`` tie-breaker is required because two or more owners are
routinely first-seen in the exact same transaction, i.e. tied on
``(slot, signature)`` alone) and returns at most ``max_candidates`` rows
in that stable order. Required test P2-T5: feeding the exact same
transactions twice, in a different list order, or under a different
``PYTHONHASHSEED``, must reproduce byte-identical output -- guaranteed
here because the sort key never falls back to Python ``dict``/``set``
iteration order (hash-seed-dependent for ``str`` keys) to break a tie, and
a failed on-chain transaction (``meta.err`` set) never contributes a
candidate.

P2-R3's second fix: every net-positive observation is still returned
(never invented, never silently erased -- MASTER_SPEC.md section 33's
"tag, do not delete" rule, and this evidence is always fully re-derivable
from the same immutable committed transaction bytes regardless), but each
candidate now also carries :data:`OWNERSHIP_SIGNER_WALLET` or
:data:`OWNERSHIP_UNRESOLVED_NON_SIGNER` (:func:`_transaction_signers`
below). A raw balance-delta alone cannot distinguish a genuine trader
wallet from a program-derived reserve/curve/pool/vault account that
merely received tokens as part of the transaction's own internal
mechanics -- but Solana requires every real buyer to have authorized
their own debit by signing the transaction (a PDA/program account can
never sign), so transaction-signer-set membership is a real,
evidence-grounded classifier, not a heuristic guess. Callers
(``argus.wallets.archaeology``) use this classification to decide wallet
candidacy; this module itself makes no such decision.
"""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Final

ALGORITHM_VERSION: Final[str] = "early_buyer_extraction_v2"
BUILD_HASH: Final[str] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

OWNERSHIP_SIGNER_WALLET: Final[str] = "SIGNER_WALLET"
OWNERSHIP_UNRESOLVED_NON_SIGNER: Final[str] = "UNRESOLVED_NON_SIGNER"


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
    ownership_classification: str
    possible_deployer: bool = False


def _transaction_signers(raw: dict[str, Any]) -> frozenset[str] | None:
    """The set of pubkeys that signed ``raw`` -- the leading
    ``header.numRequiredSignatures`` entries of ``message.accountKeys``,
    per Solana's legacy transaction-message encoding (the shape every raw
    ``getTransaction`` evidence file this project has committed uses).
    Returns ``None`` (never an empty set standing in for "no signers") on
    any missing/malformed shape -- callers must treat that as unresolved
    ownership, never as proof an owner is not a signer."""
    try:
        message = raw["transaction"]["message"]
        num_required = message["header"]["numRequiredSignatures"]
        account_keys = message["accountKeys"]
    except (KeyError, TypeError):
        return None
    if (
        not isinstance(num_required, int)
        or isinstance(num_required, bool)
        or num_required < 0
        or not isinstance(account_keys, list)
        or num_required > len(account_keys)
    ):
        return None
    signers = account_keys[:num_required]
    if not all(isinstance(key, str) for key in signers):
        return None
    return frozenset(signers)


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


@dataclasses.dataclass(frozen=True, slots=True)
class _FirstSeen:
    slot: int
    signature: str
    amount: int
    block_time: datetime | None
    decimals: int | None
    evidence_reference: str
    classification: str


def extract_early_buyers(
    transactions: list[RawTransactionEvidence],
    *,
    mint: str,
    max_candidates: int = 100,
    deployer_wallet: str | None = None,
) -> list[BuyerCandidate]:
    """Every distinct wallet's globally-earliest net-positive receipt of
    ``mint`` across ``transactions``, ordered deterministically by
    ``(slot, signature, wallet_address)`` -- independent of the order
    ``transactions`` was given in, stable across repeated/paginated
    replay, and independent of ``PYTHONHASHSEED`` (P2-T5, P2-R3's
    determinism fix -- the explicit wallet-address tie-breaker is what
    makes ties on ``(slot, signature)``, which are routine whenever more
    than one owner is first-seen in the same transaction, resolve the
    same way on every run). Never invents a buyer beyond what the
    evidence supports, and never excludes any observed owner from the
    result -- every one is returned and tagged with its
    ``ownership_classification`` (P2-R3's semantic fix: a program-derived
    reserve/curve/pool/vault account is never a meaningful buyer wallet,
    but its raw observation is preserved, not deleted). ``deployer_wallet``
    is likewise only ever tagged, per MASTER_SPEC.md section 33's
    explicit "tag, do not delete" rule."""
    first_seen: dict[str, _FirstSeen] = {}

    for tx in transactions:
        deltas = net_token_deltas_by_owner(tx.raw, mint=mint)
        decimals = _decimals_for_mint(tx.raw, mint=mint)
        signers = _transaction_signers(tx.raw)
        for owner, delta in deltas.items():
            if delta <= 0:
                continue
            candidate_key = (tx.slot, tx.signature, owner)
            existing = first_seen.get(owner)
            if existing is None or candidate_key < (
                existing.slot,
                existing.signature,
                owner,
            ):
                classification = (
                    OWNERSHIP_SIGNER_WALLET
                    if signers is not None and owner in signers
                    else OWNERSHIP_UNRESOLVED_NON_SIGNER
                )
                first_seen[owner] = _FirstSeen(
                    slot=tx.slot,
                    signature=tx.signature,
                    amount=delta,
                    block_time=tx.block_time,
                    decimals=decimals,
                    evidence_reference=tx.evidence_reference,
                    classification=classification,
                )

    ordered = sorted(first_seen.items(), key=lambda kv: (kv[1].slot, kv[1].signature, kv[0]))

    candidates: list[BuyerCandidate] = []
    for index, (wallet, seen) in enumerate(ordered[:max_candidates], start=1):
        candidates.append(
            BuyerCandidate(
                wallet_address=wallet,
                first_buy_slot=seen.slot,
                first_buy_time=seen.block_time,
                sequence_number=index,
                amount_raw=seen.amount,
                amount_decimals=seen.decimals if seen.decimals is not None else 0,
                evidence_reference=seen.evidence_reference,
                ownership_classification=seen.classification,
                possible_deployer=(deployer_wallet is not None and wallet == deployer_wallet),
            )
        )
    return candidates
