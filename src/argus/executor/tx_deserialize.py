"""argus.executor.tx_deserialize — builds a real, non-fabricated
:class:`~argus.executor.attestation.UnsignedTransactionShape` from actual
Jupiter-returned unsigned transaction bytes, R2-01
(``argus-final-spec-recovery-002``).

Closes the gap the R2-02 audit named: ``UnsignedTransactionShape`` used to
exist only as a hand-constructed test fixture, with no code path anywhere
building one from a real transaction. This module is that path: it
parses the unsigned transaction's own account-key list (via ``solders``,
never a hand-rolled byte-format parser), combines it with a REAL pre/post
:class:`~argus.executor.simulation.SimulationResult` (never invented
balances), and decodes any SPL Token accounts involved with the fixed,
public SPL Token account layout (``argus.executor.token_account_codec``)
to recover exactly which mints moved, by how much, and whether anything
outside the intended input/output pair moved at all.

Fails closed: any account that cannot be positively explained (a token
account owned by the executor wallet that fails to decode, or a
simulated transaction error) sets ``simulated_balance_changes_explained
= False`` / ``unexplained_authority_behavior = True`` rather than
guessing -- so :func:`argus.executor.attestation.attest_transaction`
rejects it rather than silently accepting an unexplained transaction.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from solders.transaction import VersionedTransaction

from argus.executor.attestation import UnsignedTransactionShape
from argus.executor.simulation import SimulationResult
from argus.executor.token_account_codec import (
    NATIVE_SOL_MINT,
    SPL_TOKEN_PROGRAM_ID,
    TokenAccountDecodeError,
    decode_token_account,
)


class TransactionDeserializationError(RuntimeError):
    """Raised when the unsigned transaction bytes themselves are
    malformed -- never proceeds with a partially-parsed message."""


def _parse(unsigned_transaction_base64: str) -> VersionedTransaction:
    try:
        raw = base64.b64decode(unsigned_transaction_base64, validate=True)
    except Exception as exc:  # noqa: BLE001 - malformed input fails closed
        raise TransactionDeserializationError(f"not valid base64: {type(exc).__name__}") from exc
    try:
        return VersionedTransaction.from_bytes(raw)
    except Exception as exc:  # noqa: BLE001 - malformed input fails closed
        raise TransactionDeserializationError(
            f"not a valid Solana VersionedTransaction: {type(exc).__name__}"
        ) from exc


def unsigned_transaction_account_keys(unsigned_transaction_base64: str) -> list[str]:
    """The full account-key list of the unsigned transaction's message,
    in order -- account index 0 is always the fee payer (a Solana
    protocol invariant, not this module's own assumption). Callers use
    this exact list as the ``watch_addresses`` passed to
    :meth:`argus.executor.simulation.TransactionSimulationProvider.simulate`
    so pre/post state is captured for every account the transaction can
    possibly touch."""
    tx = _parse(unsigned_transaction_base64)
    return [str(key) for key in tx.message.account_keys]


def unsigned_transaction_fee_payer(unsigned_transaction_base64: str) -> str:
    keys = unsigned_transaction_account_keys(unsigned_transaction_base64)
    if not keys:
        raise TransactionDeserializationError("transaction message has no account keys")
    return keys[0]


@dataclass(frozen=True)
class _TokenDelta:
    mint: str
    amount_delta: int


def _decoded_or_none(data: bytes, *, owner_program: str | None) -> tuple[str, str, int] | None:
    if owner_program != SPL_TOKEN_PROGRAM_ID:
        return None
    try:
        decoded = decode_token_account(data)
    except TokenAccountDecodeError:
        return None
    return decoded.mint, decoded.owner, decoded.amount_raw


def deserialize_unsigned_transaction_shape(
    unsigned_transaction_base64: str,
    *,
    simulation: SimulationResult,
    executor_wallet_public_key: str,
    expected_input_mint: str,
    expected_output_mint: str,
) -> UnsignedTransactionShape:
    """Builds a real :class:`UnsignedTransactionShape` from
    ``unsigned_transaction_base64`` and a REAL pre/post
    :class:`~argus.executor.simulation.SimulationResult` covering (at
    least) every address ``unsigned_transaction_account_keys`` returned
    for this same transaction. Never trusts a provider's own quote as a
    substitute for what the transaction bytes and simulated execution
    actually show."""
    fee_payer = unsigned_transaction_fee_payer(unsigned_transaction_base64)

    decode_failed = False
    outflow_mints: set[str] = set()
    net_deltas_by_mint: dict[str, int] = {}
    addresses = set(simulation.pre_accounts) | set(simulation.post_accounts)
    for address in addresses:
        pre = simulation.pre_accounts.get(address)
        post = simulation.post_accounts.get(address)
        owner_program = (post.owner_program if post is not None and post.exists else None) or (
            pre.owner_program if pre is not None and pre.exists else None
        )
        if owner_program != SPL_TOKEN_PROGRAM_ID:
            continue

        pre_decoded = (
            _decoded_or_none(pre.data, owner_program=pre.owner_program)
            if pre is not None and pre.exists
            else None
        )
        post_decoded = (
            _decoded_or_none(post.data, owner_program=post.owner_program)
            if post is not None and post.exists
            else None
        )
        if pre is not None and pre.exists and pre_decoded is None:
            decode_failed = True
            continue
        if post is not None and post.exists and post_decoded is None:
            decode_failed = True
            continue

        reference = post_decoded or pre_decoded
        if reference is None:
            continue
        mint, token_owner, _ = reference
        if token_owner != executor_wallet_public_key:
            # Not a wallet-controlled account (e.g. an AMM/vault account
            # this route touches) -- irrelevant to
            # user_controlled_outflow_mints, which is about what the
            # EXECUTOR wallet itself gives up, not liquidity-pool internals.
            continue

        pre_amount = pre_decoded[2] if pre_decoded is not None else 0
        post_amount = post_decoded[2] if post_decoded is not None else 0
        delta = post_amount - pre_amount
        net_deltas_by_mint[mint] = net_deltas_by_mint.get(mint, 0) + delta

    for mint, delta in net_deltas_by_mint.items():
        if delta < 0:
            outflow_mints.add(mint)

    input_amount_raw = max(0, -net_deltas_by_mint.get(expected_input_mint, 0))
    output_amount_raw = max(0, net_deltas_by_mint.get(expected_output_mint, 0))
    input_explained = expected_input_mint in net_deltas_by_mint and input_amount_raw > 0
    output_explained = expected_output_mint in net_deltas_by_mint and output_amount_raw > 0

    fee_pre = simulation.pre_accounts.get(fee_payer)
    fee_post = simulation.post_accounts.get(fee_payer)
    fee_payer_native_delta = 0
    if fee_pre is not None and fee_pre.exists and fee_post is not None and fee_post.exists:
        fee_payer_native_delta = fee_pre.lamports - fee_post.lamports
    if expected_input_mint == NATIVE_SOL_MINT:
        fee_payer_native_delta -= input_amount_raw
    if expected_output_mint == NATIVE_SOL_MINT:
        fee_payer_native_delta += output_amount_raw
    total_fee_raw = max(0, fee_payer_native_delta)

    simulated_balance_changes_explained = (
        simulation.err is None and not decode_failed and input_explained and output_explained
    )
    unexplained_authority_behavior = simulation.err is not None or decode_failed

    return UnsignedTransactionShape(
        signer_public_key=fee_payer,
        fee_payer_public_key=fee_payer,
        input_mint=expected_input_mint,
        output_mint=expected_output_mint,
        input_amount_raw=input_amount_raw,
        total_fee_raw=total_fee_raw,
        user_controlled_outflow_mints=frozenset(outflow_mints),
        simulated=True,
        simulated_balance_changes_explained=simulated_balance_changes_explained,
        unexplained_authority_behavior=unexplained_authority_behavior,
    )
