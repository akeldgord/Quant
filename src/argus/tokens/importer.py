"""Deterministic bootstrap-token importer (MASTER_SPEC.md Phase 2 build
item 5; required-implementation item 2).

Creates (or reuses) a ``tokens`` row for a candidate mint address, then
runs on-chain mint validation (``argus.tokens.mint_validation``) and
records the attempt as an immutable ``token_mint_validations`` row. A
malformed, missing, wrong-owner, or unavailable-evidence mint still
produces a real, queryable ``tokens`` row (never silently dropped) --
only ``mint_validated`` differs. Once ``mint_validated`` is set ``True``
from a genuine ``VALID`` result it is never reset by a later attempt
(even an ``UNAVAILABLE`` one): a real validation is not erased by a
transient provider miss.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import select

from argus.domain.token_mint_validations import TokenMintValidation
from argus.domain.tokens import Token
from argus.tokens.mint_validation import (
    ALGORITHM_VERSION,
    BUILD_HASH,
    SOURCE_TOKEN_BALANCE_EVIDENCE,
    STATUS_UNAVAILABLE,
    STATUS_VALID,
    MintValidationResult,
    validate_from_account_info,
    validate_from_token_balance_evidence,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from argus.config import ArgusConfig

EvidenceKind = Literal["account_info", "token_balance"]


@dataclasses.dataclass(frozen=True, slots=True)
class TokenImportResult:
    token_id: uuid.UUID
    mint: str
    validation: MintValidationResult
    mint_validated: bool
    validation_id: uuid.UUID


async def _get_or_create_token(session: AsyncSession, *, mint: str, now: datetime) -> Token:
    existing = (await session.execute(select(Token).where(Token.mint == mint))).scalar_one_or_none()
    if existing is not None:
        return existing
    token = Token(
        token_id=uuid.uuid4(),
        mint=mint,
        chain="solana",
        first_observed_at=now,
        mint_validated=False,
        current_lifecycle_stage=None,
        created_at=now,
    )
    session.add(token)
    await session.flush()
    return token


async def import_bootstrap_token(
    session: AsyncSession,
    *,
    mint: str,
    evidence: dict[str, Any] | None,
    evidence_kind: EvidenceKind,
    evidence_reference: str,
    now: datetime,
    config: ArgusConfig,
    git_commit: str,
) -> TokenImportResult:
    """Import (or re-validate) one candidate token mint against real
    committed evidence. Idempotent on ``mint``: calling this twice for the
    same mint never creates a second ``tokens`` row, and always appends a
    new ``token_mint_validations`` attempt (the append-only ledger
    convention -- a later attempt never overwrites an earlier one)."""
    token = await _get_or_create_token(session, mint=mint, now=now)

    if evidence_kind == "account_info":
        result = validate_from_account_info(
            evidence, mint=mint, evidence_reference=evidence_reference
        )
    else:
        if evidence is None:
            result = MintValidationResult(
                STATUS_UNAVAILABLE,
                SOURCE_TOKEN_BALANCE_EVIDENCE,
                "no transaction evidence provided",
                None,
                None,
                evidence_reference,
            )
        else:
            result = validate_from_token_balance_evidence(
                evidence, mint=mint, evidence_reference=evidence_reference
            )

    validation = TokenMintValidation(
        validation_id=uuid.uuid4(),
        token_id=token.token_id,
        validation_status=result.status,
        validation_source=result.validation_source,
        observed_at=now,
        chain_time=None,
        commitment=None,
        evidence_reference=result.evidence_reference,
        reason=result.reason,
        algorithm_version=ALGORITHM_VERSION,
        build_hash=BUILD_HASH,
        config_hash=config.config_hash,
        master_spec_hash=config.spec_hash,
        git_commit=git_commit,
        created_at=now,
    )
    session.add(validation)

    if result.status == STATUS_VALID and not token.mint_validated:
        token.mint_validated = True

    await session.flush()

    return TokenImportResult(
        token_id=token.token_id,
        mint=mint,
        validation=result,
        mint_validated=token.mint_validated,
        validation_id=validation.validation_id,
    )
