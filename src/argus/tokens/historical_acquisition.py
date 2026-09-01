"""Provider-neutral historical acquisition service (P2-R2; required
implementation 4; MASTER_SPEC.md section 27-33).

The pre-remediation Phase 2 build had no actual acquisition path: the
only way to feed :func:`argus.wallets.archaeology.run_archaeology` was an
already-collected ``--evidence-file`` on disk. This module closes that
gap with a real, typed, provider-neutral service built directly on the
same :class:`argus.providers.ChainProvider` contract Phase 1's
reconciliation engine already uses (never a new provider abstraction) --
:func:`acquire_historical_transactions` paginates an address's signature
history (mirroring
``argus.ingestion.reconciliation.ReconciliationEngine._fetch_all_pages``'s
own ordering/duplicate/cursor-cycle fault detection, adapted for a
boundary-less "walk to the true start of this address's history" rather
than a watermark-bounded gap fill), fetches each transaction, and
normalizes the result into exactly the
:class:`argus.wallets.early_buyer_extraction.RawTransactionEvidence` list
:func:`argus.wallets.archaeology.run_archaeology` already consumes -- so
this module's output plugs directly into the existing, unmodified
archaeology service.

The offline ``--evidence-file`` CLI path remains available for
deterministic demonstrations (this instruction's own explicit
allowance); this module is the *additional* live-capable path, wired
through ``argus discover acquire-and-run-archaeology`` -- a real
production command, not a test-only helper -- using the exact same
``HeliusRpcClient`` construction (API key, usage-recorder-wired) every
other live Phase 1 command already uses. No paid provider, no live
credential requirement is added: this sandbox has none configured, so
the live path is exercised here only against a deterministic fake
provider in tests, per this instruction's explicit "tests may use a
deterministic fake provider and fake usage recorder" allowance -- the
same honest DEFERRED_ENVIRONMENTAL_CHECK status every other live Helius
path in this project already carries.

Provider usage accounting flows through the provider instance itself
(``HeliusRpcClient``'s own ``usage_recorder``, wired the same way
``argus ingest run`` already wires it) -- this module makes no separate
usage-accounting call of its own.

P2-R2 remediation round 2 (``argus-phase-2-remediation-002``) closes the
one narrow acceptance case round 1 left unproven: a caller with an
independently known expected historical boundary (e.g. a token's own
creation slot, already recoverable from other evidence) can supply
``expected_oldest_slot`` so a provider's *premature* early truncation --
an empty/short page that arrives before that boundary is actually
reached -- is distinguished, machine-checkably, from a genuine "reached
the start of history" completion. With no boundary supplied, the
original round-1 semantics are unchanged exactly (a short/empty page is
still the ordinary successful completion signal).
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from argus.providers import ChainProvider, SignatureInfo

from argus.wallets.early_buyer_extraction import RawTransactionEvidence

ALGORITHM_VERSION: Final[str] = "historical_acquisition_v2"

STATUS_COMPLETE: Final[str] = "COMPLETE"
STATUS_PARTIAL: Final[str] = "PARTIAL"
STATUS_FAILED: Final[str] = "FAILED"

DEFAULT_MAX_PAGES: Final[int] = 50
DEFAULT_PAGE_SIZE: Final[int] = 1000


@dataclasses.dataclass(frozen=True, slots=True)
class AcquisitionResult:
    """Everything :func:`argus.wallets.archaeology.run_archaeology` needs
    as its own ``known_gaps``/``completeness_statement`` disclosure, plus
    the normalized transaction evidence itself. ``status`` is never
    inferred from the transaction count alone -- an address with
    genuinely zero history is still ``COMPLETE``; any fault (pagination,
    provider failure, per-transaction fetch failure) that leaves the walk
    incomplete is always ``PARTIAL`` or ``FAILED``, explicit in
    ``known_gaps``."""

    transactions: list[RawTransactionEvidence]
    status: str
    known_gaps: str | None
    completeness_statement: str
    pages_fetched: int
    signatures_seen: int
    transaction_fetch_failures: int
    # P3-R2 remediation round 3 (`argus-phase-3-remediation-003`): the
    # exact caller-supplied boundary and whether THIS walk actually
    # observed it, as real typed fields -- never re-derived from
    # ``known_gaps`` prose by a downstream persistence layer.
    # ``boundary_satisfied`` is ``None`` only when no boundary was
    # supplied at all (nothing to satisfy), matching
    # ``expected_oldest_slot is None``.
    expected_oldest_slot: int | None
    boundary_satisfied: bool | None


async def acquire_historical_transactions(
    provider: ChainProvider,
    *,
    address: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_size: int = DEFAULT_PAGE_SIZE,
    expected_oldest_slot: int | None = None,
) -> AcquisitionResult:
    """Walks ``address``'s full signature history back to genesis (no
    persisted watermark -- this is a bootstrap-style historical
    acquisition, not an incremental gap-fill), bounded by ``max_pages``
    (never unbounded), then fetches and normalizes each transaction.

    ``expected_oldest_slot`` is an optional, caller-supplied, machine-
    checkable boundary (e.g. a token's own known creation slot) -- when
    given, an empty/short "natural completion" page is trusted as
    genuinely ``COMPLETE`` only once the walk has actually observed a
    signature at or before that slot; a caller with no independently
    known boundary passes ``None`` and gets the exact prior (round-1)
    behavior unchanged, where any short/empty page is itself sufficient.
    A caller-supplied ``--partial`` flag downstream is never the proof
    here -- this function itself compares the observed walk against the
    boundary.

    Explicit fault handling, never silently reported complete:

    - **provider failure calling get_signatures_for_address** (timeout,
      rate limit, malformed response, any other exception the provider
      raises) stops pagination at the current page and reports
      ``PARTIAL`` with the exact exception recorded in ``known_gaps``;
    - **pagination ordering fault** (a later page returns a newer slot
      than already observed) stops and reports ``PARTIAL``;
    - **duplicate signature across pages** (an immediately-repeated
      cursor, or a multi-step cursor cycle -- both produce the exact same
      observable symptom, a signature seen twice, so both are caught by
      the same check) stops and reports ``PARTIAL``;
    - **the safety ceiling** (``max_pages`` reached without the walk
      naturally completing) reports ``PARTIAL``;
    - **a short/empty final page** is the ordinary "reached the true
      start of this address's history" signal -- ``COMPLETE`` when no
      ``expected_oldest_slot`` was supplied, or once the walk has already
      observed a signature at or before it; if that boundary is supplied
      but has NOT yet been reached, the same short/empty page instead
      reports ``PARTIAL`` with the unsatisfied boundary named in
      ``known_gaps`` and every signature/transaction acquired so far
      still preserved, never discarded;
    - **a per-transaction fetch failure** (the signature was listed, but
      ``get_transaction`` itself failed) is recorded individually
      (``transaction_fetch_failures``), never silently dropped from the
      count, and downgrades the overall result to ``PARTIAL`` -- the
      signatures that DID fetch successfully are still returned, never
      discarded wholesale over one failure.
    """
    all_signatures: list[SignatureInfo] = []
    seen_signatures: set[str] = set()
    before_cursor: str | None = None
    last_slot: int | None = None
    status = STATUS_COMPLETE
    gap_notes: list[str] = []
    page_number = 0
    # True immediately when no boundary was supplied (nothing to satisfy);
    # otherwise flips True the first time an observed signature's slot is
    # at or below the caller's expected oldest slot.
    boundary_satisfied = expected_oldest_slot is None

    def _unsatisfied_boundary_note(*, page_kind: str) -> str:
        observed = f"slot {last_slot}" if last_slot is not None else "no signatures observed"
        return (
            f"expected oldest slot {expected_oldest_slot} not yet reached before a "
            f"{page_kind} page at page {page_number} -- earliest observed: {observed}"
        )

    for page_number in range(1, max_pages + 1):
        try:
            page = await provider.get_signatures_for_address(
                address, before_signature=before_cursor, limit=page_size
            )
        except Exception as exc:  # noqa: BLE001 -- provider-boundary fault, recorded not re-raised
            gap_notes.append(
                f"provider failure fetching signatures (page {page_number}): "
                f"{type(exc).__name__}: {exc}"
            )
            status = STATUS_PARTIAL
            break

        if not page:
            if not boundary_satisfied:
                gap_notes.append(_unsatisfied_boundary_note(page_kind="empty"))
                status = STATUS_PARTIAL
            break  # genuinely reached the start of this address's history

        fault = False
        for item in page:
            if last_slot is not None and item.slot > last_slot:
                gap_notes.append(
                    f"pagination ordering fault at page {page_number}: {item.signature!r} "
                    f"(slot {item.slot}) is newer than the prior observed slot {last_slot} "
                    "-- provider violated newest-first ordering"
                )
                status = STATUS_PARTIAL
                fault = True
                break
            last_slot = item.slot
            if item.signature in seen_signatures:
                gap_notes.append(
                    f"duplicate signature {item.signature!r} observed across pages (page "
                    f"{page_number}) -- immediately-repeated cursor or multi-step cursor cycle"
                )
                status = STATUS_PARTIAL
                fault = True
                break
            seen_signatures.add(item.signature)
            all_signatures.append(item)
            if expected_oldest_slot is not None and item.slot <= expected_oldest_slot:
                boundary_satisfied = True
        if fault:
            break

        before_cursor = page[-1].signature
        if len(page) < page_size:
            if not boundary_satisfied:
                gap_notes.append(_unsatisfied_boundary_note(page_kind="short"))
                status = STATUS_PARTIAL
            break  # short page -- reached the start
    else:
        gap_notes.append(
            f"safety ceiling of {max_pages} pages reached without exhausting {address!r}'s "
            "address history -- raise max_pages or investigate provider retention"
        )
        status = STATUS_PARTIAL

    transactions: list[RawTransactionEvidence] = []
    fetch_failures = 0
    for sig_info in all_signatures:
        try:
            raw = await provider.get_transaction(sig_info.signature)
        except Exception as exc:  # noqa: BLE001 -- per-item fault, recorded not re-raised
            fetch_failures += 1
            gap_notes.append(
                f"transaction fetch failed for {sig_info.signature!r}: {type(exc).__name__}: {exc}"
            )
            status = STATUS_PARTIAL
            continue
        transactions.append(
            RawTransactionEvidence(
                raw=raw,
                signature=sig_info.signature,
                slot=sig_info.slot,
                block_time=sig_info.block_time,
                evidence_reference=f"live_acquisition:{address}:{sig_info.signature}",
            )
        )

    completeness_statement = (
        f"{len(transactions)} of {len(all_signatures)} listed signature(s) fetched across "
        f"{page_number} page(s) for address {address!r}; "
        + (
            "complete address-history walk (no fault, safety ceiling not reached)"
            if status == STATUS_COMPLETE
            else "incomplete -- see known_gaps for the exact fault(s)"
        )
    )
    return AcquisitionResult(
        transactions=transactions,
        status=status,
        known_gaps="; ".join(gap_notes) or None,
        completeness_statement=completeness_statement,
        pages_fetched=page_number,
        signatures_seen=len(all_signatures),
        transaction_fetch_failures=fetch_failures,
        expected_oldest_slot=expected_oldest_slot,
        boundary_satisfied=(None if expected_oldest_slot is None else boundary_satisfied),
    )
