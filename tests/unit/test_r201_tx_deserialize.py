"""Tests for argus.executor.tx_deserialize -- R2-01
(``argus-final-spec-recovery-002``).

Builds a real (unsigned, placeholder-signature) ``VersionedTransaction``
via ``solders`` -- exactly the shape Jupiter's own ``swapTransaction``
base64 payload has -- and a hand-constructed but REAL pre/post
:class:`~argus.executor.simulation.SimulationResult` (the same shape a
real ``getMultipleAccounts``/``simulateTransaction`` round trip would
produce), then asserts the deserializer recovers real mints/amounts/fee
from it rather than trusting a quote.
"""

from __future__ import annotations

import base64

from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from argus.executor.simulation import AccountSnapshot, SimulationResult
from argus.executor.token_account_codec import SPL_TOKEN_PROGRAM_ID
from argus.executor.tx_deserialize import (
    deserialize_unsigned_transaction_shape,
    unsigned_transaction_account_keys,
    unsigned_transaction_fee_payer,
)

_SYSTEM_PROGRAM_ID = "11111111111111111111111111111111111111111"

FEE_PAYER = Keypair()
INPUT_MINT = Pubkey.new_unique()
OUTPUT_MINT = Pubkey.new_unique()
INPUT_ATA = Pubkey.new_unique()
OUTPUT_ATA = Pubkey.new_unique()
AMM_VAULT = Pubkey.new_unique()
AMM_AUTHORITY = Pubkey.new_unique()


def _encode_token_account(*, mint: Pubkey, owner: Pubkey, amount: int) -> bytes:
    body = bytes(mint) + bytes(owner) + amount.to_bytes(8, "little", signed=False)
    return body + bytes(165 - len(body))


def _build_unsigned_transaction_base64() -> str:
    ix = Instruction(
        program_id=Pubkey.new_unique(),
        accounts=[
            AccountMeta(INPUT_ATA, False, True),
            AccountMeta(OUTPUT_ATA, False, True),
            AccountMeta(AMM_VAULT, False, True),
        ],
        data=bytes([9, 9, 9]),
    )
    message = MessageV0.try_compile(FEE_PAYER.pubkey(), [ix], [], Hash.default())
    placeholder_sigs = [Signature.default() for _ in range(message.header.num_required_signatures)]
    tx = VersionedTransaction.populate(message, placeholder_sigs)
    return base64.b64encode(bytes(tx)).decode("ascii")


def _base_simulation(*, fee_lamports: int = 5_000) -> tuple[str, dict, dict]:
    unsigned_b64 = _build_unsigned_transaction_base64()
    fee_payer_lamports_pre = 10_000_000_000

    pre = {
        str(FEE_PAYER.pubkey()): AccountSnapshot(
            address=str(FEE_PAYER.pubkey()),
            exists=True,
            owner_program=_SYSTEM_PROGRAM_ID,
            lamports=fee_payer_lamports_pre,
            data=b"",
        ),
        str(INPUT_ATA): AccountSnapshot(
            address=str(INPUT_ATA),
            exists=True,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            lamports=2_039_280,
            data=_encode_token_account(mint=INPUT_MINT, owner=FEE_PAYER.pubkey(), amount=1_000_000),
        ),
        str(OUTPUT_ATA): AccountSnapshot(
            address=str(OUTPUT_ATA),
            exists=True,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            lamports=2_039_280,
            data=_encode_token_account(mint=OUTPUT_MINT, owner=FEE_PAYER.pubkey(), amount=0),
        ),
        str(AMM_VAULT): AccountSnapshot(
            address=str(AMM_VAULT),
            exists=True,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            lamports=2_039_280,
            data=_encode_token_account(mint=OUTPUT_MINT, owner=AMM_AUTHORITY, amount=5_000_000),
        ),
    }
    post = {
        str(FEE_PAYER.pubkey()): AccountSnapshot(
            address=str(FEE_PAYER.pubkey()),
            exists=True,
            owner_program=_SYSTEM_PROGRAM_ID,
            lamports=fee_payer_lamports_pre - fee_lamports,
            data=b"",
        ),
        str(INPUT_ATA): AccountSnapshot(
            address=str(INPUT_ATA),
            exists=True,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            lamports=2_039_280,
            data=_encode_token_account(mint=INPUT_MINT, owner=FEE_PAYER.pubkey(), amount=0),
        ),
        str(OUTPUT_ATA): AccountSnapshot(
            address=str(OUTPUT_ATA),
            exists=True,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            lamports=2_039_280,
            data=_encode_token_account(mint=OUTPUT_MINT, owner=FEE_PAYER.pubkey(), amount=950_000),
        ),
        str(AMM_VAULT): AccountSnapshot(
            address=str(AMM_VAULT),
            exists=True,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            lamports=2_039_280,
            data=_encode_token_account(mint=OUTPUT_MINT, owner=AMM_AUTHORITY, amount=4_050_000),
        ),
    }
    return unsigned_b64, pre, post


def test_unsigned_transaction_account_keys_includes_fee_payer_first() -> None:
    unsigned_b64, _, _ = _base_simulation()
    keys = unsigned_transaction_account_keys(unsigned_b64)
    assert keys[0] == str(FEE_PAYER.pubkey())
    assert unsigned_transaction_fee_payer(unsigned_b64) == str(FEE_PAYER.pubkey())


def test_deserialize_recovers_real_mints_amounts_and_fee_from_simulation() -> None:
    unsigned_b64, pre, post = _base_simulation()
    simulation = SimulationResult(err=None, pre_accounts=pre, post_accounts=post)

    shape = deserialize_unsigned_transaction_shape(
        unsigned_b64,
        simulation=simulation,
        executor_wallet_public_key=str(FEE_PAYER.pubkey()),
        expected_input_mint=str(INPUT_MINT),
        expected_output_mint=str(OUTPUT_MINT),
    )

    assert shape.signer_public_key == str(FEE_PAYER.pubkey())
    assert shape.fee_payer_public_key == str(FEE_PAYER.pubkey())
    assert shape.input_mint == str(INPUT_MINT)
    assert shape.output_mint == str(OUTPUT_MINT)
    assert shape.input_amount_raw == 1_000_000
    assert shape.total_fee_raw == 5_000
    assert shape.user_controlled_outflow_mints == frozenset({str(INPUT_MINT)})
    assert shape.simulated is True
    assert shape.simulated_balance_changes_explained is True
    assert shape.unexplained_authority_behavior is False


def test_deserialize_flags_unexplained_behavior_on_simulation_error() -> None:
    unsigned_b64, pre, post = _base_simulation()
    simulation = SimulationResult(
        err={"InstructionError": [0, "Custom"]}, pre_accounts=pre, post_accounts=post
    )

    shape = deserialize_unsigned_transaction_shape(
        unsigned_b64,
        simulation=simulation,
        executor_wallet_public_key=str(FEE_PAYER.pubkey()),
        expected_input_mint=str(INPUT_MINT),
        expected_output_mint=str(OUTPUT_MINT),
    )

    assert shape.unexplained_authority_behavior is True
    assert shape.simulated_balance_changes_explained is False


def test_deserialize_flags_unexplained_behavior_on_undecodable_token_account() -> None:
    unsigned_b64, pre, post = _base_simulation()
    # Corrupt the output ATA's post-state so it no longer decodes as a
    # valid 165-byte SPL Token account -- must fail closed, never guess.
    post = dict(post)
    post[str(OUTPUT_ATA)] = AccountSnapshot(
        address=str(OUTPUT_ATA),
        exists=True,
        owner_program=SPL_TOKEN_PROGRAM_ID,
        lamports=1,
        data=b"\x00" * 10,
    )
    simulation = SimulationResult(err=None, pre_accounts=pre, post_accounts=post)

    shape = deserialize_unsigned_transaction_shape(
        unsigned_b64,
        simulation=simulation,
        executor_wallet_public_key=str(FEE_PAYER.pubkey()),
        expected_input_mint=str(INPUT_MINT),
        expected_output_mint=str(OUTPUT_MINT),
    )

    assert shape.unexplained_authority_behavior is True
    assert shape.simulated_balance_changes_explained is False


def test_deserialize_captures_unexpected_outflow_mint() -> None:
    unsigned_b64, pre, post = _base_simulation()
    surprise_mint = Pubkey.new_unique()
    surprise_account = str(Pubkey.new_unique())
    pre = dict(pre)
    post = dict(post)
    pre[surprise_account] = AccountSnapshot(
        address=surprise_account,
        exists=True,
        owner_program=SPL_TOKEN_PROGRAM_ID,
        lamports=2_039_280,
        data=_encode_token_account(mint=surprise_mint, owner=FEE_PAYER.pubkey(), amount=500),
    )
    post[surprise_account] = AccountSnapshot(
        address=surprise_account,
        exists=True,
        owner_program=SPL_TOKEN_PROGRAM_ID,
        lamports=2_039_280,
        data=_encode_token_account(mint=surprise_mint, owner=FEE_PAYER.pubkey(), amount=0),
    )
    simulation = SimulationResult(err=None, pre_accounts=pre, post_accounts=post)

    shape = deserialize_unsigned_transaction_shape(
        unsigned_b64,
        simulation=simulation,
        executor_wallet_public_key=str(FEE_PAYER.pubkey()),
        expected_input_mint=str(INPUT_MINT),
        expected_output_mint=str(OUTPUT_MINT),
    )

    assert str(surprise_mint) in shape.user_controlled_outflow_mints
    assert shape.user_controlled_outflow_mints - {str(INPUT_MINT)} == {str(surprise_mint)}
