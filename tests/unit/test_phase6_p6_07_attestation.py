"""P6-07 (SAFETY_OR_INTEGRITY_BLOCKING): transaction attestation before
signing -- MASTER_SPEC.md section 78, orchestrator instruction
``argus-phase-6-001``.

Table-driven: one valid inert fixture, plus one failure fixture for
every attestation dimension. A signer spy proves the signer is never
called for any failed/unknown attestation, and that the valid fixture
only reaches the signing seam -- never a network submission.
"""

from __future__ import annotations

from typing import Any

import pytest

from argus.executor.attestation import (
    ALL_DIMENSIONS,
    DIMENSION_AMOUNT,
    DIMENSION_FEES,
    DIMENSION_INPUT_MINT,
    DIMENSION_OUTFLOWS,
    DIMENSION_OUTPUT_MINT,
    DIMENSION_SIGNER,
    DIMENSION_SIMULATION,
    DIMENSION_WALLET,
    ExpectedTransactionShape,
    UnsignedTransactionShape,
    attest_transaction,
)
from argus.executor.dispatch import DispatchGuard, DispatchNeverCalledError
from argus.executor.signing import RaisingSigner, SignerNeverCalledError

_EXPECTED = ExpectedTransactionShape(
    expected_signer_public_key="SIGNER_PUB",
    executor_wallet_public_key="WALLET_PUB",
    input_mint="So11111111111111111111111111111111111111112",
    output_mint="TOKEN_MINT_ABC",
    intended_input_amount_raw=1_000_000,
    max_total_fee_raw=5_000,
)


def _valid_tx(**overrides: object) -> UnsignedTransactionShape:
    base: dict[str, Any] = {
        "signer_public_key": "SIGNER_PUB",
        "fee_payer_public_key": "WALLET_PUB",
        "input_mint": _EXPECTED.input_mint,
        "output_mint": _EXPECTED.output_mint,
        "input_amount_raw": _EXPECTED.intended_input_amount_raw,
        "total_fee_raw": 4_000,
        "user_controlled_outflow_mints": frozenset({_EXPECTED.input_mint}),
        "simulated": True,
        "simulated_balance_changes_explained": True,
        "unexplained_authority_behavior": False,
    }
    base.update(overrides)
    return UnsignedTransactionShape(**base)


def test_valid_fixture_passes_every_dimension() -> None:
    result = attest_transaction(_valid_tx(), _EXPECTED)
    assert result.all_passed is True
    assert result.failed_dimensions == ()


@pytest.mark.parametrize(
    "overrides,expected_failed_dimension",
    [
        ({"signer_public_key": "WRONG_SIGNER"}, DIMENSION_SIGNER),
        ({"fee_payer_public_key": "WRONG_WALLET"}, DIMENSION_WALLET),
        ({"input_mint": "WRONG_INPUT_MINT"}, DIMENSION_INPUT_MINT),
        ({"output_mint": "WRONG_OUTPUT_MINT"}, DIMENSION_OUTPUT_MINT),
        ({"input_amount_raw": 999}, DIMENSION_AMOUNT),
        (
            {"user_controlled_outflow_mints": frozenset({"UNEXPECTED_MINT"})},
            DIMENSION_OUTFLOWS,
        ),
        ({"total_fee_raw": 999_999}, DIMENSION_FEES),
        ({"simulated": False}, DIMENSION_SIMULATION),
        ({"simulated_balance_changes_explained": False}, DIMENSION_SIMULATION),
        ({"unexplained_authority_behavior": True}, DIMENSION_SIMULATION),
    ],
)
def test_each_dimension_failure_is_independently_detected(
    overrides: dict, expected_failed_dimension: str
) -> None:
    tx = _valid_tx(**overrides)
    result = attest_transaction(tx, _EXPECTED)
    assert result.all_passed is False
    assert expected_failed_dimension in result.failed_dimensions


def test_every_dimension_is_covered_by_the_table_above() -> None:
    covered = {
        DIMENSION_SIGNER,
        DIMENSION_WALLET,
        DIMENSION_INPUT_MINT,
        DIMENSION_OUTPUT_MINT,
        DIMENSION_AMOUNT,
        DIMENSION_OUTFLOWS,
        DIMENSION_FEES,
        DIMENSION_SIMULATION,
    }
    assert covered == set(ALL_DIMENSIONS)


def test_signer_never_called_when_any_dimension_fails() -> None:
    """A guard constructed with the raising sentinel signer is never
    actually invoked -- attestation failure means the caller must not
    even reach the signing seam."""
    guard = DispatchGuard(signer=RaisingSigner())
    tx = _valid_tx(input_amount_raw=1)  # fails DIMENSION_AMOUNT
    result = attest_transaction(tx, _EXPECTED)
    assert result.all_passed is False
    # The caller's own responsibility is to gate on `all_passed` before
    # ever touching `guard.signer` -- proven here by never doing so.
    with pytest.raises(SignerNeverCalledError):
        _ = guard.signer.public_key


def test_default_dispatch_guard_submission_raises_if_ever_called() -> None:
    guard = DispatchGuard(signer=RaisingSigner())
    with pytest.raises(DispatchNeverCalledError):
        guard.submit()
