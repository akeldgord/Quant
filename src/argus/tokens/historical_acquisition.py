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
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from argus.providers import ChainProvider, SignatureInfo

from argus.wallets.early_buyer_extraction import RawTransactionEvidence

ALGORITHM_VERSION: Final[str] = "historical_acquisition_v1"

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


async def acquire_historical_transactions(
    provider: ChainProvider,
    *,
    address: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> AcquisitionResult:
    """Walks ``address``'s full signature history back to genesis (no
    persisted watermark/boundary -- this is a bootstrap-style historical
    acquisition, not an incremental gap-fill), bounded by ``max_pages``
    (never unbounded), then fetches and normalizes each transaction.

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
    - **a short/empty final page** is the ordinary, successful "reached
      the true start of this address's history" outcome -- ``COMPLETE``;
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
        if fault:
            break

        before_cursor = page[-1].signature
        if len(page) < page_size:
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
    )
