"""argus.executor.idempotency — MASTER_SPEC.md section 77 (EXECUTION
IDEMPOTENCY), Phase 6 (``argus-phase-6-001``).

The idempotency fingerprint is a stable SHA-256 hex digest over the
exact identity of one semantic trade intent (signal, strategy version,
token, side, quote mint, notional). Two calls with the same identity
always produce the SAME fingerprint, and ``execution_intents``'s own
UNIQUE constraint on this column (migration ``0024``) is the database-
level backstop that makes inserting a duplicate intent structurally
impossible -- restart/replay can never execute the same intent twice.
"""

from __future__ import annotations

import hashlib
import uuid


def compute_idempotency_fingerprint(
    *,
    prospective_event_id: uuid.UUID | None,
    strategy_version: str,
    token_id: uuid.UUID,
    side: str,
    quote_mint: str,
    notional_input_raw: int,
) -> str:
    canonical = "|".join(
        [
            str(prospective_event_id) if prospective_event_id is not None else "NONE",
            strategy_version,
            str(token_id),
            side,
            quote_mint,
            str(notional_input_raw),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
