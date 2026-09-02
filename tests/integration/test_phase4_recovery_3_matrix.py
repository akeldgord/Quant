"""argus-phase-4-recovery-003 -- TC-01 through TC-06, the frozen test-only
completion matrix an independent audit (embedded in
`orchestration/ORCHESTRATOR_INSTRUCTIONS.md` as `argus-phase-4-recovery-
003`) required after finding recovery-002's own submitted tests narrower
than the coverage AM-01/02/03/04/08/09/10 actually demanded (COV-01).

This is a TEST-ONLY completion: F-01 and F-02 (`src/argus/shadow/
quote_jobs.py`) are NOT touched here -- both were independently confirmed
already correct by the recovery-003 audit itself, based on a fresh scratch
harness driving the exact same common executor these tests use. This file
only supplies the missing worker/persistence/reload proof the frozen
matrix explicitly required, at the SAME production seam every other Phase
4 test file drives: a real `JupiterClient` over `httpx.MockTransport`, the
real `_execute_and_record_probe` common executor (permitted directly by
recovery-002's own "production callers or the unchanged common seam are
both acceptable" clause, reused verbatim by recovery-003), and genuine
persisted `ShadowQuoteProbe`/`ShadowPosition` rows on the existing
disposable PostgreSQL test database.

Reuses `tests/integration/test_phase4_recovery_2.py`'s own established
fixture/response-body helpers (`_sessionmaker`, `_cleanup_wallet`,
`_seed_intent_with_entry_probes`, `_valid_route_plan`,
`_jupiter_quote_body`, `_jupiter_client`, `_counting_handler`,
`_fill_entry_and_get_position`) exactly as recovery-003's own instruction
explicitly allows ("You may import/reuse existing recovery-002 test
helpers"), with a distinct wallet-address prefix (`P4R3`) so this file
never collides with any parallel test file sharing the same database.

Every TC row below claims exactly ONE probe by its own `probe_id` (never a
kind-wide claim), so the other 5 still-PENDING entry-delay probes a single
`_seed_intent_with_entry_probes` call schedules are never touched by this
file's own assertions -- "target probes by ID to avoid unrelated due
probes changing counts," per the frozen instruction.

argus-phase-4-recovery-005 (SEALED ACCEPTANCE CONTRACT, test-only, no
production code change) adds two frozen assertions on top of the existing
94-case inventory, both inside this same file:

- ASSERT-01: `_process_and_reprocess` (shared by TC-01/03/04, whose own
  outcomes are always non-SUCCESS) now also observes the scoped
  `ShadowQuoteProbe` row count (by the claimed probe's own parent --
  `shadow_intent_id` for ENTRY_DELAY, `shadow_position_id` for
  REVERSE_EXECUTABLE) and the seeded-wallet `ShadowPosition` count at
  three points -- before first execution, after the committed terminal
  result, and after the fresh-session repeat -- asserting all three are
  identical. Never applied to TC-02's own SUCCESS cases.
- ASSERT-02: TC-04's own 44 cases now wrap both executor calls (first +
  repeat, both inside `_process_and_reprocess`) in `caplog.at_level
  (logging.DEBUG)` and assert none of the injected inert unsafe
  sentinels, nor the unsafe `errorCode` value itself (raw or
  escaped-`repr()` form), ever appear in the captured formatted log text.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from argus.clock import Clock
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    OUTCOME_NO_ROUTE,
    OUTCOME_PROVIDER_CAPACITY_MISS,
    OUTCOME_QUOTE_FAILED,
    OUTCOME_SUCCESS,
    PROBE_KIND_ENTRY_DELAY,
    PROBE_KIND_REVERSE_EXECUTABLE,
    ShadowQuoteProbe,
)
from argus.shadow.quote_jobs import _claim_due_probes, _execute_and_record_probe
from tests.integration.test_phase4_recovery_2 import (
    _NOW,
    _cleanup_wallet,
    _counting_handler,
    _fill_entry_and_get_position,
    _jupiter_client,
    _jupiter_quote_body,
    _seed_intent_with_entry_probes,
    _sessionmaker,
    _valid_route_plan,
)

pytestmark = pytest.mark.asyncio


def _unique_wallet() -> str:
    return f"P4R3{uuid.uuid4().hex[:38]}"


def _unique_mint() -> str:
    return f"P4R3Mint{uuid.uuid4().hex[:30]}"


# ---------------------------------------------------------------------
# Shared seed/claim/process/reload helpers -- one narrow seam every TC
# row below drives, so the Cartesian coverage stays readable.
# ---------------------------------------------------------------------


async def _seed_and_claim_entry(sessionmaker, config):
    """Seeds one tracked wallet's real buy swap + monitoring pass (6 due
    ENTRY_DELAY probes), then claims exactly ONE of them by its own
    probe_id/generation -- the other 5 stay untouched PENDING rows.
    Returns (wallet_address, wallet_id, shadow_intent_id,
    shadow_position_id[always None here], probe_id, generation)."""
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    intent = await _seed_intent_with_entry_probes(
        sessionmaker, config, wallet_address=wallet_address, mint=mint
    )
    far_future = _NOW + timedelta(seconds=400)
    async with sessionmaker() as session, session.begin():
        claimed = await _claim_due_probes(
            session,
            probe_kind=PROBE_KIND_ENTRY_DELAY,
            now=far_future,
            worker_id="tc-entry-worker",
            stale_after=timedelta(seconds=30),
            limit=1,
        )
    assert len(claimed) == 1
    probe_id, generation = claimed[0]
    return wallet_address, intent.wallet_id, intent.shadow_intent_id, None, probe_id, generation


async def _seed_and_claim_reverse(sessionmaker, config):
    """Fills a real entry probe (creating a real ShadowPosition with its
    own real scheduled REVERSE_EXECUTABLE probes via the actual
    production fill path), then claims exactly ONE reverse probe by its
    own probe_id/generation. Returns (wallet_address, wallet_id,
    shadow_intent_id[always None here], shadow_position_id, probe_id,
    generation)."""
    wallet_address = _unique_wallet()
    mint = _unique_mint()
    intent = await _seed_intent_with_entry_probes(
        sessionmaker, config, wallet_address=wallet_address, mint=mint
    )
    position = await _fill_entry_and_get_position(sessionmaker, config, intent)
    far_future = position.opened_at + timedelta(hours=25)
    async with sessionmaker() as session, session.begin():
        claimed = await _claim_due_probes(
            session,
            probe_kind=PROBE_KIND_REVERSE_EXECUTABLE,
            now=far_future,
            worker_id="tc-reverse-worker",
            stale_after=timedelta(seconds=30),
            limit=1,
        )
    assert len(claimed) == 1
    probe_id, generation = claimed[0]
    return (
        wallet_address,
        position.wallet_id,
        None,
        position.shadow_position_id,
        probe_id,
        generation,
    )


async def _seed_and_claim(sessionmaker, config, kind: str):
    if kind == PROBE_KIND_ENTRY_DELAY:
        return await _seed_and_claim_entry(sessionmaker, config)
    return await _seed_and_claim_reverse(sessionmaker, config)


async def _probe_route_identity(sessionmaker, probe_id: uuid.UUID) -> tuple[str, str, int]:
    async with sessionmaker() as session:
        probe = await session.get(ShadowQuoteProbe, probe_id)
        assert probe is not None
        return probe.input_mint, probe.output_mint, probe.notional_input_amount_raw


async def _position_count(sessionmaker, wallet_id: uuid.UUID) -> int:
    async with sessionmaker() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(ShadowPosition)
                .where(ShadowPosition.wallet_id == wallet_id)
            )
        ).scalar_one()


async def _scoped_probe_count(
    sessionmaker,
    *,
    shadow_intent_id: uuid.UUID | None,
    shadow_position_id: uuid.UUID | None,
) -> int:
    """ASSERT-01: the scoped ShadowQuoteProbe row count for exactly the
    claimed probe's own parent (its shadow_intent_id for ENTRY_DELAY, its
    shadow_position_id for REVERSE_EXECUTABLE) -- never an unrelated
    table-wide count."""
    assert (shadow_intent_id is None) != (shadow_position_id is None)
    async with sessionmaker() as session:
        condition = (
            ShadowQuoteProbe.shadow_intent_id == shadow_intent_id
            if shadow_intent_id is not None
            else ShadowQuoteProbe.shadow_position_id == shadow_position_id
        )
        return (
            await session.execute(
                select(func.count()).select_from(ShadowQuoteProbe).where(condition)
            )
        ).scalar_one()


def _snapshot(probe: ShadowQuoteProbe) -> dict[str, Any]:
    return {
        "probe_id": probe.probe_id,
        "outcome": probe.outcome,
        "requested_at": probe.requested_at,
        "responded_at": probe.responded_at,
        "terminal_at": probe.terminal_at,
        "failure_evidence": probe.failure_evidence,
        "expected_output_amount_raw": probe.expected_output_amount_raw,
        "route_present": probe.route_present,
        "claim_generation": probe.claim_generation,
    }


async def _process_and_reprocess(
    sessionmaker,
    config,
    probe_id: uuid.UUID,
    generation: int,
    respond: Callable[[httpx.Request], httpx.Response],
    *,
    wallet_id: uuid.UUID,
    shadow_intent_id: uuid.UUID | None,
    shadow_position_id: uuid.UUID | None,
) -> tuple[ShadowQuoteProbe, dict[str, Any]]:
    """Processes the claimed probe once via the real common executor,
    then -- WITHOUT closing the same provider/transport -- reloads the
    row in a fresh session/engine and reprocesses the SAME probe_id
    again (already-terminal short-circuit, per `_execute_and_record_
    probe`'s own first check). Asserts the complete persisted record is
    byte-for-byte identical before/after, and that the transport recorded
    exactly ONE call in total -- keeping the provider open across both
    calls so a genuine accidental second dispatch could never be masked
    by a closed-client exception.

    ASSERT-01 (argus-phase-4-recovery-005): also observes the scoped
    ShadowQuoteProbe count (by the claimed probe's own parent
    shadow_intent_id/shadow_position_id) and the seeded-wallet
    ShadowPosition count at three points -- before first execution, after
    the committed terminal result, and after the fresh-session repeat --
    and asserts all three observations are identical. Callers using this
    helper only ever reach non-SUCCESS terminal outcomes (TC-01/03/04),
    so this oracle is never applied to a TC-02 SUCCESS case."""
    before_probe_count = await _scoped_probe_count(
        sessionmaker, shadow_intent_id=shadow_intent_id, shadow_position_id=shadow_position_id
    )
    before_position_count = await _position_count(sessionmaker, wallet_id)

    handler = _counting_handler(respond)
    provider, http_client = _jupiter_client(handler)
    try:
        first = await _execute_and_record_probe(
            sessionmaker,
            probe_id=probe_id,
            provider=provider,
            config=config,
            clock=Clock(),
            _claim_generation=generation,
        )
        assert len(handler.calls) == 1  # type: ignore[attr-defined]

        after_first_probe_count = await _scoped_probe_count(
            sessionmaker, shadow_intent_id=shadow_intent_id, shadow_position_id=shadow_position_id
        )
        after_first_position_count = await _position_count(sessionmaker, wallet_id)
        assert after_first_probe_count == before_probe_count
        assert after_first_position_count == before_position_count

        config2, engine2, sessionmaker2 = _sessionmaker()
        try:
            async with sessionmaker2() as session:
                before = await session.get(ShadowQuoteProbe, probe_id)
                assert before is not None
                snapshot_before = _snapshot(before)

            # Repeat processing: terminal_at is already set, so this must
            # be an immediate idempotent no-op -- never a second dispatch.
            await _execute_and_record_probe(
                sessionmaker2,
                probe_id=probe_id,
                provider=provider,
                config=config2,
                clock=Clock(),
            )

            async with sessionmaker2() as session:
                after = await session.get(ShadowQuoteProbe, probe_id)
                assert after is not None
                snapshot_after = _snapshot(after)
        finally:
            await engine2.dispose()

        assert snapshot_after == snapshot_before
        assert len(handler.calls) == 1  # type: ignore[attr-defined]  # still exactly 1 -- no new HTTP request

        after_repeat_probe_count = await _scoped_probe_count(
            sessionmaker, shadow_intent_id=shadow_intent_id, shadow_position_id=shadow_position_id
        )
        after_repeat_position_count = await _position_count(sessionmaker, wallet_id)
        assert after_repeat_probe_count == before_probe_count
        assert after_repeat_position_count == before_position_count

        return first, snapshot_after
    finally:
        await http_client.aclose()


def _route_body(
    *,
    input_mint: str,
    output_mint: str,
    notional: int,
    route_plan_override: list[Any] | None = None,
) -> dict[str, Any]:
    return _jupiter_quote_body(
        input_mint=input_mint,
        output_mint=output_mint,
        in_amount=notional,
        out_amount=500_000,
        route_plan_override=route_plan_override,
    )


# =======================================================================
# TC-01 / AM-01,02,03 -- kind x nested field x malformed value (8 cases),
# each with the full reload/repeat identity proof.
# =======================================================================

_TC01_MALFORMED = [
    ("superscript_two", "²"),
    ("5000_ascii_digits", "1" * 5000),
]


@pytest.mark.parametrize("kind", [PROBE_KIND_ENTRY_DELAY, PROBE_KIND_REVERSE_EXECUTABLE])
@pytest.mark.parametrize("field", ["inAmount", "outAmount"])
@pytest.mark.parametrize(
    "malformed_id,malformed_value", _TC01_MALFORMED, ids=[m[0] for m in _TC01_MALFORMED]
)
async def test_tc01_malformed_nested_amount_terminal_no_route_and_reload_idempotent(
    admin_engine, kind: str, field: str, malformed_id: str, malformed_value: str
) -> None:
    config, engine, sessionmaker = _sessionmaker()
    wallet_address = None
    try:
        (
            wallet_address,
            wallet_id,
            shadow_intent_id,
            shadow_position_id,
            probe_id,
            generation,
        ) = await _seed_and_claim(sessionmaker, config, kind)
        input_mint, output_mint, notional = await _probe_route_identity(sessionmaker, probe_id)
        before_positions = await _position_count(sessionmaker, wallet_id)

        def respond(request: httpx.Request) -> httpx.Response:
            route_plan = _valid_route_plan(
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=notional,
                out_amount=500_000,
            )
            route_plan[0]["swapInfo"][field] = malformed_value
            return httpx.Response(
                200,
                json=_route_body(
                    input_mint=input_mint,
                    output_mint=output_mint,
                    notional=notional,
                    route_plan_override=route_plan,
                ),
            )

        first, _snapshot_after = await _process_and_reprocess(
            sessionmaker,
            config,
            probe_id,
            generation,
            respond,
            wallet_id=wallet_id,
            shadow_intent_id=shadow_intent_id,
            shadow_position_id=shadow_position_id,
        )

        assert first.outcome == OUTCOME_NO_ROUTE
        assert first.requested_at is not None
        assert first.responded_at is not None
        assert first.terminal_at is not None
        assert first.requested_at <= first.responded_at <= first.terminal_at

        after_positions = await _position_count(sessionmaker, wallet_id)
        assert after_positions == before_positions
    finally:
        if wallet_address is not None:
            await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# =======================================================================
# TC-02 / AM-04 -- valid/invalid nested amount values through the common
# executor (entry kind only, per the frozen "no dual-kind duplication for
# this row" allowance). No reload requirement for valid values.
# =======================================================================

_TC02_VALID = [
    ("str_1", "1"),
    ("str_001_leading_zero", "001"),
    ("int_1", 1),
]

_TC02_INVALID = [
    ("empty_string", ""),
    ("ascii_garbage", "garbage"),
    ("str_zero", "0"),
    ("int_zero", 0),
    ("str_negative", "-1"),
    ("int_negative", -1),
    ("bool_true", True),
    ("float", 1.5),
    ("none", None),
    ("non_ascii_digit", "²"),
]


@pytest.mark.parametrize("field", ["inAmount", "outAmount"])
@pytest.mark.parametrize("value_id,value", _TC02_VALID, ids=[v[0] for v in _TC02_VALID])
async def test_tc02_valid_nested_amount_via_common_executor_succeeds(
    admin_engine, field: str, value_id: str, value: object
) -> None:
    config, engine, sessionmaker = _sessionmaker()
    wallet_address = None
    try:
        (
            wallet_address,
            wallet_id,
            _shadow_intent_id,
            _shadow_position_id,
            probe_id,
            generation,
        ) = await _seed_and_claim(sessionmaker, config, PROBE_KIND_ENTRY_DELAY)
        input_mint, output_mint, notional = await _probe_route_identity(sessionmaker, probe_id)

        def respond(request: httpx.Request) -> httpx.Response:
            route_plan = _valid_route_plan(
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=notional,
                out_amount=500_000,
            )
            route_plan[0]["swapInfo"][field] = value
            return httpx.Response(
                200,
                json=_route_body(
                    input_mint=input_mint,
                    output_mint=output_mint,
                    notional=notional,
                    route_plan_override=route_plan,
                ),
            )

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)
        try:
            result = await _execute_and_record_probe(
                sessionmaker,
                probe_id=probe_id,
                provider=provider,
                config=config,
                clock=Clock(),
                _claim_generation=generation,
            )
        finally:
            await http_client.aclose()

        assert result.outcome == OUTCOME_SUCCESS
        assert result.route_present is True
        assert (await _position_count(sessionmaker, wallet_id)) == 1
    finally:
        if wallet_address is not None:
            await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


@pytest.mark.parametrize("field", ["inAmount", "outAmount"])
@pytest.mark.parametrize("value_id,value", _TC02_INVALID, ids=[v[0] for v in _TC02_INVALID])
async def test_tc02_invalid_nested_amount_via_common_executor_is_no_route_no_fill(
    admin_engine, field: str, value_id: str, value: object
) -> None:
    config, engine, sessionmaker = _sessionmaker()
    wallet_address = None
    try:
        (
            wallet_address,
            wallet_id,
            _shadow_intent_id,
            _shadow_position_id,
            probe_id,
            generation,
        ) = await _seed_and_claim(sessionmaker, config, PROBE_KIND_ENTRY_DELAY)
        input_mint, output_mint, notional = await _probe_route_identity(sessionmaker, probe_id)

        def respond(request: httpx.Request) -> httpx.Response:
            route_plan = _valid_route_plan(
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=notional,
                out_amount=500_000,
            )
            route_plan[0]["swapInfo"][field] = value
            return httpx.Response(
                200,
                json=_route_body(
                    input_mint=input_mint,
                    output_mint=output_mint,
                    notional=notional,
                    route_plan_override=route_plan,
                ),
            )

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)
        try:
            result = await _execute_and_record_probe(
                sessionmaker,
                probe_id=probe_id,
                provider=provider,
                config=config,
                clock=Clock(),
                _claim_generation=generation,
            )
        finally:
            await http_client.aclose()

        assert result.outcome == OUTCOME_NO_ROUTE
        assert result.expected_output_amount_raw is None
        assert (await _position_count(sessionmaker, wallet_id)) == 0
    finally:
        if wallet_address is not None:
            await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# =======================================================================
# TC-03 / AM-05,07,10 -- both kinds x 4 status/code combinations, each
# with the full reload/repeat identity proof.
# =======================================================================

_TC03_CASES = [
    (
        "429_known_code",
        429,
        {"errorCode": "AUDIT_RATE_LIMIT"},
        OUTCOME_PROVIDER_CAPACITY_MISS,
        {"http_status_code": 429, "provider_error_code": "AUDIT_RATE_LIMIT"},
    ),
    (
        "400_no_route_code",
        400,
        {"errorCode": "COULD_NOT_FIND_ANY_ROUTE"},
        OUTCOME_NO_ROUTE,
        {"http_status_code": 400, "provider_error_code": "COULD_NOT_FIND_ANY_ROUTE"},
    ),
    (
        "400_unknown_safe_code",
        400,
        {"errorCode": "UNKNOWN_SAFE_CODE"},
        OUTCOME_QUOTE_FAILED,
        {"http_status_code": 400, "provider_error_code": "UNKNOWN_SAFE_CODE"},
    ),
    (
        "429_no_route_shaped_code",
        429,
        {"errorCode": "COULD_NOT_FIND_ANY_ROUTE"},
        OUTCOME_PROVIDER_CAPACITY_MISS,
        {"http_status_code": 429, "provider_error_code": "COULD_NOT_FIND_ANY_ROUTE"},
    ),
]


@pytest.mark.parametrize("kind", [PROBE_KIND_ENTRY_DELAY, PROBE_KIND_REVERSE_EXECUTABLE])
@pytest.mark.parametrize(
    "case_id,status_code,body,expected_outcome,expected_evidence",
    _TC03_CASES,
    ids=[c[0] for c in _TC03_CASES],
)
async def test_tc03_status_and_code_mapping_worker_and_reload_idempotent(
    admin_engine,
    kind: str,
    case_id: str,
    status_code: int,
    body: dict[str, str],
    expected_outcome: str,
    expected_evidence: dict[str, Any],
) -> None:
    config, engine, sessionmaker = _sessionmaker()
    wallet_address = None
    try:
        (
            wallet_address,
            wallet_id,
            shadow_intent_id,
            shadow_position_id,
            probe_id,
            generation,
        ) = await _seed_and_claim(sessionmaker, config, kind)

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, json=body)

        first, _snapshot_after = await _process_and_reprocess(
            sessionmaker,
            config,
            probe_id,
            generation,
            respond,
            wallet_id=wallet_id,
            shadow_intent_id=shadow_intent_id,
            shadow_position_id=shadow_position_id,
        )

        assert first.outcome == expected_outcome
        assert first.failure_evidence == expected_evidence
    finally:
        if wallet_address is not None:
            await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# =======================================================================
# TC-04 / AM-08,10 -- both kinds x HTTP400/429 x 11 frozen unsafe codes,
# each with ignored fake-secret sibling fields/headers and the full
# reload/repeat identity proof.
# =======================================================================

_TC04_UNSAFE_CODES: list[tuple[str, object]] = [
    ("url_with_fake_key", "https://quote-api.jup.ag/v6/quote?api_key=AUDIT_ONLY_FAKE_SECRET"),
    ("bare_query_assignment", "api_key=AUDIT_ONLY_FAKE_SECRET"),
    ("embedded_newline", "CODE_WITH\nEMBEDDED\nNEWLINE"),
    ("embedded_control_char", "CODE_WITH\x00CONTROL"),
    ("json_body_shaped", '{"errorCode": "X"}'),
    ("empty_string", ""),
    ("129_ascii_letters", "A" * 129),
    ("bool", True),
    ("int", 123),
    ("dict", {"errorCode": "X"}),
    ("list", ["X"]),
]


@pytest.mark.parametrize("kind", [PROBE_KIND_ENTRY_DELAY, PROBE_KIND_REVERSE_EXECUTABLE])
@pytest.mark.parametrize("status_code", [400, 429])
@pytest.mark.parametrize(
    "code_id,unsafe_code", _TC04_UNSAFE_CODES, ids=[c[0] for c in _TC04_UNSAFE_CODES]
)
async def test_tc04_unsafe_provider_code_never_persisted_worker_and_reload_idempotent(
    admin_engine,
    caplog: pytest.LogCaptureFixture,
    kind: str,
    status_code: int,
    code_id: str,
    unsafe_code: object,
) -> None:
    config, engine, sessionmaker = _sessionmaker()
    wallet_address = None
    try:
        (
            wallet_address,
            wallet_id,
            shadow_intent_id,
            shadow_position_id,
            probe_id,
            generation,
        ) = await _seed_and_claim(sessionmaker, config, kind)

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code,
                json={
                    "errorCode": unsafe_code,
                    # Ignored fake-secret sibling fields -- never
                    # positively identified, never persisted.
                    "apiKeyUsed": "sk-live-should-never-be-stored",
                    "requestUrl": "https://quote-api.jup.ag/v6/quote?apiKey=SECRET",
                    "traceId": "trace-should-not-be-stored-either",
                },
                headers={
                    "X-Api-Key-Echo": "should-never-be-stored",
                    "Set-Cookie": "session=should-never-be-stored",
                },
            )

        # ASSERT-02 (argus-phase-4-recovery-005): capture DEBUG-and-above
        # logging around BOTH executor calls (first execution + fresh-
        # session repeat, both performed inside _process_and_reprocess)
        # and assert none of the injected inert unsafe sentinels or the
        # unsafe error-code value itself (raw or escaped-repr form) ever
        # appear in the captured formatted log output.
        with caplog.at_level(logging.DEBUG):
            first, snapshot_after = await _process_and_reprocess(
                sessionmaker,
                config,
                probe_id,
                generation,
                respond,
                wallet_id=wallet_id,
                shadow_intent_id=shadow_intent_id,
                shadow_position_id=shadow_position_id,
            )
        captured_log_text = caplog.text

        expected_outcome = (
            OUTCOME_QUOTE_FAILED if status_code == 400 else OUTCOME_PROVIDER_CAPACITY_MISS
        )
        assert first.outcome == expected_outcome
        assert first.failure_evidence == {"http_status_code": status_code}

        serialized = str(snapshot_after["failure_evidence"])
        forbidden_values = [
            "sk-live-should-never-be-stored",
            "apiKey=SECRET",
            "trace-should-not-be-stored-either",
            "should-never-be-stored",
        ]
        if isinstance(unsafe_code, str) and unsafe_code:
            forbidden_values.append(unsafe_code)
            forbidden_values.append(repr(unsafe_code))
        for forbidden in forbidden_values:
            assert forbidden not in serialized
            assert forbidden not in captured_log_text
    finally:
        if wallet_address is not None:
            await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()


# =======================================================================
# TC-05 / AM-09 -- identifier boundary (entry kind only, common-seam
# exemption), HTTP400/429.
# =======================================================================

_TC05_CODES: list[tuple[str, str, bool]] = [
    ("1_char", "A", True),
    ("128_chars", "A" * 128, True),
    ("unknown_digits_underscore", "a1_b2_C3", True),
    ("129_chars_rejected", "A" * 129, False),
]


@pytest.mark.parametrize("status_code", [400, 429])
@pytest.mark.parametrize(
    "code_id,code,expect_preserved", _TC05_CODES, ids=[c[0] for c in _TC05_CODES]
)
async def test_tc05_identifier_boundary_worker(
    admin_engine, status_code: int, code_id: str, code: str, expect_preserved: bool
) -> None:
    config, engine, sessionmaker = _sessionmaker()
    wallet_address = None
    try:
        (
            wallet_address,
            _wallet_id,
            _shadow_intent_id,
            _shadow_position_id,
            probe_id,
            generation,
        ) = await _seed_and_claim(sessionmaker, config, PROBE_KIND_ENTRY_DELAY)

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, json={"errorCode": code})

        handler = _counting_handler(respond)
        provider, http_client = _jupiter_client(handler)
        try:
            result = await _execute_and_record_probe(
                sessionmaker,
                probe_id=probe_id,
                provider=provider,
                config=config,
                clock=Clock(),
                _claim_generation=generation,
            )
        finally:
            await http_client.aclose()

        expected_outcome = (
            OUTCOME_PROVIDER_CAPACITY_MISS if status_code == 429 else OUTCOME_QUOTE_FAILED
        )
        # A 400 with the known no-route code is the one exception; none
        # of TC-05's own codes equal it, so plain QUOTE_FAILED/capacity
        # miss always applies here.
        assert result.outcome == expected_outcome
        if expect_preserved:
            assert result.failure_evidence == {
                "http_status_code": status_code,
                "provider_error_code": code,
            }
        else:
            assert result.failure_evidence == {"http_status_code": status_code}
    finally:
        if wallet_address is not None:
            await _cleanup_wallet(admin_engine, wallet_address)
        await engine.dispose()
