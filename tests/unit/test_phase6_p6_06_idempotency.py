"""P6-06 (SPEC_BLOCKING): idempotency fingerprint -- MASTER_SPEC.md
section 77 (EXECUTION IDEMPOTENCY), orchestrator instruction
``argus-phase-6-001``.

The fingerprint is a deterministic function of one semantic intent's
identity: identical inputs always produce the identical fingerprint
(replay-safe), and any single differing field always produces a
different fingerprint (no accidental collision between distinct
intents). The database-level "one row per fingerprint" and
"crash-after-submit/restart" halves of this row are covered by the
DB-gated integration test in
``tests/integration/test_phase6_persistence_and_concurrency.py``.
"""

from __future__ import annotations

import uuid

from argus.executor.idempotency import compute_idempotency_fingerprint

_BASE_KWARGS: dict = {
    "prospective_event_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
    "strategy_version": "copy_v1",
    "token_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
    "side": "BUY",
    "quote_mint": "So11111111111111111111111111111111111111112",
    "notional_input_raw": 1_000_000,
}


def test_identical_inputs_produce_identical_fingerprint() -> None:
    a = compute_idempotency_fingerprint(**_BASE_KWARGS)
    b = compute_idempotency_fingerprint(**_BASE_KWARGS)
    assert a == b


def test_fingerprint_is_a_64_character_hex_sha256_digest() -> None:
    fingerprint = compute_idempotency_fingerprint(**_BASE_KWARGS)
    assert len(fingerprint) == 64
    int(fingerprint, 16)  # raises ValueError if not valid hex


def test_none_prospective_event_id_is_handled_deterministically() -> None:
    kwargs = dict(_BASE_KWARGS, prospective_event_id=None)
    a = compute_idempotency_fingerprint(**kwargs)
    b = compute_idempotency_fingerprint(**kwargs)
    assert a == b
    assert a != compute_idempotency_fingerprint(**_BASE_KWARGS)


def test_different_strategy_version_changes_fingerprint() -> None:
    a = compute_idempotency_fingerprint(**_BASE_KWARGS)
    b = compute_idempotency_fingerprint(**dict(_BASE_KWARGS, strategy_version="copy_v2"))
    assert a != b


def test_different_token_id_changes_fingerprint() -> None:
    a = compute_idempotency_fingerprint(**_BASE_KWARGS)
    b = compute_idempotency_fingerprint(
        **dict(_BASE_KWARGS, token_id=uuid.UUID("33333333-3333-3333-3333-333333333333"))
    )
    assert a != b


def test_different_side_changes_fingerprint() -> None:
    a = compute_idempotency_fingerprint(**_BASE_KWARGS)
    b = compute_idempotency_fingerprint(**dict(_BASE_KWARGS, side="SELL"))
    assert a != b


def test_different_quote_mint_changes_fingerprint() -> None:
    a = compute_idempotency_fingerprint(**_BASE_KWARGS)
    b = compute_idempotency_fingerprint(
        **dict(_BASE_KWARGS, quote_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    )
    assert a != b


def test_different_notional_changes_fingerprint() -> None:
    a = compute_idempotency_fingerprint(**_BASE_KWARGS)
    b = compute_idempotency_fingerprint(**dict(_BASE_KWARGS, notional_input_raw=2_000_000))
    assert a != b
