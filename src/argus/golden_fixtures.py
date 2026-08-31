"""Real-chain golden fixture import/validation (Phase 1 remediation round
2, finding #12; extended by round 4, findings #1/#2/#3).

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

Round 4 findings #2/#3 fixed two defects in the round 2 design:

- **Byte-exact reproducibility (finding #2).** ``--input`` must now be
  the *exact* raw bytes as captured upstream (including any wrapping
  array/envelope the upstream repository's own convention uses) -- never
  a copy an operator hand-unwrapped before handing it to this command.
  Those exact raw bytes are preserved verbatim in a content-addressed
  ``sources/`` directory (keyed by the ``git hash-object`` blob SHA-1, so
  the same identity ``git log``/``git cat-file`` would report for that
  upstream commit), and the array-unwrap/envelope-unwrap/canonicalize
  pipeline that derives the sanitized fixture from them is itself
  recorded as an ordered, hashed transform manifest --
  :func:`validate_real_chain_fixtures` replays that exact pipeline from
  the preserved source bytes and fails on any divergence at any step,
  rather than only re-checking a final hash against itself.
- **Non-circular expectations (finding #3).** ``expected_classification``/
  ``expected_confidence`` are now required arguments the caller supplies
  (an independent claim about what the transaction *should* parse to),
  checked against -- not defined by -- ``observed_classification``/
  ``observed_confidence`` (what actually running the parser produces).
  A mismatch refuses the import unless ``allow_observed_mismatch=True``
  is passed explicitly, so a fixture can never silently record the
  parser's own current output as if it were an independently-reviewed
  answer.
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
class TransformStep:
    """One step of the deterministic, offline-replayable pipeline that
    derives a sanitized fixture from preserved raw upstream bytes (Phase
    1 remediation round 4, finding #2). ``applied`` is ``False`` when
    this step was a structural no-op for this particular upstream file
    (e.g. ``unwrap_json_array`` on a payload that was never
    array-wrapped) -- the step still runs and is still recorded, so the
    manifest is a complete, honest account of the whole pipeline, not
    just the steps that happened to change something."""

    name: str
    applied: bool
    output_sha256: str


@dataclasses.dataclass(frozen=True, slots=True)
class RealChainFixtureRecord:
    """Everything the round 2 instruction (extended by round 4, findings
    #2/#3) requires preserved for one imported real-chain fixture --
    written to ``provenance.json`` (the machine-readable record this
    module reads back for validation) and rendered into
    ``PROVENANCE.md`` (the human-readable table)."""

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
    upstream_git_blob_sha1: str
    original_sha256: str
    sanitized_sha256: str
    transform_manifest: tuple[TransformStep, ...]
    observed_classification: str
    observed_confidence: str
    expected_classification: str
    expected_confidence: str
    parser_version: str
    imported_at: str

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RealChainFixtureRecord:
        data = dict(data)
        data["transform_manifest"] = tuple(
            TransformStep(**step) for step in data["transform_manifest"]
        )
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


def _git_blob_sha1(data: bytes) -> str:
    """The same content identity ``git hash-object``/``git cat-file``
    would report for these exact bytes as a blob -- an offline,
    independently-recomputable link back to the immutable upstream git
    commit this fixture traces to (Phase 1 remediation round 4, finding
    #2), without requiring a live clone of the upstream repository to
    verify."""
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def _unwrap_json_array(payload: Any) -> tuple[Any, bool]:
    """Several upstream repositories' own fixture convention wraps one
    captured payload in a single-element JSON array (``[{...}]``) rather
    than storing the bare object -- detected and unwrapped automatically,
    same as :func:`_unwrap_rpc_envelope` below, rather than requiring an
    operator to pre-unwrap it (which is exactly how round 4 finding #2's
    ``original_sha256``-computed-from-already-unwrapped-input defect
    happened: the pre-unwrapped copy handed to this command was never the
    genuine upstream bytes)."""
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        return payload[0], True
    return payload, False


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


def _canonical_json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _run_transform_pipeline(
    raw_bytes: bytes,
) -> tuple[dict[str, Any], bytes, tuple[TransformStep, ...]]:
    """The single deterministic pipeline -- array-unwrap, then
    envelope-unwrap, then require-shape, then canonicalize -- that
    derives a sanitized fixture from raw upstream bytes. Run once at
    import time and replayed again, from nothing but the preserved raw
    source bytes, at validation time (Phase 1 remediation round 4,
    finding #2): the two call sites sharing this exact function is what
    makes validation a genuine independent rebuild, not just a
    re-comparison of a stored hash against itself."""
    try:
        payload: Any = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise RealChainFixtureError(f"not valid JSON: {exc}") from exc

    steps: list[TransformStep] = []

    payload, array_applied = _unwrap_json_array(payload)
    steps.append(
        TransformStep(
            name="unwrap_json_array",
            applied=array_applied,
            output_sha256=hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
        )
    )

    payload, envelope_applied = _unwrap_rpc_envelope(payload)
    steps.append(
        TransformStep(
            name="unwrap_json_rpc_envelope",
            applied=envelope_applied,
            output_sha256=hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
        )
    )

    payload = _require_get_transaction_shape(payload)

    sanitized_bytes = _canonical_json_bytes(payload)
    steps.append(
        TransformStep(
            name="canonicalize_json_formatting",
            applied=True,
            output_sha256=hashlib.sha256(sanitized_bytes).hexdigest(),
        )
    )

    return payload, sanitized_bytes, tuple(steps)


def _provenance_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "provenance.json"


def _sources_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sources"


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
        "network call itself -- see the module docstring for why). Raw "
        "upstream bytes are preserved verbatim in `sources/` (named by "
        "their git blob SHA-1) so `validate-real-chain` can independently "
        "rebuild every sanitized fixture from nothing but that preserved "
        "source, offline, rather than trusting a stored hash. See "
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
        "| Category | Signature | Slot | Version | Upstream | Git blob SHA-1 | License | "
        "Expected classification | Observed classification | Sanitized SHA-256 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for category, record in sorted(records.items()):
        upstream = f"[{record.upstream_repo}@{record.upstream_commit[:12]}]({record.upstream_path})"
        agree = "" if record.expected_classification == record.observed_classification else " ⚠"
        lines.append(
            f"| {category} | `{record.signature}` | {record.slot} | "
            f"{record.transaction_version} | {upstream} | `{record.upstream_git_blob_sha1}` | "
            f"{record.upstream_license} | "
            f"{record.expected_classification} | {record.observed_classification}{agree} | "
            f"`{record.sanitized_sha256}` |"
        )
    lines.append("\n## Per-fixture detail\n")
    for category, record in sorted(records.items()):
        transform_lines = "\n".join(
            f"  {i + 1}. `{step.name}` (applied={step.applied}): `{step.output_sha256}`"
            for i, step in enumerate(record.transform_manifest)
        )
        lines.append(
            f"### `{category}`\n\n"
            f"- wallet perspective: `{record.wallet_address}`\n"
            f"- raw upstream source preserved at: `sources/{record.upstream_git_blob_sha1}"
            ".source.json`\n"
            f"- transform manifest:\n{transform_lines}\n"
            f"- original (as-captured) SHA-256: `{record.original_sha256}`\n"
            f"- expected classification/confidence (independently asserted at import "
            f"time): {record.expected_classification} / {record.expected_confidence}\n"
            f"- observed classification/confidence (actually running the parser): "
            f"{record.observed_classification} / {record.observed_confidence}\n"
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
    expected_classification: str,
    expected_confidence: str,
    wallet_address: str | None = None,
    allow_observed_mismatch: bool = False,
    fixtures_dir: Path = DEFAULT_REAL_FIXTURES_DIR,
    clock: Clock | None = None,
) -> RealChainFixtureRecord:
    """Validates ``input_path`` as a genuine, *unmodified* raw upstream
    capture, canonicalizes it, runs it through the real parser, and
    writes the fixture file, the raw source bytes, and the provenance
    record. Purely offline: ``input_path`` must already contain a
    payload captured elsewhere, and must be the exact bytes as captured
    -- any array/envelope wrapping the upstream repository's own
    convention uses is unwrapped by this function itself (recorded in
    the transform manifest), never by the caller beforehand (Phase 1
    remediation round 4, finding #2).

    ``expected_classification``/``expected_confidence`` are the caller's
    own independently-reasoned claim about what this transaction should
    parse to -- checked against, never defined by, what the parser
    actually produces (``observed_classification``/
    ``observed_confidence``, always computed by genuinely running it).
    A mismatch refuses the import (finding #3) unless
    ``allow_observed_mismatch=True`` is passed explicitly to deliberately
    capture a currently-divergent case for tracking -- never to hide a
    bug silently."""
    original_bytes = input_path.read_bytes()
    original_sha256 = hashlib.sha256(original_bytes).hexdigest()
    upstream_git_blob_sha1 = _git_blob_sha1(original_bytes)

    payload, sanitized_bytes, transform_manifest = _run_transform_pipeline(original_bytes)
    sanitized_sha256 = hashlib.sha256(sanitized_bytes).hexdigest()

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

    parsed = parse_transaction(payload, wallet_address=resolved_wallet, slot=slot, block_time=None)
    observed_classification = parsed.classification
    observed_confidence = str(parsed.confidence)
    if (
        observed_classification != expected_classification
        or observed_confidence != expected_confidence
    ) and not allow_observed_mismatch:
        raise RealChainFixtureError(
            f"{category!r}: parser observed {observed_classification}/{observed_confidence}, "
            f"which does not match the asserted expected_classification="
            f"{expected_classification!r}/expected_confidence={expected_confidence!r}. "
            "Either the expectation is wrong, or the parser has a bug -- refusing to "
            "import a fixture whose 'expected' value was never actually reviewed against "
            "what the parser produces. Pass allow_observed_mismatch=True only to "
            "deliberately capture a known-divergent case for tracking."
        )

    fixtures_dir.mkdir(parents=True, exist_ok=True)
    (fixtures_dir / f"{category}.json").write_bytes(sanitized_bytes)
    sources_dir = _sources_dir(fixtures_dir)
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / f"{upstream_git_blob_sha1}.source.json").write_bytes(original_bytes)

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
        upstream_git_blob_sha1=upstream_git_blob_sha1,
        original_sha256=original_sha256,
        sanitized_sha256=sanitized_sha256,
        transform_manifest=transform_manifest,
        observed_classification=observed_classification,
        observed_confidence=observed_confidence,
        expected_classification=expected_classification,
        expected_confidence=expected_confidence,
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
    """Re-verifies every currently-imported real-chain fixture by
    independently rebuilding it from scratch (Phase 1 remediation round
    4, finding #2), not merely re-comparing stored hashes against
    themselves:

    1. The preserved raw source bytes (``sources/<blob-sha>.source.json``)
       still exist, still hash to the recorded ``original_sha256``, and
       still have the recorded ``upstream_git_blob_sha1``.
    2. Replaying :func:`_run_transform_pipeline` on those raw bytes
       reproduces the exact same transform manifest recorded at import
       time (catching drift at whichever step actually diverges).
    3. The freshly-rebuilt sanitized bytes are byte-identical to the
       committed ``<category>.json`` fixture file on disk (catching
       tampering of the fixture file itself, not just a hash mismatch).
    4. The parser's current output still matches the recorded
       ``expected_classification``/``expected_confidence`` (the same
       "golden fixture output changes must fail until reviewed"
       discipline MASTER_SPEC.md section 21 requires of the synthetic
       fixtures) -- this is checked against the independently-asserted
       expectation, never against the parser's own observed output at
       import time (finding #3).

    Returns an empty list when no real-chain fixtures are imported yet --
    that is itself the honest, currently-expected state, not a
    validation failure."""
    results: list[RealChainFixtureValidationResult] = []
    sources_dir = _sources_dir(fixtures_dir)
    for category, record in sorted(load_provenance(fixtures_dir).items()):
        fixture_path = fixtures_dir / f"{category}.json"
        source_path = sources_dir / f"{record.upstream_git_blob_sha1}.source.json"

        if not source_path.exists():
            results.append(
                RealChainFixtureValidationResult(
                    category=category,
                    ok=False,
                    detail=f"preserved raw source missing: {source_path}",
                )
            )
            continue
        if not fixture_path.exists():
            results.append(
                RealChainFixtureValidationResult(
                    category=category, ok=False, detail=f"fixture file missing: {fixture_path}"
                )
            )
            continue

        raw_bytes = source_path.read_bytes()
        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        if raw_sha256 != record.original_sha256:
            results.append(
                RealChainFixtureValidationResult(
                    category=category,
                    ok=False,
                    detail=(
                        f"raw source hash mismatch: recorded {record.original_sha256}, "
                        f"current {raw_sha256}"
                    ),
                )
            )
            continue
        actual_blob_sha1 = _git_blob_sha1(raw_bytes)
        if actual_blob_sha1 != record.upstream_git_blob_sha1:
            results.append(
                RealChainFixtureValidationResult(
                    category=category,
                    ok=False,
                    detail=(
                        f"git blob SHA-1 mismatch: recorded {record.upstream_git_blob_sha1}, "
                        f"current {actual_blob_sha1}"
                    ),
                )
            )
            continue

        try:
            rebuilt_payload, rebuilt_bytes, rebuilt_manifest = _run_transform_pipeline(raw_bytes)
        except RealChainFixtureError as exc:
            results.append(
                RealChainFixtureValidationResult(
                    category=category,
                    ok=False,
                    detail=f"rebuild from preserved source failed: {exc}",
                )
            )
            continue

        if rebuilt_manifest != record.transform_manifest:
            for i, (rebuilt_step, recorded_step) in enumerate(
                zip(rebuilt_manifest, record.transform_manifest, strict=True)
            ):
                if rebuilt_step != recorded_step:
                    results.append(
                        RealChainFixtureValidationResult(
                            category=category,
                            ok=False,
                            detail=(
                                f"transform manifest diverged at step {i} "
                                f"({recorded_step.name!r}): recorded {recorded_step}, "
                                f"rebuilt {rebuilt_step}"
                            ),
                        )
                    )
                    break
            else:
                results.append(
                    RealChainFixtureValidationResult(
                        category=category, ok=False, detail="transform manifest length diverged"
                    )
                )
            continue

        current_fixture_bytes = fixture_path.read_bytes()
        if rebuilt_bytes != current_fixture_bytes:
            results.append(
                RealChainFixtureValidationResult(
                    category=category,
                    ok=False,
                    detail=(
                        "rebuilt sanitized bytes do not match the committed fixture file "
                        "-- the fixture file was modified outside the import pipeline"
                    ),
                )
            )
            continue
        current_sha256 = hashlib.sha256(current_fixture_bytes).hexdigest()
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

        parsed = parse_transaction(
            rebuilt_payload, wallet_address=record.wallet_address, slot=record.slot, block_time=None
        )
        if parsed.classification != record.expected_classification or (
            str(parsed.confidence) != record.expected_confidence
        ):
            results.append(
                RealChainFixtureValidationResult(
                    category=category,
                    ok=False,
                    detail=(
                        f"parser output changed: expected "
                        f"{record.expected_classification}/{record.expected_confidence}, "
                        f"current {parsed.classification}/{parsed.confidence}"
                    ),
                )
            )
            continue
        results.append(RealChainFixtureValidationResult(category=category, ok=True, detail="ok"))
    return results
