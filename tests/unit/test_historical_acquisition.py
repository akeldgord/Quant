"""Tests for argus.tokens.historical_acquisition (P2-R2 frozen
remediation acceptance test R2): the live, provider-neutral acquisition
path the pre-remediation Phase 2 build entirely lacked. Every fault this
module documents handling -- multiple pages, a duplicate item/page
(immediately-repeated cursor and a multi-step cursor cycle), a premature
short/empty page, safety-ceiling exhaustion, a provider-level timeout /
rate limit / malformed response, and a per-transaction fetch failure --
is proven here against a deterministic scripted fake provider (per
argus-phase-2-remediation-001's explicit "tests may use a deterministic
fake provider" allowance). No live credential, no network call, no paid
provider anywhere in this file.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from argus.providers import SignatureInfo
from argus.tokens.historical_acquisition import (
    DEFAULT_MAX_PAGES,
    DEFAULT_PAGE_SIZE,
    STATUS_COMPLETE,
    STATUS_PARTIAL,
    acquire_historical_transactions,
)

ADDRESS = "ScriptedAddress1111111111111111111111111111"


def _sig(signature: str, slot: int) -> SignatureInfo:
    return SignatureInfo(signature=signature, slot=slot, block_time=None, err=None)


def _tx(signature: str) -> dict[str, Any]:
    return {"transaction": {"signatures": [signature]}, "slot": 0, "meta": {"err": None}}


@dataclasses.dataclass
class ScriptedChainProvider:
    """A deterministic fake honoring only the two `ChainProvider` methods
    :func:`acquire_historical_transactions` actually calls. Pages are a
    plain call-index-ordered script (never derived from cursor value) so
    each test can inject exactly the fault it names -- including faults
    (a multi-step cursor cycle, a re-observed duplicate two pages later)
    that would be awkward to provoke from a cursor-honoring fake."""

    pages: list[list[SignatureInfo]] = dataclasses.field(default_factory=list)
    page_exceptions: dict[int, Exception] = dataclasses.field(default_factory=dict)
    transactions: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    tx_exceptions: dict[str, Exception] = dataclasses.field(default_factory=dict)
    calls: list[tuple[str | None, int]] = dataclasses.field(default_factory=list)
    tx_calls: list[str] = dataclasses.field(default_factory=list)
    # A per-call accounting log this fake maintains itself -- standing in for
    # a real ChainProvider implementation's own internal usage_recorder
    # (e.g. HeliusRpcClient's, already exhaustively tested in
    # test_provider_adapters.py). acquire_historical_transactions never
    # calls a usage recorder of its own (see the module's own docstring):
    # provider usage accounting is a property of *every* call this service
    # makes reaching the provider exactly once, which this log lets a test
    # verify directly.
    usage_log: list[str] = dataclasses.field(default_factory=list)

    async def get_signatures_for_address(
        self,
        wallet_address: str,
        *,
        until_signature: str | None = None,
        before_signature: str | None = None,
        limit: int = 1000,
    ) -> list[SignatureInfo]:
        call_index = len(self.calls)
        self.calls.append((before_signature, limit))
        self.usage_log.append(f"get_signatures_for_address#{call_index}")
        if call_index in self.page_exceptions:
            raise self.page_exceptions[call_index]
        if call_index >= len(self.pages):
            return []
        return self.pages[call_index]

    async def get_transaction(self, signature: str) -> dict[str, Any]:
        self.tx_calls.append(signature)
        self.usage_log.append(f"get_transaction:{signature}")
        if signature in self.tx_exceptions:
            raise self.tx_exceptions[signature]
        return self.transactions[signature]

    # The remaining ChainProvider protocol methods are structurally
    # required but never exercised by acquire_historical_transactions --
    # trivial stubs, never called in any test in this file.
    async def get_signature_statuses(self, signatures: list[str]) -> list[Any]:
        raise NotImplementedError

    async def get_balance(self, wallet_address: str) -> int:
        raise NotImplementedError

    async def get_token_accounts(self, wallet_address: str) -> list[Any]:
        raise NotImplementedError

    async def get_slot(self) -> int:
        raise NotImplementedError


class RateLimitError(Exception):
    pass


@pytest.mark.asyncio
async def test_multiple_full_pages_then_short_page_completes() -> None:
    provider = ScriptedChainProvider(
        pages=[
            [_sig("A", 30), _sig("B", 29)],
            [_sig("C", 28), _sig("D", 27)],
            [_sig("E", 26)],  # short (< page_size) -- reached genesis
        ],
        transactions={s: _tx(s) for s in "ABCDE"},
    )

    result = await acquire_historical_transactions(
        provider, address=ADDRESS, max_pages=10, page_size=2
    )

    assert result.status == STATUS_COMPLETE
    assert result.known_gaps is None
    assert result.pages_fetched == 3
    assert result.signatures_seen == 5
    assert [t.signature for t in result.transactions] == ["A", "B", "C", "D", "E"]
    assert result.transaction_fetch_failures == 0
    assert "complete" in result.completeness_statement.lower()


@pytest.mark.asyncio
async def test_empty_history_is_complete_with_zero_transactions() -> None:
    provider = ScriptedChainProvider(pages=[[]])

    result = await acquire_historical_transactions(provider, address=ADDRESS, page_size=100)

    assert result.status == STATUS_COMPLETE
    assert result.transactions == []
    assert result.pages_fetched == 1
    assert result.signatures_seen == 0


@pytest.mark.asyncio
async def test_immediately_repeated_cursor_duplicate_is_detected() -> None:
    # "B" is the last entry of page 0 and reappears as the first entry of
    # page 1 -- the classic off-by-one/immediately-repeated-cursor bug.
    provider = ScriptedChainProvider(
        pages=[
            [_sig("A", 20), _sig("B", 19)],
            [_sig("B", 19), _sig("C", 18)],
        ],
        transactions={s: _tx(s) for s in "ABC"},
    )

    result = await acquire_historical_transactions(
        provider, address=ADDRESS, max_pages=10, page_size=2
    )

    assert result.status == STATUS_PARTIAL
    assert result.known_gaps is not None
    assert "duplicate signature" in result.known_gaps
    assert "'B'" in result.known_gaps
    # The fault is detected mid-second-page: only A and B (page 1's first,
    # already-seen entry never gets appended twice) were collected.
    assert [t.signature for t in result.transactions] == ["A", "B"]


@pytest.mark.asyncio
async def test_multi_step_cursor_cycle_is_detected_by_the_same_check() -> None:
    # "A" reappears two pages later at a strictly-lower slot (so it does
    # NOT trip the ordering-fault check first) -- a multi-step cursor
    # cycle, caught by the same seen_signatures check as the immediate
    # case, per the module's own documented reasoning.
    provider = ScriptedChainProvider(
        pages=[
            [_sig("A", 10), _sig("B", 9), _sig("C", 8)],
            [_sig("D", 7), _sig("E", 6), _sig("H", 5)],
            [_sig("A", 4), _sig("F", 3)],
        ],
        transactions={s: _tx(s) for s in "ABCDEHF"},
    )

    result = await acquire_historical_transactions(
        provider, address=ADDRESS, max_pages=10, page_size=3
    )

    assert result.status == STATUS_PARTIAL
    assert result.known_gaps is not None
    assert "duplicate signature" in result.known_gaps
    assert "'A'" in result.known_gaps
    assert [t.signature for t in result.transactions] == list("ABCDEH")


@pytest.mark.asyncio
async def test_pagination_ordering_fault_is_detected() -> None:
    provider = ScriptedChainProvider(
        pages=[
            [_sig("A", 10), _sig("B", 9)],
            [_sig("C", 99)],  # newer slot than the prior observed slot 9
        ],
        transactions={s: _tx(s) for s in "ABC"},
    )

    result = await acquire_historical_transactions(
        provider, address=ADDRESS, max_pages=10, page_size=2
    )

    assert result.status == STATUS_PARTIAL
    assert result.known_gaps is not None
    assert "ordering fault" in result.known_gaps
    assert [t.signature for t in result.transactions] == ["A", "B"]


@pytest.mark.asyncio
async def test_safety_ceiling_exhaustion_reports_partial() -> None:
    # Every page is exactly page_size (never short), so the walk never
    # naturally completes -- max_pages must be the thing that stops it.
    provider = ScriptedChainProvider(
        pages=[[_sig(f"S{i}", 100 - i)] for i in range(5)],
        transactions={f"S{i}": _tx(f"S{i}") for i in range(5)},
    )

    result = await acquire_historical_transactions(
        provider, address=ADDRESS, max_pages=3, page_size=1
    )

    assert result.status == STATUS_PARTIAL
    assert result.known_gaps is not None
    assert "safety ceiling of 3 pages" in result.known_gaps
    assert result.pages_fetched == 3
    assert len(result.transactions) == 3


@pytest.mark.asyncio
async def test_provider_timeout_downgrades_to_partial_and_preserves_prior_pages() -> None:
    provider = ScriptedChainProvider(
        pages=[[_sig("A", 10)]],
        page_exceptions={1: TimeoutError("upstream RPC timed out")},
        transactions={"A": _tx("A")},
    )

    result = await acquire_historical_transactions(
        provider, address=ADDRESS, max_pages=10, page_size=1
    )

    assert result.status == STATUS_PARTIAL
    assert result.known_gaps is not None
    assert "TimeoutError" in result.known_gaps
    assert "upstream RPC timed out" in result.known_gaps
    assert [t.signature for t in result.transactions] == ["A"]


@pytest.mark.asyncio
async def test_provider_rate_limit_downgrades_to_partial() -> None:
    provider = ScriptedChainProvider(
        pages=[],
        page_exceptions={0: RateLimitError("429 rate limited")},
    )

    result = await acquire_historical_transactions(provider, address=ADDRESS, max_pages=5)

    assert result.status == STATUS_PARTIAL
    assert result.known_gaps is not None
    assert "RateLimitError" in result.known_gaps
    assert "429 rate limited" in result.known_gaps
    assert result.pages_fetched == 1
    assert result.transactions == []


@pytest.mark.asyncio
async def test_malformed_provider_response_downgrades_to_partial() -> None:
    provider = ScriptedChainProvider(
        pages=[],
        page_exceptions={0: ValueError("malformed JSON in getSignaturesForAddress response")},
    )

    result = await acquire_historical_transactions(provider, address=ADDRESS)

    assert result.status == STATUS_PARTIAL
    assert result.known_gaps is not None
    assert "ValueError" in result.known_gaps
    assert "malformed JSON" in result.known_gaps


@pytest.mark.asyncio
async def test_transaction_fetch_failure_is_partial_but_preserves_the_rest() -> None:
    provider = ScriptedChainProvider(
        pages=[[_sig("A", 3), _sig("B", 2), _sig("C", 1)]],
        transactions={"A": _tx("A"), "C": _tx("C")},
        tx_exceptions={"B": ConnectionError("connection reset fetching B")},
    )

    result = await acquire_historical_transactions(
        provider, address=ADDRESS, max_pages=10, page_size=10
    )

    # The listing itself was complete (a short/final page) -- only the
    # per-transaction fetch faulted, which alone must still downgrade the
    # overall result to PARTIAL rather than being silently absorbed.
    assert result.status == STATUS_PARTIAL
    assert result.transaction_fetch_failures == 1
    assert result.known_gaps is not None
    assert "transaction fetch failed for 'B'" in result.known_gaps
    assert "ConnectionError" in result.known_gaps
    # A and C fetched fine and are never discarded over B's failure.
    assert [t.signature for t in result.transactions] == ["A", "C"]
    assert result.signatures_seen == 3


@pytest.mark.asyncio
async def test_partial_success_combines_multiple_faults_honestly() -> None:
    """A full failure-matrix combination: a genuine multi-page listing
    that itself completes cleanly, but two of the three listed
    transactions fail to fetch -- proving PARTIAL always reflects the
    worst fault observed, and every honest gap note survives together."""
    provider = ScriptedChainProvider(
        pages=[
            [_sig("A", 5), _sig("B", 4)],
            [_sig("C", 3)],
        ],
        transactions={"A": _tx("A")},
        tx_exceptions={
            "B": TimeoutError("timed out fetching B"),
            "C": ConnectionError("reset fetching C"),
        },
    )

    result = await acquire_historical_transactions(
        provider, address=ADDRESS, max_pages=10, page_size=2
    )

    assert result.status == STATUS_PARTIAL
    assert result.transaction_fetch_failures == 2
    assert result.signatures_seen == 3
    assert [t.signature for t in result.transactions] == ["A"]
    assert result.known_gaps is not None
    assert "transaction fetch failed for 'B'" in result.known_gaps
    assert "transaction fetch failed for 'C'" in result.known_gaps
    assert "incomplete" in result.completeness_statement.lower()


@pytest.mark.asyncio
async def test_every_provider_call_is_individually_accounted_for_exactly_once() -> None:
    """R2 provider-matrix requirement: proves usage accounting, not just a
    source-text claim -- every listing page fetch and every listed
    transaction fetch (successes and failures alike -- a failed fetch is
    still a real, billable provider call) reaches the provider exactly
    once, with no call silently skipped, retried, or duplicated by the
    acquisition service itself."""
    provider = ScriptedChainProvider(
        pages=[
            [_sig("A", 5), _sig("B", 4)],
            [_sig("C", 3)],
        ],
        transactions={"A": _tx("A")},
        tx_exceptions={"B": TimeoutError("timed out"), "C": ConnectionError("reset")},
    )

    result = await acquire_historical_transactions(
        provider, address=ADDRESS, max_pages=10, page_size=2
    )

    assert provider.usage_log == [
        "get_signatures_for_address#0",
        "get_signatures_for_address#1",
        "get_transaction:A",
        "get_transaction:B",
        "get_transaction:C",
    ]
    assert result.pages_fetched == len(
        [c for c in provider.usage_log if c.startswith("get_signatures_for_address")]
    )
    assert result.signatures_seen == len(
        [c for c in provider.usage_log if c.startswith("get_transaction:")]
    )


@pytest.mark.asyncio
async def test_default_page_bounds_are_the_documented_constants() -> None:
    assert DEFAULT_MAX_PAGES == 50
    assert DEFAULT_PAGE_SIZE == 1000

    provider = ScriptedChainProvider(pages=[[]])
    await acquire_historical_transactions(provider, address=ADDRESS)

    assert provider.calls == [(None, DEFAULT_PAGE_SIZE)]


@pytest.mark.asyncio
async def test_evidence_reference_and_identity_fields_are_carried_through() -> None:
    provider = ScriptedChainProvider(
        pages=[[_sig("A", 1)]],
        transactions={"A": _tx("A")},
    )

    result = await acquire_historical_transactions(provider, address=ADDRESS, page_size=10)

    assert len(result.transactions) == 1
    ev = result.transactions[0]
    assert ev.signature == "A"
    assert ev.slot == 1
    assert ev.evidence_reference == f"live_acquisition:{ADDRESS}:A"
    assert ev.raw == _tx("A")


# ---------------------------------------------------------------------
# argus-phase-2-remediation-002: expected_oldest_slot boundary matrix.
# The one remaining acceptance case round 1 left unproven -- a caller
# with an independently known expected historical boundary must not
# have a *premature* provider truncation (an empty/short page arriving
# before that boundary is actually reached) silently reported COMPLETE.
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r002_premature_short_page_before_boundary_is_partial() -> None:
    """Frozen acceptance test 1: an expected boundary that has NOT been
    reached, then a short (< page_size) page -- must be non-COMPLETE,
    name the unsatisfied boundary, preserve every fetched transaction,
    and account for every provider call actually made."""
    provider = ScriptedChainProvider(
        pages=[[_sig("A", 50), _sig("B", 49)]],  # short: 2 < page_size(5)
        transactions={"A": _tx("A"), "B": _tx("B")},
    )

    result = await acquire_historical_transactions(
        provider, address=ADDRESS, max_pages=10, page_size=5, expected_oldest_slot=10
    )

    assert result.status == STATUS_PARTIAL
    assert result.known_gaps is not None
    assert "expected oldest slot 10 not yet reached" in result.known_gaps
    assert "short" in result.known_gaps
    assert "slot 49" in result.known_gaps  # earliest observed, honestly reported
    # Every fetched transaction is preserved, never discarded over the
    # unsatisfied boundary.
    assert [t.signature for t in result.transactions] == ["A", "B"]
    assert result.signatures_seen == 2
    # Exactly the calls the walk actually made -- one listing call, two
    # transaction fetches -- correct provider usage accounting.
    assert provider.usage_log == [
        "get_signatures_for_address#0",
        "get_transaction:A",
        "get_transaction:B",
    ]


@pytest.mark.asyncio
async def test_r002_premature_empty_page_before_boundary_is_partial() -> None:
    """Frozen acceptance test 2: after at least one valid (full) page, an
    empty page arrives before the expected boundary is satisfied -- same
    fail-closed behavior, prior page's evidence preserved."""
    provider = ScriptedChainProvider(
        pages=[
            [_sig("A", 50), _sig("B", 49)],  # full page (page_size=2)
            [],  # premature empty page -- boundary (slot 10) not reached
        ],
        transactions={"A": _tx("A"), "B": _tx("B")},
    )

    result = await acquire_historical_transactions(
        provider, address=ADDRESS, max_pages=10, page_size=2, expected_oldest_slot=10
    )

    assert result.status == STATUS_PARTIAL
    assert result.known_gaps is not None
    assert "expected oldest slot 10 not yet reached" in result.known_gaps
    assert "empty" in result.known_gaps
    assert "slot 49" in result.known_gaps
    assert [t.signature for t in result.transactions] == ["A", "B"]
    assert provider.usage_log == [
        "get_signatures_for_address#0",
        "get_signatures_for_address#1",
        "get_transaction:A",
        "get_transaction:B",
    ]


@pytest.mark.asyncio
async def test_r002_boundary_satisfied_reports_complete() -> None:
    """Frozen acceptance test 3: the expected boundary IS actually
    reached/observed before the natural short-page completion -- the
    otherwise-valid walk may report COMPLETE."""
    provider = ScriptedChainProvider(
        pages=[[_sig("A", 50), _sig("B", 10), _sig("C", 9)]],  # short: 3 < page_size(5)
        transactions={s: _tx(s) for s in "ABC"},
    )

    result = await acquire_historical_transactions(
        provider, address=ADDRESS, max_pages=10, page_size=5, expected_oldest_slot=10
    )

    assert result.status == STATUS_COMPLETE
    assert result.known_gaps is None
    assert [t.signature for t in result.transactions] == ["A", "B", "C"]
    assert "complete" in result.completeness_statement.lower()


@pytest.mark.asyncio
async def test_r002_no_boundary_supplied_preserves_prior_short_page_complete_behavior() -> None:
    """Frozen acceptance test 4 (no-boundary regression): the exact same
    short-page shape that test_r002_premature_short_page_before_boundary_
    is_partial reports PARTIAL for (with a boundary) must still report
    COMPLETE when expected_oldest_slot is omitted entirely -- proving the
    default genuinely preserves round-1's unconditional short/empty-page-
    is-complete semantics, not merely a coincidentally-passing case."""
    provider = ScriptedChainProvider(
        pages=[[_sig("A", 50), _sig("B", 49)]],  # identical shape to test 1 above
        transactions={"A": _tx("A"), "B": _tx("B")},
    )

    result = await acquire_historical_transactions(
        provider, address=ADDRESS, max_pages=10, page_size=5
    )  # expected_oldest_slot omitted -- defaults to None

    assert result.status == STATUS_COMPLETE
    assert result.known_gaps is None
    assert [t.signature for t in result.transactions] == ["A", "B"]
