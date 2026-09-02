"""Scheduled quote-probe execution -- entry-delay (section 46) and
reverse-executable (section 47) -- with claim-based restart safety
(section 84: "kill shadow worker mid-job -> restart -> no duplicate
shadow trade").

Every probe follows the SAME three-step, independently-committing shape
``argus.wallets.archaeology.run_archaeology`` already established for
crash safety:

1. **claim** -- an atomic ``UPDATE ... WHERE claimed_at IS NULL OR
   claimed_at < staleness cutoff`` (``FOR UPDATE SKIP LOCKED``), committed
   alone, incrementing ``claim_generation`` (P4-R5). A worker that dies
   here leaves the row claimable again once its claim goes stale -- never
   silently lost, never double-claimed by a live concurrent worker.
2. **call the provider** -- deliberately OUTSIDE any open transaction
   (a real network round trip must never hold a DB transaction/lock
   open). ``requested_at``/``responded_at`` come from the injected
   :class:`~argus.clock.Clock`, taken immediately before/after the call,
   so actual latency is always the real measured gap -- never asserted
   ("Never claim a +1s quote if the call occurred +2.7s later," section
   46's own explicit rule). When a real ``PriorityScheduler`` is supplied
   (as the production CLI always does -- P4-R4), the call itself is
   submitted through it under this probe kind's own priority class
   (``P4_prospective_copyability_quote``/``P5_shadow_exit_quote``), so
   shadow-research quoting shares the SAME capacity/priority machinery
   that governs every other provider call in this project, and a
   scheduler-level drop is recorded as an honest
   ``PROVIDER_CAPACITY_MISS``, never a fabricated failure/success.
3. **record** -- one atomic transaction that re-reads the probe row
   ``FOR UPDATE`` and verifies the ``claim_generation`` this attempt
   itself observed during its own claim still matches (P4-R5): a worker
   whose claim went stale and was superseded by a fresh reclaim can never
   publish its own late result over the new attempt's, and two workers
   racing through this step can never both write -- Postgres row locking
   serializes them, and the loser (whichever reaches the lock second)
   finds ``responded_at``/generation already settled and quietly no-ops,
   discarding its own already-completed provider call. On a genuine new
   terminal write, this same transaction creates the ``ShadowPosition``
   (for an ``ENTRY_DELAY`` probe whose outcome is ``SUCCESS`` -- guarded
   by the position's own unique ``shadow_intent_id`` constraint, so even
   a genuine double-execution of this step can never create two
   positions for the same intent) and schedules its reverse-executable/
   mark probes, all together. A worker that dies after step 2 but before
   this commits simply leaves the probe claimed-but-unresponded; the next
   claim pass (after the staleness window) reclaims and re-attempts it --
   never resuming mid-write, since nothing was ever partially written.

P4-R4 remediation: real ``JupiterClient`` failures (an ``httpx.
HTTPStatusError`` from ``response.raise_for_status()``) are now classified
by inspecting the actual response body for Jupiter's own documented
``COULD_NOT_FIND_ANY_ROUTE`` error code (-> ``NO_ROUTE``) and HTTP 429 (->
``PROVIDER_CAPACITY_MISS``, a real rate-limit signal) -- previously ONLY
the fake-provider-only ``ShadowQuoteError`` subclasses were recognized, so
every real adapter failure collapsed into the generic ``QUOTE_FAILED``
catch-all regardless of its actual cause. Any other/unparseable HTTP
error, and any error this project cannot positively identify, remains the
honest ``QUOTE_FAILED`` -- never guessed further. ``_classify_quote`` now
also verifies the response's own ``inAmount`` echoes the exact requested
notional before trusting ``outAmount`` at all, and requires genuine,
non-empty ``routePlan`` evidence (never merely a positive ``outAmount``)
before ever reporting ``route_present=True``/``SUCCESS`` -- a malformed or
identity-mismatched response is an honest ``QUOTE_FAILED``, never a
fabricated success.

P4-remediation-002 R4: the mint-identity check now compares the response's
own ``inputMint``/``outputMint`` fields against the mints this call actually
requested -- never the caller-echoed labels on :class:`ExecutableQuote`,
which merely restate the request and cannot reveal a genuine provider-side
mint disagreement. Route-plan evidence must be structurally well-formed
(each entry a dict carrying its own ``swapInfo`` dict), not merely a
non-empty list -- ``routePlan=[null]`` is equivalent to no route. A price-
impact value that is *present but garbage* (non-numeric, NaN, infinite) is
now an honest ``QUOTE_FAILED``, distinct from a genuinely *absent* impact
field, which stays leniently ``None`` -- missing evidence is unknown,
supplied-but-untrustworthy evidence is a failure, never silently equated.
Jupiter's own ``platformFee.amount`` is now honestly parsed into
``fee_estimate_raw`` when present and well-formed, ``None`` otherwise --
never fabricated or summed across currencies. ``requested_at``/
``responded_at`` are now captured from inside the actually-dispatched
callable (so a scheduler queue wait before dispatch is correctly reflected
in ``scheduling_delay_seconds``, never conflated with post-dispatch network
latency), and both stay honestly ``None`` for a genuine scheduler-level
capacity drop that never reached the provider. A new ``terminal_at``
column, set on every terminal write regardless of dispatch, is now the
single source of truth for "is this probe done" across claim-candidate
filtering, no-fill/intent-finalization checks, and report windowing --
``responded_at`` alone is no longer assumed to be the only completion
proof.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import httpx
from sqlalchemy import or_, select

from argus.domain.shadow_intents import STATUS_FILLED, STATUS_NO_FILL, ShadowIntent
from argus.domain.shadow_mark_outcomes import OUTCOME_PENDING as MARK_OUTCOME_PENDING
from argus.domain.shadow_mark_outcomes import ShadowMarkOutcome
from argus.domain.shadow_positions import ShadowPosition
from argus.domain.shadow_quote_probes import (
    OUTCOME_INSUFFICIENT_LIQUIDITY,
    OUTCOME_NO_ROUTE,
    OUTCOME_PENDING,
    OUTCOME_PRICE_IMPACT_EXCESSIVE,
    OUTCOME_PROVIDER_CAPACITY_MISS,
    OUTCOME_QUOTE_FAILED,
    OUTCOME_SUCCESS,
    OUTCOME_TOKEN_RESTRICTED,
    PROBE_KIND_ENTRY_DELAY,
    PROBE_KIND_REVERSE_EXECUTABLE,
    ShadowQuoteProbe,
)
from argus.shadow.errors import (
    InsufficientLiquidityError,
    NoRouteError,
    ProviderCapacityMissError,
    TokenRestrictedError,
)
from argus.shadow.errors import ShadowQuoteError as _ShadowQuoteError
from argus.shadow.horizons import horizon_to_timedelta

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from argus.clock import Clock
    from argus.config import ArgusConfig
    from argus.providers import ExecutionProvider, MarketDataProvider
    from argus.providers.models import ExecutableQuote
    from argus.providers.scheduler import PriorityScheduler
    from argus.telegram.notifier import TelegramNotifier

ALGORITHM_VERSION: Final[str] = "shadow_quote_jobs_v2"

PRIORITY_CLASS_ENTRY_DELAY: Final[str] = "P4_prospective_copyability_quote"
PRIORITY_CLASS_REVERSE_EXECUTABLE: Final[str] = "P5_shadow_exit_quote"

_ERROR_OUTCOME_MAP: Final[dict[type[Exception], str]] = {
    NoRouteError: OUTCOME_NO_ROUTE,
    InsufficientLiquidityError: OUTCOME_INSUFFICIENT_LIQUIDITY,
    TokenRestrictedError: OUTCOME_TOKEN_RESTRICTED,
    ProviderCapacityMissError: OUTCOME_PROVIDER_CAPACITY_MISS,
}

# Jupiter's own documented v6 quote-endpoint error code for "no route
# exists at all" -- the ONE code this project positively recognizes from
# a real HTTP error body; any other/unparseable body stays the honest
# QUOTE_FAILED catch-all rather than a guessed mapping.
_JUPITER_NO_ROUTE_ERROR_CODE: Final[str] = "COULD_NOT_FIND_ANY_ROUTE"

_DEFAULT_MAX_PRICE_IMPACT_PCT: Final[Decimal] = Decimal("0.10")


class SimulatedWorkerCrash(RuntimeError):
    """Raised only when a caller explicitly requests a crash-injection
    point for a restart/idempotency test (section 84's own required
    test) -- never raised in normal operation."""


# P4-REC-03: the maximum length this project ever trusts a provider-
# supplied error-code STRING to be before treating it as unsafe-to-persist
# garbage (never a body, never a header, never a URL -- just this one
# short identifier field).
_MAX_SAFE_PROVIDER_CODE_LEN: Final[int] = 128

# F-02 (argus-phase-4-recovery-002): a genuine provider error-code
# identifier is a bounded ASCII grammar -- [A-Za-z][A-Za-z0-9_]{0,127} --
# never merely "the right length." A type/length-only check (the P4-REC-03
# original) let an unsafe-shaped string (a URL, a bare query assignment,
# embedded control characters, JSON-body-shaped text) through unchanged as
# long as it happened to fit the length bound. This is a format policy for
# identifiers, not a claim to detect every possible secret hidden in
# arbitrary text.
_SAFE_PROVIDER_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^[A-Za-z][A-Za-z0-9_]{{0,{_MAX_SAFE_PROVIDER_CODE_LEN - 1}}}$"
)


def _safe_provider_error_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if not _SAFE_PROVIDER_CODE_PATTERN.fullmatch(value):
        return None
    return value


def _classify_provider_exception(exc: Exception) -> tuple[str, dict | None]:
    """Maps ANY exception a real or fake execution provider (or the
    shared scheduler) can raise to the correct honest outcome -- never
    just the fake-provider-only :class:`ShadowQuoteError` family.

    P4-REC-03: also returns a small, bounded, already-sanitized
    failure-evidence dict alongside the outcome -- the caller persists
    this verbatim into ``ShadowQuoteProbe.failure_evidence``. Only ever
    carries a handful of positively-identified, safe-to-store scalar
    fields (an HTTP status code, a provider-supplied error-code STRING
    already used for classification above, a scheduler drop reason/
    priority class) -- never the raw response body, headers, or request
    URL, and never a fabricated/guessed mapping for an exception type this
    project cannot positively identify (``None`` in that case, honestly
    unavailable rather than invented)."""
    from argus.providers.scheduler import RequestDropped

    if isinstance(exc, RequestDropped):
        return OUTCOME_PROVIDER_CAPACITY_MISS, {
            "scheduler_drop_reason": exc.reason,
            "scheduler_priority_class": exc.priority_class,
        }
    if isinstance(exc, _ShadowQuoteError):
        return _ERROR_OUTCOME_MAP.get(type(exc), OUTCOME_QUOTE_FAILED), None
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        status_code = response.status_code
        # F-02: extract safe evidence BEFORE selecting the status-derived
        # outcome -- a parsing failure (invalid/non-object JSON) must never
        # erase the HTTP429 capacity classification, and a genuinely
        # supplied, safe errorCode must survive on 429 exactly like every
        # other status.
        try:
            body = response.json()
        except ValueError:
            body = None
        provider_code = (
            _safe_provider_error_code(body.get("errorCode")) if isinstance(body, dict) else None
        )
        evidence: dict = {"http_status_code": status_code}
        if provider_code is not None:
            evidence["provider_error_code"] = provider_code
        if status_code == 429:
            # HTTP429 always remains PROVIDER_CAPACITY_MISS, even when the
            # code is absent, malformed, or equals the known no-route
            # identifier -- 429 is a capacity signal, never re-mapped by
            # any code content.
            return OUTCOME_PROVIDER_CAPACITY_MISS, evidence
        if provider_code == _JUPITER_NO_ROUTE_ERROR_CODE:
            return OUTCOME_NO_ROUTE, evidence
        return OUTCOME_QUOTE_FAILED, evidence
    return OUTCOME_QUOTE_FAILED, None


def _is_positive_raw_amount(value: object) -> bool:
    """A genuine Jupiter v6 raw-amount field (``inAmount``/``outAmount``)
    is a decimal-digit string (or, defensively, a real ``int``) encoding a
    strictly positive integer -- never a bool (``isinstance(True, int)``
    is true in Python, but a bool is never a genuine raw-amount value),
    never a float, never a negative/zero placeholder, and never an
    unparseable string.

    F-01 (argus-phase-4-recovery-002): ``str.isdigit()`` alone is NOT
    sufficient -- it accepts non-ASCII Unicode "digit" characters (e.g.
    superscript-two ``"²"``) that ``int()`` cannot parse, and Python's
    own global integer-string-conversion length guard raises
    ``ValueError`` for an excessively long digit string. Both previously
    escaped this function uncaught, crashing the whole probe-processing
    call instead of producing an honest terminal non-success. ``isascii()``
    rejects non-ASCII digits outright (never needing the guard below for
    them); the ``try/except`` is defense-in-depth for the interpreter's
    own conversion-length limit, which this project never disables."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value > 0
    if isinstance(value, str):
        if not value or not value.isascii() or not value.isdigit():
            return False
        try:
            parsed = int(value)
        except (ValueError, OverflowError):
            return False
        return parsed > 0
    return False


def _is_nonempty_mint_string(value: object) -> bool:
    return isinstance(value, str) and len(value) > 0


def _is_structurally_valid_route_entry(entry: object) -> bool:
    """A genuine Jupiter v6 ``routePlan`` entry is an object carrying its
    own ``swapInfo`` object (never a bare ``null``/non-object placeholder)
    with the fields the existing quote contract actually requires per leg:
    nonempty string ``inputMint``/``outputMint`` and valid positive
    integer/raw-amount ``inAmount``/``outAmount`` strings
    (P4-REC-02/P4-remediation-audit-002 R4-V: a nonempty ``swapInfo``
    DICT is not itself route evidence -- ``swapInfo={}`` or a ``swapInfo``
    whose own required nested fields are missing, wrong-typed, or
    non-positive is exactly as invalid as no ``swapInfo`` at all). This
    checks the EXISTING quote contract's own per-leg shape, never demands
    new economic/semantic proof beyond it (P4-remediation-002 R4:
    "Nonempty list is not route validation... do not demand new economic/
    semantic proof beyond that contract" -- P4-REC-02 only deepens this
    same existing contract one level, from "swapInfo is a dict" to
    "swapInfo's own required fields are genuinely present and valid")."""
    if not isinstance(entry, dict):
        return False
    swap_info = entry.get("swapInfo")
    if not isinstance(swap_info, dict):
        return False
    return (
        _is_nonempty_mint_string(swap_info.get("inputMint"))
        and _is_nonempty_mint_string(swap_info.get("outputMint"))
        and _is_positive_raw_amount(swap_info.get("inAmount"))
        and _is_positive_raw_amount(swap_info.get("outAmount"))
    )


def _extract_fee_estimate_raw(quote_raw: dict) -> int | None:
    """Jupiter's own v6 ``platformFee`` field (``{"amount": "...",
    "feeBps": N}``), when present and structurally parseable, in the ONE
    fixed currency Jupiter itself always denominates it in -- never summed
    or converted across mints (P4-remediation-002 R4: "never add
    heterogeneous currencies"). Absent or malformed stays honestly
    unavailable (``None``), never fabricated."""
    platform_fee = quote_raw.get("platformFee")
    if not isinstance(platform_fee, dict):
        return None
    amount = platform_fee.get("amount")
    if amount is None:
        return None
    try:
        return int(amount)
    except (TypeError, ValueError):
        return None


def _classify_quote(
    quote_raw: dict,
    *,
    out_amount_raw: int,
    in_amount_raw: int,
    requested_notional_raw: int,
    requested_input_mint: str,
    requested_output_mint: str,
    config: ArgusConfig,
) -> tuple[str, Decimal | None, bool]:
    """Real Jupiter quotes always carry ``priceImpactPct``/``routePlan``;
    this project decides whether that impact is excessive (section 48),
    never Jupiter itself. A genuinely MISSING impact field is treated
    leniently (``None``, not excessive) -- an honestly-unknown impact is
    not the same claim as a known-excessive one. A SUPPLIED but malformed
    or nonfinite impact value, by contrast, is untrustworthy evidence and
    produces an explicit ``QUOTE_FAILED`` with no fill
    (P4-remediation-002 R4: "missing impact must remain explicit; never
    silently assert a known-safe value" is not the same rule as "a
    present-but-garbage value is silently ignored").

    P4-R4 (round 1): a response whose own echoed ``inAmount`` does not
    match the exact notional this probe requested is untrustworthy and is
    never used as a success, regardless of its ``outAmount``.

    P4-remediation-002 R4 (round 2): the response's own RAW
    ``inputMint``/``outputMint`` fields (never the caller-echoed labels
    :class:`~argus.providers.models.ExecutableQuote` puts on the object)
    must match what was actually requested -- a provider response for an
    unrelated mint pair is never a valid quote for THIS probe.
    ``route_present`` requires genuine, structurally valid ``routePlan``
    entries (each carrying its own ``swapInfo`` object) -- a nonempty list
    of ``null``/malformed placeholders is not route evidence, exactly like
    an empty list."""
    raw_input_mint = quote_raw.get("inputMint")
    raw_output_mint = quote_raw.get("outputMint")
    if raw_input_mint != requested_input_mint or raw_output_mint != requested_output_mint:
        return OUTCOME_QUOTE_FAILED, None, False

    if in_amount_raw != requested_notional_raw:
        return OUTCOME_QUOTE_FAILED, None, False

    raw_impact = quote_raw.get("priceImpactPct")
    price_impact: Decimal | None
    if raw_impact is None:
        price_impact = None
    else:
        try:
            price_impact = Decimal(str(raw_impact))
        except (ValueError, ArithmeticError):
            return OUTCOME_QUOTE_FAILED, None, False
        if not price_impact.is_finite():
            # Decimal("NaN")/Decimal("Infinity") parse without raising
            # (they are valid IEEE-754-style Decimal special values) but
            # are a genuinely SUPPLIED, malformed value -- untrustworthy
            # evidence, an honest QUOTE_FAILED, never silently dropped to
            # the "missing" leniency path.
            return OUTCOME_QUOTE_FAILED, None, False

    threshold = config.get("thresholds.max_price_impact_pct")
    max_impact = Decimal(str(threshold)) if threshold is not None else _DEFAULT_MAX_PRICE_IMPACT_PCT

    route_plan = quote_raw.get("routePlan")
    has_route_evidence = (
        isinstance(route_plan, list)
        and len(route_plan) > 0
        and all(_is_structurally_valid_route_entry(entry) for entry in route_plan)
    )
    if not has_route_evidence or out_amount_raw <= 0:
        return OUTCOME_NO_ROUTE, price_impact, False
    if price_impact is not None and price_impact > max_impact:
        return OUTCOME_PRICE_IMPACT_EXCESSIVE, price_impact, True
    return OUTCOME_SUCCESS, price_impact, True


async def _claim_due_probes(
    session: AsyncSession,
    *,
    probe_kind: str,
    now: datetime,
    worker_id: str,
    stale_after: timedelta,
    limit: int,
) -> list[tuple[uuid.UUID, int]]:
    stale_cutoff = now - stale_after
    candidates = (
        (
            await session.execute(
                select(ShadowQuoteProbe)
                .where(
                    ShadowQuoteProbe.probe_kind == probe_kind,
                    ShadowQuoteProbe.target_due_at <= now,
                    ShadowQuoteProbe.terminal_at.is_(None),
                    or_(
                        ShadowQuoteProbe.claimed_at.is_(None),
                        ShadowQuoteProbe.claimed_at < stale_cutoff,
                    ),
                )
                .order_by(ShadowQuoteProbe.target_due_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    claimed: list[tuple[uuid.UUID, int]] = []
    for probe in candidates:
        probe.claimed_at = now
        probe.claimed_by = worker_id
        probe.claim_generation += 1
        claimed.append((probe.probe_id, probe.claim_generation))
    await session.flush()
    return claimed


async def _maybe_finalize_intent_no_fill(
    session: AsyncSession, *, shadow_intent_id: uuid.UUID
) -> None:
    entry_probes = (
        (
            await session.execute(
                select(ShadowQuoteProbe).where(
                    ShadowQuoteProbe.shadow_intent_id == shadow_intent_id,
                    ShadowQuoteProbe.probe_kind == PROBE_KIND_ENTRY_DELAY,
                )
            )
        )
        .scalars()
        .all()
    )
    if not entry_probes or any(p.terminal_at is None for p in entry_probes):
        return
    if any(p.outcome == OUTCOME_SUCCESS for p in entry_probes):
        return
    existing_position = (
        await session.execute(
            select(ShadowPosition.shadow_position_id).where(
                ShadowPosition.shadow_intent_id == shadow_intent_id
            )
        )
    ).scalar_one_or_none()
    if existing_position is not None:
        return
    intent = await session.get(ShadowIntent, shadow_intent_id)
    if intent is not None and intent.status != STATUS_NO_FILL:
        intent.status = STATUS_NO_FILL


async def schedule_reverse_probes_for_position(
    session: AsyncSession, *, position: ShadowPosition, config: ArgusConfig, opened_at: datetime
) -> list[ShadowQuoteProbe]:
    """Schedules the reverse-executable probes for a just-opened shadow
    position (section 47's own 5m/30m/1h/6h/24h horizons) plus its mark
    outcomes (section 47's descriptive-only mark family, 5m/30m/1h/6h/
    24h/3d/7d) -- called from the SAME atomic transaction that created
    ``position``, so a position is never left without its own scheduled
    follow-up probes."""
    reverse_horizons: Sequence[str] = config.get("executable_outcome_horizons") or [
        "5m",
        "30m",
        "1h",
        "6h",
        "24h",
    ]
    mark_horizons: Sequence[str] = config.get("mark_outcome_horizons") or [
        "5m",
        "30m",
        "1h",
        "6h",
        "24h",
        "3d",
        "7d",
    ]
    probes: list[ShadowQuoteProbe] = []
    for label in reverse_horizons:
        probe = ShadowQuoteProbe(
            probe_id=uuid.uuid4(),
            probe_kind=PROBE_KIND_REVERSE_EXECUTABLE,
            target_label=label,
            target_seconds_from_observation=None,
            shadow_intent_id=None,
            shadow_position_id=position.shadow_position_id,
            input_mint=position.output_mint,
            output_mint=position.input_mint,
            notional_input_amount_raw=position.entry_output_amount_raw,
            target_due_at=opened_at + horizon_to_timedelta(label),
            outcome=OUTCOME_PENDING,
            algorithm_version=ALGORITHM_VERSION,
            created_at=opened_at,
        )
        session.add(probe)
        probes.append(probe)
    for label in mark_horizons:
        mark = ShadowMarkOutcome(
            shadow_mark_outcome_id=uuid.uuid4(),
            shadow_position_id=position.shadow_position_id,
            horizon_label=label,
            due_at=opened_at + horizon_to_timedelta(label),
            outcome=MARK_OUTCOME_PENDING,
            algorithm_version=ALGORITHM_VERSION,
            created_at=opened_at,
        )
        session.add(mark)
    await session.flush()
    return probes


async def _notify_shadow_event(notifier: TelegramNotifier | None, *, text: str) -> None:
    """Best-effort only (P4-R6): a notification failure must never lose
    or roll back the real, already-committed trading-research record."""
    if notifier is None:
        return
    with contextlib.suppress(Exception):  # notification is never allowed to affect the record
        await notifier.notify(event_type="SHADOW_EVENT", text=text)


async def _execute_and_record_probe(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    probe_id: uuid.UUID,
    provider: ExecutionProvider,
    config: ArgusConfig,
    clock: Clock,
    market_provider: MarketDataProvider | None = None,
    scheduler: PriorityScheduler | None = None,
    priority_class: str | None = None,
    notifier: TelegramNotifier | None = None,
    _claim_generation: int | None = None,
    _simulate_crash_after: str | None = None,
) -> ShadowQuoteProbe:
    async with session_factory() as session:
        probe = await session.get(ShadowQuoteProbe, probe_id)
        assert probe is not None
        if probe.terminal_at is not None:
            # Already terminal -- a needless provider call must never
            # happen for an invocation that has nothing left to record
            # (P4-R5). ``terminal_at`` (never ``responded_at`` alone,
            # P4-remediation-002 R4) is the one true "is this probe done"
            # signal: a genuine scheduler-level capacity drop is terminal
            # with NO ``responded_at`` ever set at all. No lock is needed
            # to observe this: only a genuine NEW claim (a higher
            # claim_generation) can ever move a probe from terminal back
            # to claimable, and this call's own observed_generation was
            # captured at ITS claim time.
            return probe
        input_mint = probe.input_mint
        output_mint = probe.output_mint
        notional = probe.notional_input_amount_raw
        target_due_at = probe.target_due_at
        probe_kind = probe.probe_kind
        shadow_intent_id = probe.shadow_intent_id
        shadow_position_id = probe.shadow_position_id
        target_label = probe.target_label
        observed_generation = (
            _claim_generation if _claim_generation is not None else probe.claim_generation
        )

    # P4-remediation-002 R4: requested_at/responded_at are captured INSIDE
    # the dispatched callable itself, immediately before/after the actual
    # provider call -- never before scheduler.submit() is even invoked.
    # A scheduler queue wait is scheduling delay, not provider latency: if
    # the scheduler defers dispatch, requested_at correctly reflects the
    # real, later dispatch instant, not the earlier enqueue instant. A
    # request that is DROPPED before ever being dispatched (RequestDropped
    # raised by the scheduler itself, before _call_provider ever runs)
    # leaves both None -- no request/response ever genuinely happened.
    requested_at: datetime | None = None
    responded_at: datetime | None = None
    outcome = OUTCOME_QUOTE_FAILED
    expected_output: int | None = None
    price_impact: Decimal | None = None
    route_present = False
    fee_estimate: int | None = None
    raw_quote: dict | None = None
    failure_evidence: dict | None = None

    async def _call_provider() -> ExecutableQuote:
        nonlocal requested_at, responded_at
        requested_at = clock.utc_now()
        try:
            return await provider.get_quote(
                input_mint=input_mint, output_mint=output_mint, amount_raw=notional
            )
        finally:
            # Real dispatch happened (success OR a real provider-side
            # error like HTTP 429/no-route) -- both keep actual
            # send/response evidence, per P4-remediation-002 R4's own
            # "HTTP429 is different: it DID make a request" rule.
            responded_at = clock.utc_now()

    try:
        if scheduler is not None and priority_class is not None:
            quote = await scheduler.submit(priority_class, _call_provider)
        else:
            quote = await _call_provider()
    except Exception as exc:  # noqa: BLE001 -- classified below, never silently swallowed
        outcome, failure_evidence = _classify_provider_exception(exc)
    else:
        outcome, price_impact, route_present = _classify_quote(
            dict(quote.raw),
            out_amount_raw=quote.out_amount_raw,
            in_amount_raw=quote.in_amount_raw,
            requested_notional_raw=notional,
            requested_input_mint=input_mint,
            requested_output_mint=output_mint,
            config=config,
        )
        expected_output = (
            quote.out_amount_raw
            if outcome in (OUTCOME_SUCCESS, OUTCOME_PRICE_IMPACT_EXCESSIVE)
            else None
        )
        fee_estimate = _extract_fee_estimate_raw(dict(quote.raw))
        raw_quote = dict(quote.raw)
    terminal_at = clock.utc_now()
    scheduling_delay_seconds = (
        Decimal(str((requested_at - target_due_at).total_seconds()))
        if requested_at is not None
        else None
    )
    latency_ms = (
        int((responded_at - requested_at).total_seconds() * 1000)
        if requested_at is not None and responded_at is not None
        else None
    )

    entry_price_usd: Decimal | None = None
    if (
        probe_kind == PROBE_KIND_ENTRY_DELAY
        and outcome == OUTCOME_SUCCESS
        and market_provider is not None
    ):
        try:
            snapshot = await market_provider.token_snapshot(output_mint)
            entry_price_usd = snapshot.price_usd
        except Exception:  # noqa: BLE001 -- best-effort only; mark outcomes stay descriptive either way
            entry_price_usd = None

    if _simulate_crash_after == "quote":
        raise SimulatedWorkerCrash(f"simulated crash after quote call (probe_id={probe_id})")

    created_position = False
    async with session_factory() as session, session.begin():
        probe = (
            await session.execute(
                select(ShadowQuoteProbe)
                .where(ShadowQuoteProbe.probe_id == probe_id)
                .with_for_update()
            )
        ).scalar_one()
        if probe.terminal_at is not None or probe.claim_generation != observed_generation:
            # Already recorded by another worker/attempt, or this
            # attempt's own claim was superseded by a fresher reclaim --
            # idempotent no-op, never a second/late write (section 84,
            # P4-R5). ``terminal_at``, not ``responded_at`` alone
            # (P4-remediation-002 R4) -- a scheduler-drop terminal write
            # never sets ``responded_at`` at all. The provider call above
            # already happened and its result is simply discarded here.
            return probe

        probe.requested_at = requested_at
        probe.responded_at = responded_at
        probe.scheduling_delay_seconds = scheduling_delay_seconds
        probe.latency_ms = latency_ms
        probe.terminal_at = terminal_at
        probe.expected_output_amount_raw = expected_output
        probe.price_impact_pct = price_impact
        probe.route_present = route_present
        probe.fee_estimate_raw = fee_estimate
        probe.outcome = outcome
        probe.raw_quote = raw_quote
        probe.failure_evidence = failure_evidence

        if probe_kind == PROBE_KIND_ENTRY_DELAY:
            assert shadow_intent_id is not None
            if outcome == OUTCOME_SUCCESS:
                # Lock the parent intent FIRST (P4-R5): two different
                # entry-delay probes for the SAME intent can both resolve
                # SUCCESS and race to create the first ShadowPosition. An
                # unguarded check-then-insert here is a real check-then-
                # act race -- the loser's session.flush() below would
                # raise an unhandled IntegrityError on the position's own
                # unique shadow_intent_id constraint instead of being
                # absorbed. Locking the intent row makes the loser block
                # here until the winner's transaction commits, then its
                # own existing_position re-check (right after the lock is
                # granted) correctly finds the winner's already-created
                # row and skips creating a second one.
                intent = (
                    await session.execute(
                        select(ShadowIntent)
                        .where(ShadowIntent.shadow_intent_id == shadow_intent_id)
                        .with_for_update()
                    )
                ).scalar_one()
                existing_position = (
                    await session.execute(
                        select(ShadowPosition).where(
                            ShadowPosition.shadow_intent_id == shadow_intent_id
                        )
                    )
                ).scalar_one_or_none()
                if existing_position is None:
                    # SUCCESS is only ever reached after a real dispatch
                    # (the outcome starts as QUOTE_FAILED and is only
                    # changed once a provider call actually completed),
                    # so responded_at is always set here.
                    assert responded_at is not None
                    position = ShadowPosition(
                        shadow_position_id=uuid.uuid4(),
                        shadow_intent_id=shadow_intent_id,
                        wallet_id=intent.wallet_id,
                        token_id=intent.token_id,
                        input_mint=input_mint,
                        output_mint=output_mint,
                        entry_input_amount_raw=notional,
                        entry_output_amount_raw=expected_output or 0,
                        entry_price_impact_pct=price_impact,
                        entry_route_present=route_present,
                        entry_fee_estimate_raw=fee_estimate,
                        entry_price_usd=entry_price_usd,
                        entry_probe_target_label=target_label,
                        entry_requested_at=requested_at,
                        entry_responded_at=responded_at,
                        opened_at=responded_at,
                        algorithm_version=ALGORITHM_VERSION,
                        created_at=responded_at,
                    )
                    session.add(position)
                    intent.status = STATUS_FILLED
                    await session.flush()
                    await schedule_reverse_probes_for_position(
                        session, position=position, config=config, opened_at=responded_at
                    )
                    created_position = True
            else:
                await _maybe_finalize_intent_no_fill(session, shadow_intent_id=shadow_intent_id)
        else:
            assert shadow_position_id is not None

        await session.flush()

    if created_position:
        await _notify_shadow_event(
            notifier,
            text=(
                f"Shadow position opened for intent {shadow_intent_id}: "
                f"{input_mint} -> {output_mint}, probe {target_label}"
            ),
        )
    return probe


async def run_due_entry_probes(
    session_factory: async_sessionmaker[AsyncSession],
    provider: ExecutionProvider,
    *,
    config: ArgusConfig,
    clock: Clock,
    now: datetime,
    market_provider: MarketDataProvider | None = None,
    scheduler: PriorityScheduler | None = None,
    notifier: TelegramNotifier | None = None,
    worker_id: str = "entry-delay-worker",
    stale_after: timedelta = timedelta(seconds=30),
    limit: int = 50,
    _simulate_crash_after: str | None = None,
) -> list[ShadowQuoteProbe]:
    """Claims and executes every currently-due ``ENTRY_DELAY`` probe.
    Call repeatedly (a bounded loop, a cron tick, or a REPLAY step
    advancing a controlled clock) -- this function itself never sleeps
    or blocks waiting for a future due time. ``market_provider`` is
    optional and best-effort -- only used to capture a fill's entry
    market price for later mark-outcome computation (section 47); its
    absence or failure never blocks a shadow fill. ``scheduler``, when
    supplied, routes every quote call through the shared
    ``PriorityScheduler`` under ``P4_prospective_copyability_quote``
    (P4-R4) -- the production CLI always supplies one; tests may omit it
    to call the provider directly."""
    async with session_factory() as session, session.begin():
        claimed = await _claim_due_probes(
            session,
            probe_kind=PROBE_KIND_ENTRY_DELAY,
            now=now,
            worker_id=worker_id,
            stale_after=stale_after,
            limit=limit,
        )
    if _simulate_crash_after == "claim":
        raise SimulatedWorkerCrash("simulated crash after claim")

    results = []
    for probe_id, generation in claimed:
        results.append(
            await _execute_and_record_probe(
                session_factory,
                probe_id=probe_id,
                provider=provider,
                config=config,
                clock=clock,
                market_provider=market_provider,
                scheduler=scheduler,
                priority_class=PRIORITY_CLASS_ENTRY_DELAY,
                notifier=notifier,
                _claim_generation=generation,
                _simulate_crash_after=_simulate_crash_after,
            )
        )
    return results


async def run_due_reverse_probes(
    session_factory: async_sessionmaker[AsyncSession],
    provider: ExecutionProvider,
    *,
    config: ArgusConfig,
    clock: Clock,
    now: datetime,
    scheduler: PriorityScheduler | None = None,
    worker_id: str = "reverse-executable-worker",
    stale_after: timedelta = timedelta(seconds=30),
    limit: int = 50,
    _simulate_crash_after: str | None = None,
) -> list[ShadowQuoteProbe]:
    """Claims and executes every currently-due ``REVERSE_EXECUTABLE``
    probe -- same claim/execute/record shape as
    :func:`run_due_entry_probes`, routed through the shared scheduler
    under ``P5_shadow_exit_quote`` when supplied (P4-R4)."""
    async with session_factory() as session, session.begin():
        claimed = await _claim_due_probes(
            session,
            probe_kind=PROBE_KIND_REVERSE_EXECUTABLE,
            now=now,
            worker_id=worker_id,
            stale_after=stale_after,
            limit=limit,
        )
    if _simulate_crash_after == "claim":
        raise SimulatedWorkerCrash("simulated crash after claim")

    results = []
    for probe_id, generation in claimed:
        results.append(
            await _execute_and_record_probe(
                session_factory,
                probe_id=probe_id,
                provider=provider,
                config=config,
                clock=clock,
                scheduler=scheduler,
                priority_class=PRIORITY_CLASS_REVERSE_EXECUTABLE,
                _claim_generation=generation,
                _simulate_crash_after=_simulate_crash_after,
            )
        )
    return results
