"""argus.executor.attestation — MASTER_SPEC.md section 78 (TRANSACTION
ATTESTATION BEFORE SIGNING), Phase 6 (``argus-phase-6-001``).

The executor must not sign a provider-supplied transaction merely
because it came from a provider. :func:`attest_transaction` checks
every one of section 78's verification dimensions against a typed,
already-deserialized transaction shape (:class:`UnsignedTransactionShape`
-- a real byte-level deserializer is a separate concern this frozen
scope does not require building, since attestation itself only needs
the already-parsed fields) and returns one dimension result per check.
The signer (``argus.executor.signing.Signer``) is never called unless
every dimension is ``PASS``.
"""

from __future__ import annotations

from dataclasses import dataclass

DIMENSION_SIGNER = "signer_identity"
DIMENSION_WALLET = "executor_wallet_identity"
DIMENSION_INPUT_MINT = "input_mint"
DIMENSION_OUTPUT_MINT = "output_mint"
DIMENSION_AMOUNT = "intended_amount"
DIMENSION_OUTFLOWS = "user_controlled_outflows"
DIMENSION_FEES = "fees_tips_rent_ceiling"
DIMENSION_SIMULATION = "simulated_balance_changes"

ALL_DIMENSIONS: tuple[str, ...] = (
    DIMENSION_SIGNER,
    DIMENSION_WALLET,
    DIMENSION_INPUT_MINT,
    DIMENSION_OUTPUT_MINT,
    DIMENSION_AMOUNT,
    DIMENSION_OUTFLOWS,
    DIMENSION_FEES,
    DIMENSION_SIMULATION,
)


@dataclass(frozen=True)
class ExpectedTransactionShape:
    """What the executor itself intended, computed independently of the
    provider's response -- never trusted blindly."""

    expected_signer_public_key: str
    executor_wallet_public_key: str
    input_mint: str
    output_mint: str
    intended_input_amount_raw: int
    max_total_fee_raw: int  # network fee + priority fee + tip + rent, combined ceiling


@dataclass(frozen=True)
class UnsignedTransactionShape:
    """A typed, ALREADY-DESERIALIZED unsigned-transaction fixture --
    tests construct this directly, matching the frozen contract's own
    "table-driven fake unsigned-transaction fixtures" requirement."""

    signer_public_key: str
    fee_payer_public_key: str
    input_mint: str
    output_mint: str
    input_amount_raw: int
    total_fee_raw: int
    user_controlled_outflow_mints: frozenset[str]
    simulated: bool
    simulated_balance_changes_explained: bool
    unexplained_authority_behavior: bool


@dataclass(frozen=True)
class DimensionResult:
    dimension: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class AttestationResult:
    dimension_results: tuple[DimensionResult, ...]

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.dimension_results)

    @property
    def failed_dimensions(self) -> tuple[str, ...]:
        return tuple(r.dimension for r in self.dimension_results if not r.passed)


def attest_transaction(
    tx: UnsignedTransactionShape, expected: ExpectedTransactionShape
) -> AttestationResult:
    results: list[DimensionResult] = []

    results.append(
        DimensionResult(
            DIMENSION_SIGNER,
            tx.signer_public_key == expected.expected_signer_public_key,
            f"signer={tx.signer_public_key!r} expected={expected.expected_signer_public_key!r}",
        )
    )
    results.append(
        DimensionResult(
            DIMENSION_WALLET,
            tx.fee_payer_public_key == expected.executor_wallet_public_key,
            f"fee_payer={tx.fee_payer_public_key!r} "
            f"expected={expected.executor_wallet_public_key!r}",
        )
    )
    results.append(
        DimensionResult(
            DIMENSION_INPUT_MINT,
            tx.input_mint == expected.input_mint,
            f"input_mint={tx.input_mint!r} expected={expected.input_mint!r}",
        )
    )
    results.append(
        DimensionResult(
            DIMENSION_OUTPUT_MINT,
            tx.output_mint == expected.output_mint,
            f"output_mint={tx.output_mint!r} expected={expected.output_mint!r}",
        )
    )
    results.append(
        DimensionResult(
            DIMENSION_AMOUNT,
            tx.input_amount_raw == expected.intended_input_amount_raw,
            f"input_amount_raw={tx.input_amount_raw} expected={expected.intended_input_amount_raw}",
        )
    )
    unexpected_outflows = tx.user_controlled_outflow_mints - {expected.input_mint}
    results.append(
        DimensionResult(
            DIMENSION_OUTFLOWS,
            not unexpected_outflows,
            f"unexpected_outflow_mints={sorted(unexpected_outflows)}",
        )
    )
    results.append(
        DimensionResult(
            DIMENSION_FEES,
            tx.total_fee_raw <= expected.max_total_fee_raw,
            f"total_fee_raw={tx.total_fee_raw} ceiling={expected.max_total_fee_raw}",
        )
    )
    simulation_ok = (
        tx.simulated
        and tx.simulated_balance_changes_explained
        and not tx.unexplained_authority_behavior
    )
    results.append(
        DimensionResult(
            DIMENSION_SIMULATION,
            simulation_ok,
            f"simulated={tx.simulated} "
            f"balance_changes_explained={tx.simulated_balance_changes_explained} "
            f"unexplained_authority_behavior={tx.unexplained_authority_behavior}",
        )
    )
    return AttestationResult(dimension_results=tuple(results))
