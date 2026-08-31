"""Real-chain golden fixture import/validation (Phase 1 remediation round
2, finding #12).

Synthetic fixtures (``tests/golden/fixtures/*.json``, see
``scripts/_generate_golden_fixtures.py``) prove the parser's own
determinism but never satisfy the real-chain fixture acceptance
criterion. This module is the offline half of closing that gap: this
sandbox has read-only GitHub access (confirmed working -- see
``tests/golden/fixtures/real/PROVENANCE.md``) but no general RPC egress
(confirmed blocked -- a direct ``getVersion`` call to
``api.mainnet-beta.solana.com`` fails at the proxy with a 403 policy
denial), so an authentic ``getTransaction`` payload has to be captured by
some *other*, network-enabled host and handed to this command as a local
file. This command never makes a network call itself; it only validates
an already-obtained payload's shape, canonicalizes it, records its
provenance, and proves the real parser classifies it -- so acquisition
(a separate, later step, by a host that *can* reach RPC) and
verification (this command, reproducible anywhere) are cleanly split.

Every import preserves exactly the fields the round 2 instruction
requires: chain/signature/slot/transaction version (read from the
payload itself, never taken on faith from a CLI flag, so they can never
drift from what the bytes actually say); upstream repository, commit,
and path (which the operator must supply, since nothing in the payload
itself can prove where it came from); upstream license; original and
sanitized bytes' SHA-256; the sanitization transform applied; and the
parser fields/expected canonical output (computed by actually running
:func:`argus.parsing.generic_parser.parse_transaction`, never asserted
by hand).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

from argus.clock import Clock
from argus.parsing.generic_parser import parse_transaction

DEFAULT_REAL_FIXTURES_DIR: Path = (
    Path(__file__).resolve().parents[2] / "tests" / "golden" / "fixtures" / "real"
)


class RealChainFixtureError(ValueError):
    """The input file is not usable as a real-chain golden fixture."""


@dataclasses.dataclass(frozen=True, slots=True)
class RealChainFixtureRecord:
    """Everything the round 2 instruction requires preserved for one
    imported real-chain fixture -- written to ``provenance.json`` (the
    machine-readable record this module reads back for validation) and
    rendered into ``PROVENANCE.md`` (the human-readable table)."""

    category: str
    chain: str
    signature: str
    slot: int
    transaction_version: str
    upstream_repo: str
    upstream_commit: str
    upstream_path: str
    upstream_license: str
    wallet_address: str
    original_sha256: str
    sanitized_sha256: str
    sanitization_transform: str
    expected_classification: str
    expected_confidence: str
    parser_version: str
    imported_at: str

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RealChainFixtureRecord:
        return cls(**data)


def _account_keys(message: Any) -> list[str]:
    if not isinstance(message, dict):
        return []
    keys = message.get("accountKeys", [])
    if not isinstance(keys, list):
        return []
    # Some RPC shapes return account keys as {"pubkey": "..."} objects
    # (e.g. jsonParsed encoding); accept both forms, matching
    # argus.parsing.generic_parser._account_keys exactly.
    return [k["pubkey"] if isinstance(k, dict) else k for k in keys]


def _unwrap_rpc_envelope(payload: Any) -> tuple[Any, bool]:
    """A payload captured via a raw ``curl``/RPC call is typically the
    *full* JSON-RPC envelope (``{"jsonrpc": "2.0", "result": {...}, "id":
    1}``), not just the ``result`` object -- while every fixture this
    project stores (synthetic and real) is the unwrapped ``result`` object
    directly (matching exactly what
    :meth:`argus.providers.helius.client.HeliusRpcClient.get_transaction`
    returns and what ``chain_events.raw_payload`` persists). Detects and
    unwraps that envelope shape automatically rather than rejecting a
    perfectly genuine capture on a technicality; returns whether it did."""
    if (
        isinstance(payload, dict)
        and "result" in payload
        and isinstance(payload["result"], dict)
        and not {"transaction", "meta", "slot"}.issubset(payload.keys())
    ):
        return payload["result"], True
    return payload, False


def _require_get_transaction_shape(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RealChainFixtureError(f"expected a JSON object, got {type(payload).__name__}")
    for key in ("transaction", "meta", "slot"):
        if key not in payload:
            raise RealChainFixtureError(
                f"not a getTransaction-shaped payload: missing required key {key!r}"
            )
    transaction = payload["transaction"]
    if not isinstance(transaction, dict) or "signatures" not in transaction:
        raise RealChainFixtureError("payload['transaction'] missing 'signatures'")
    signatures = transaction["signatures"]
    if not isinstance(signatures, list) or not signatures or not isinstance(signatures[0], str):
        raise RealChainFixtureError(
            "payload['transaction']['signatures'][0] must be a non-empty string"
        )
    if not isinstance(payload["meta"], dict):
        raise RealChainFixtureError("payload['meta'] must be an object")
    return payload


def _provenance_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "provenance.json"


def load_provenance(
    fixtures_dir: Path = DEFAULT_REAL_FIXTURES_DIR,
) -> dict[str, RealChainFixtureRecord]:
    path = _provenance_path(fixtures_dir)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {category: RealChainFixtureRecord.from_dict(entry) for category, entry in raw.items()}


def _write_provenance(
    records: dict[str, RealChainFixtureRecord], fixtures_dir: Path = DEFAULT_REAL_FIXTURES_DIR
) -> None:
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    payload = {category: record.to_dict() for category, record in sorted(records.items())}
    _provenance_path(fixtures_dir).write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    (fixtures_dir / "PROVENANCE.md").write_text(_render_markdown(records))


def _render_markdown(records: dict[str, RealChainFixtureRecord]) -> str:
    header = (
        "# Real-chain golden fixture provenance\n\n"
        "Generated by `argus fixtures import-real-chain` "
        "(`argus.golden_fixtures`) -- do not hand-edit; re-run the import "
        "command to update an entry. Every fixture here is an authentic "
        "`getTransaction` payload traceable to an immutable upstream "
        "GitHub commit, imported offline (this command never makes a "
        "network call itself -- see the module docstring for why). See "
        "`SEARCH_LOG.md` (hand-maintained, never overwritten by this "
        "command) for which upstream repositories were searched, which "
        "required categories these fixtures satisfy, and which remain "
        "NOT TESTED.\n\n"
    )
    if not records:
        return (
            header
            + "No real-chain fixtures are imported yet. See "
            + "`SEARCH_LOG.md` for the search process: this sandbox has "
            + "confirmed read-only GitHub access but no general RPC "
            + "egress, so no upstream repository found so far embeds "
            + "actual captured `getTransaction` payload bytes (as opposed "
            + "to a live-fetched signature reference) that this command "
            + "could import without network access of its own. This "
            + "criterion remains PARTIAL / NOT TESTED for every required "
            + "category until a network-enabled host captures and "
            + "verifies fixtures with this same command.\n"
        )
    lines = [
        header,
        "| Category | Signature | Slot | Version | Upstream | License | "
        "Expected classification | Sanitized SHA-256 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for category, record in sorted(records.items()):
        upstream = f"[{record.upstream_repo}@{record.upstream_commit[:12]}]({record.upstream_path})"
        lines.append(
            f"| {category} | `{record.signature}` | {record.slot} | "
            f"{record.transaction_version} | {upstream} | {record.upstream_license} | "
            f"{record.expected_classification} | `{record.sanitized_sha256}` |"
        )
    lines.append("\n## Per-fixture detail\n")
    for category, record in sorted(records.items()):
        lines.append(
            f"### `{category}`\n\n"
            f"- wallet perspective: `{record.wallet_address}`\n"
            f"- sanitization transform: {record.sanitization_transform}\n"
            f"- original (as-captured) SHA-256: `{record.original_sha256}`\n"
            f"- expected confidence: {record.expected_confidence}\n"
            f"- parser version at import: `{record.parser_version}`\n"
            f"- imported at: {record.imported_at}\n"
        )
    return "\n".join(lines) + "\n"


def import_real_chain_fixture(
    *,
    input_path: Path,
    category: str,
    upstream_repo: str,
    upstream_commit: str,
    upstream_path: str,
    upstream_license: str,
    wallet_address: str | None = None,
    fixtures_dir: Path = DEFAULT_REAL_FIXTURES_DIR,
    clock: Clock | None = None,
) -> RealChainFixtureRecord:
    """Validates ``input_path`` as a genuine `getTransaction`-shaped
    payload, canonicalizes it, runs it through the real parser, and writes
    both the fixture file and its provenance record. Purely offline:
    ``input_path`` must already contain a payload captured elsewhere."""
    original_bytes = input_path.read_bytes()
    original_sha256 = hashlib.sha256(original_bytes).hexdigest()

    try:
        payload = json.loads(original_bytes)
    except json.JSONDecodeError as exc:
        raise RealChainFixtureError(f"{input_path}: not valid JSON: {exc}") from exc
    payload, unwrapped = _unwrap_rpc_envelope(payload)
    payload = _require_get_transaction_shape(payload)

    transaction = payload["transaction"]
    signature: str = transaction["signatures"][0]
    slot = int(payload["slot"])
    transaction_version = str(payload.get("version", "legacy"))
    account_keys = _account_keys(transaction.get("message"))
    resolved_wallet = wallet_address or (account_keys[0] if account_keys else None)
    if not resolved_wallet:
        raise RealChainFixtureError(
            "no wallet_address given and the payload has no accountKeys to default to"
        )

    # The sanitization transform: on-chain data is already public, so
    # nothing is redacted -- an enclosing JSON-RPC envelope
    # ({"jsonrpc", "result", "id"}) is unwrapped down to just the
    # `result` object when present (matching every other fixture in this
    # project, and what chain_events.raw_payload actually stores), and
    # formatting is canonicalized (sorted keys, fixed indentation) so
    # re-importing the same upstream payload always produces an identical
    # fixture file byte-for-byte.
    sanitization_transform = (
        "unwrapped JSON-RPC envelope down to `result`; canonicalized JSON formatting"
        if unwrapped
        else "canonicalized JSON formatting only (no envelope to unwrap)"
    )
    sanitized_text = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    sanitized_sha256 = hashlib.sha256(sanitized_text.encode("utf-8")).hexdigest()

    parsed = parse_transaction(payload, wallet_address=resolved_wallet, slot=slot, block_time=None)

    fixtures_dir.mkdir(parents=True, exist_ok=True)
    (fixtures_dir / f"{category}.json").write_text(sanitized_text)

    record = RealChainFixtureRecord(
        category=category,
        chain="solana",
        signature=signature,
        slot=slot,
        transaction_version=transaction_version,
        upstream_repo=upstream_repo,
        upstream_commit=upstream_commit,
        upstream_path=upstream_path,
        upstream_license=upstream_license,
        wallet_address=resolved_wallet,
        original_sha256=original_sha256,
        sanitized_sha256=sanitized_sha256,
        sanitization_transform=sanitization_transform,
        expected_classification=parsed.classification,
        expected_confidence=str(parsed.confidence),
        parser_version=parsed.parser_version,
        imported_at=(clock or Clock()).utc_now().isoformat(),
    )

    records = load_provenance(fixtures_dir)
    records[category] = record
    _write_provenance(records, fixtures_dir)
    return record


@dataclasses.dataclass(frozen=True, slots=True)
class RealChainFixtureValidationResult:
    category: str
    ok: bool
    detail: str


def validate_real_chain_fixtures(
    fixtures_dir: Path = DEFAULT_REAL_FIXTURES_DIR,
) -> list[RealChainFixtureValidationResult]:
    """Re-verifies every currently-imported real-chain fixture: its bytes
    still hash to the recorded ``sanitized_sha256`` (detects drift) and
    the parser's current output still matches the recorded
    ``expected_classification``/``expected_confidence`` (the same "golden
    fixture output changes must fail until reviewed" discipline
    MASTER_SPEC.md section 21 requires of the synthetic fixtures). Returns
    an empty list when no real-chain fixtures are imported yet -- that is
    itself the honest, currently-expected state (see
    ``PROVENANCE.md``), not a validation failure."""
    results: list[RealChainFixtureValidationResult] = []
    for category, record in sorted(load_provenance(fixtures_dir).items()):
        fixture_path = fixtures_dir / f"{category}.json"
        if not fixture_path.exists():
            results.append(
                RealChainFixtureValidationResult(
                    category=category, ok=False, detail=f"fixture file missing: {fixture_path}"
                )
            )
            continue
        current_bytes = fixture_path.read_bytes()
        current_sha256 = hashlib.sha256(current_bytes).hexdigest()
        if current_sha256 != record.sanitized_sha256:
            results.append(
                RealChainFixtureValidationResult(
                    category=category,
                    ok=False,
                    detail=(
                        f"sanitized hash mismatch: recorded {record.sanitized_sha256}, "
                        f"current {current_sha256}"
                    ),
                )
            )
            continue
        payload = json.loads(current_bytes)
        parsed = parse_transaction(
            payload, wallet_address=record.wallet_address, slot=record.slot, block_time=None
        )
        if parsed.classification != record.expected_classification or (
            str(parsed.confidence) != record.expected_confidence
        ):
            results.append(
                RealChainFixtureValidationResult(
                    category=category,
                    ok=False,
                    detail=(
                        f"parser output changed: recorded "
                        f"{record.expected_classification}/{record.expected_confidence}, "
                        f"current {parsed.classification}/{parsed.confidence}"
                    ),
                )
            )
            continue
        results.append(RealChainFixtureValidationResult(category=category, ok=True, detail="ok"))
    return results
