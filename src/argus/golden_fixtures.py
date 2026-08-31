"""Real-chain golden fixture import/validation (Phase 1 remediation round
2, finding #12; extended by round 4, findings #1/#2/#3; extended again by
round 5, findings #1/#2).

Synthetic fixtures (``tests/golden/fixtures/*.json``, see
``scripts/_generate_golden_fixtures.py``) prove the parser's own
determinism but never satisfy the real-chain fixture acceptance
criterion. This module is the offline half of closing that gap: this
sandbox has read-only GitHub access (confirmed working -- see
``tests/golden/fixtures/real/PROVENANCE.md``) but no general RPC egress,
so an authentic ``getTransaction`` payload has to be captured by some
*other*, network-enabled host (or this same sandbox's own confirmed
``git``/``raw.githubusercontent.com`` access) and handed to this module's
import function as already-obtained evidence -- acquisition (network
access required) and verification (offline, reproducible anywhere) stay
cleanly split.

Round 5 replaced round 4's two flat ``expected_classification``/
``expected_confidence`` strings and one asserted ``upstream_license``
string with two much richer, independently-checkable structures
(findings #1/#2):

- :class:`ExpectedOutcome` -- a typed, immutable, independently-reviewed
  expectation for one wallet perspective: classification, eligibility,
  *every* asset delta the transaction produced (not just the single
  primary in/out leg), expected input/output mint and amounts, the
  network fee, failed-transaction status, a confidence rule, and the
  reviewer's own method/rationale/evidence. Never derived from running
  the parser -- :func:`import_real_chain_fixture` records the parser's
  ``observed_*`` output as a *separate* set of fields, checked against
  (never promoted to) the expectation.
- :class:`GitTreeAttestation` / :class:`LicenseEvidence` -- real ``git
  ls-tree`` evidence (captured once, at import time, against an
  already-cloned local copy of the upstream repository -- this sandbox's
  confirmed-working ``git clone`` access) proving the declared upstream
  path at the declared commit resolves to the declared blob, and doing
  the same for the upstream license file, with its exact bytes preserved
  and hashed. A bare asserted metadata string is never trusted alone.

Every fixture's full evidence -- upstream identity, preserved source
bytes, transform manifest, license, and expectation -- is folded into one
``evidence_chain_hash``, so a partial edit to any single field (without
recomputing the rest) is detectable by :func:`validate_real_chain_fixtures`
re-deriving that hash from the record's current content, entirely
offline. A fixture whose observed parser output diverges from its
independent expectation may still be imported, but only as an explicitly
``quarantined`` research fixture with a recorded reason -- it always
fails golden validation and is never counted as passing category
coverage.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from argus.clock import Clock
from argus.parsing.generic_parser import (
    ParsedTransaction,
    compute_account_level_deltas,
    compute_asset_deltas,
    parse_transaction,
)

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
class GitTreeAttestation:
    """An offline-verifiable Git *object chain*, captured once at import
    time (this sandbox's confirmed-working ``git clone`` access), proving
    -- by independently recomputing every object ID along the way, from
    raw preserved object bytes, with no ``git`` binary or network access
    required at validation time -- that the declared path at the declared
    commit resolves to the declared blob (Phase 1 remediation round 6,
    finding #2).

    Round 5's version stored a single saved ``git ls-tree`` output line
    and the offline validator only re-parsed that *same* line and checked
    it against itself -- that proves the saved text is internally
    self-consistent, never that the declared upstream commit actually
    contains the declared path at a tree that resolves to the declared
    blob. This version instead preserves the *raw git object content* for
    the commit and every tree walked along ``path`` (base64-encoded, since
    they are arbitrary bytes in a JSON record), so
    :func:`verify_git_object_chain` can, entirely offline:

    1. recompute ``commit_sha`` from ``commit_object_b64`` using git's own
       content-addressing (``sha1("commit " + len + "\\0" + content)``)
       and confirm it matches;
    2. parse the commit object's first ``tree <sha>`` line to get the
       declared root tree;
    3. walk ``path_components`` one directory level at a time, at each
       step recomputing that level's tree object hash from
       ``tree_object_chain_b64[i]`` and confirming it matches the sha
       expected from the previous level (the root tree's own hash for
       level 0), then looking up the next path component's entry inside
       that freshly-parsed tree to get either the next level's tree sha
       or, at the final component, the resolved blob's sha1;
    4. confirm the fully-resolved final blob sha1 equals ``blob_sha1``.

    This proves genuine Git *object-chain integrity* -- that these
    specific bytes, if fed to ``git hash-object``, really do chain from
    ``commit_sha`` down to ``blob_sha1`` via exactly this path. It does
    **not**, and cannot, prove that ``commit_sha`` was genuinely served by
    a particular remote hostname/repository at any point in time --
    fabricating a self-consistent, syntactically valid Git object graph
    requires no network access at all. That property is inherently
    online-only, reported separately (as the acquisition record: which
    URL was cloned, when), and never counted as an offline PASS."""

    commit_sha: str
    commit_object_b64: str
    path: str
    path_components: tuple[str, ...]
    tree_object_chain_b64: tuple[str, ...]
    mode: str
    blob_sha1: str
    captured_at: str


@dataclasses.dataclass(frozen=True, slots=True)
class LicenseEvidence:
    """The upstream repository's license, bound the same way a fixture's
    transaction data is: real ``git ls-tree`` evidence for the license
    file's own path/blob, its exact bytes preserved verbatim and hashed,
    plus the reviewer's compatibility decision and required attribution
    text (Phase 1 remediation round 5, finding #2)."""

    spdx_id: str
    path: str
    tree_attestation: GitTreeAttestation
    bytes_sha256: str
    compatibility_decision: str
    attribution: str


@dataclasses.dataclass(frozen=True, slots=True)
class WalletPerspective:
    """Which wallet this expectation is reasoned from, and how that role
    was established (e.g. "accountKeys[0], the transaction's fee payer,
    per the upstream repository's own wallet-perspective test
    description")."""

    wallet_address: str
    method: str


@dataclasses.dataclass(frozen=True, slots=True)
class ExpectedAssetDelta:
    """One asset's net balance change, as independently reasoned by the
    reviewer -- ordered and compared against every asset
    :func:`argus.parsing.generic_parser.compute_asset_deltas` actually
    finds, not only the classifier's single primary in/out leg."""

    mint: str  # "SOL" (canonical) or a mint address
    account_context: str | None  # a specific token account, only when material
    raw_amount: int  # signed; negative = outflow, positive = inflow
    decimals: int
    ui_amount: str  # exact decimal string


@dataclasses.dataclass(frozen=True, slots=True)
class ExpectedAccountAssetDelta:
    """One wallet-owned *account*'s independently-reviewed net balance
    change, preserved before by-mint aggregation (Phase 1 remediation
    round 6, finding #3) -- checked against
    :func:`argus.parsing.generic_parser.compute_account_level_deltas`,
    which retains real account-index/owner/mint/pre/post/net/decimals
    granularity that :class:`ExpectedAssetDelta`'s by-mint view discards.
    This is the oracle a multiple-token-account/LP-style category is
    actually proven against: two accounts of the same mint moving in
    opposite directions can net to zero and disappear from the by-mint
    view entirely, even though both were genuinely material."""

    account_identifier: str
    account_index: int
    owner: str
    mint: str  # "SOL" (canonical) or a mint address
    pre_raw_amount: int
    post_raw_amount: int
    net_raw_delta: int
    decimals: int
    ui_delta: str  # exact decimal string


@dataclasses.dataclass(frozen=True, slots=True)
class ReviewerEvidence:
    method: str
    rationale: str
    evidence_refs: tuple[str, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class ExpectedOutcome:
    """The typed, immutable, independently-reviewed expectation for one
    real-chain fixture's wallet perspective (Phase 1 remediation round 5,
    finding #1; ``account_deltas`` added round 6, finding #3). Never
    derived from running the parser under test --
    :func:`import_real_chain_fixture` computes the parser's own
    ``observed_*`` output as separate fields on
    :class:`RealChainFixtureRecord`, checked against (never promoted to)
    this object."""

    classification: str
    is_copy_eligible: bool
    wallet_perspective: WalletPerspective
    asset_deltas: tuple[ExpectedAssetDelta, ...]
    account_deltas: tuple[ExpectedAccountAssetDelta, ...]
    expected_input_mint: str | None
    expected_input_amount_raw: int | None
    expected_output_mint: str | None
    expected_output_amount_raw: int | None
    network_fee_raw: int
    transaction_failed: bool
    expected_confidence: str
    confidence_rule: str
    reviewer: ReviewerEvidence


@dataclasses.dataclass(frozen=True, slots=True)
class RealChainFixtureRecord:
    """Everything round 2/4/5's instructions require preserved for one
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
    upstream_path_note: str
    upstream_tree_attestation: GitTreeAttestation
    upstream_license: LicenseEvidence
    upstream_git_blob_sha1: str
    original_sha256: str
    sanitized_sha256: str
    transform_manifest: tuple[TransformStep, ...]
    observed_classification: str
    observed_confidence: str
    observed_is_copy_eligible: bool
    expectation: ExpectedOutcome
    quarantined: bool
    quarantine_reason: str | None
    evidence_chain_hash: str
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
        data["upstream_tree_attestation"] = _tree_attestation_from_dict(
            data["upstream_tree_attestation"]
        )
        data["upstream_license"] = _license_evidence_from_dict(data["upstream_license"])
        data["expectation"] = _expectation_from_dict(data["expectation"])
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


def _git_object_sha1(object_type: str, content: bytes) -> str:
    """Git's own content-addressing for any loose object type: ``sha1(<type>
    " " <len> "\\0" <content>)``. ``_git_blob_sha1`` (round 4, finding #2)
    is the ``object_type="blob"`` special case; round 6, finding #2 needs
    the same identity for ``commit`` and ``tree`` objects too, to walk and
    verify a full object chain offline."""
    header = f"{object_type} {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()  # noqa: S324 -- git's own content-addressing


def _git_blob_sha1(data: bytes) -> str:
    """The same content identity ``git hash-object``/``git cat-file``
    would report for these exact bytes as a blob -- an offline,
    independently-recomputable link back to the immutable upstream git
    commit this fixture traces to (Phase 1 remediation round 4, finding
    #2), without requiring a live clone of the upstream repository to
    verify."""
    return _git_object_sha1("blob", data)


def _parse_git_commit_tree_sha(commit_bytes: bytes) -> str:
    """Extracts the root tree SHA-1 from a raw git commit object's first
    ``tree <sha>`` header line."""
    try:
        first_line = commit_bytes.split(b"\n", 1)[0].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RealChainFixtureError("git commit object is not valid UTF-8") from exc
    prefix, _sep, tree_sha = first_line.partition(" ")
    if (
        prefix != "tree"
        or len(tree_sha) != 40
        or not all(c in "0123456789abcdef" for c in tree_sha)
    ):
        raise RealChainFixtureError(
            f"git commit object does not begin with a valid 'tree <sha>' header line: {first_line!r}"
        )
    return tree_sha


def _parse_git_tree_object(tree_bytes: bytes) -> list[tuple[str, str, str]]:
    """Parses a raw git tree object's binary content (mode-space-name-NUL-
    20_raw_sha1_bytes, repeated) into ``(mode, name, sha1_hex)`` entries,
    in on-disk order. Pure Python, no ``git`` binary required -- this is
    what lets :func:`verify_git_object_chain` run fully offline."""
    entries: list[tuple[str, str, str]] = []
    i, n = 0, len(tree_bytes)
    while i < n:
        null_idx = tree_bytes.find(b"\0", i)
        if null_idx == -1:
            raise RealChainFixtureError("truncated git tree object: missing NUL after entry header")
        try:
            header = tree_bytes[i:null_idx].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RealChainFixtureError("git tree object entry header is not valid UTF-8") from exc
        mode, _sep, name = header.partition(" ")
        if not _sep:
            raise RealChainFixtureError(f"malformed git tree entry header: {header!r}")
        sha_bytes = tree_bytes[null_idx + 1 : null_idx + 21]
        if len(sha_bytes) != 20:
            raise RealChainFixtureError("truncated git tree object: incomplete entry SHA-1")
        entries.append((mode, name, sha_bytes.hex()))
        i = null_idx + 21
    return entries


_REGULAR_FILE_GIT_MODES = frozenset({"100644", "100755", "120000"})


def attest_git_tree(
    repo_clone_dir: Path, commit: str, path: str, *, clock: Clock | None = None
) -> GitTreeAttestation:
    """Walks an already-cloned local copy of the upstream repository (a
    shallow, tree/commit-only clone -- e.g. ``git clone
    --filter=blob:none --no-checkout <url>`` -- is sufficient; no blob
    content needs to be fetched) to build a full, offline-independently-
    verifiable Git object chain from the declared commit down to the
    declared path's blob (Phase 1 remediation round 6, finding #2):
    resolves the commit, reads its raw object bytes, extracts the root
    tree, then walks ``path`` one directory component at a time, reading
    each tree object's raw bytes along the way and self-checking every
    object's content against its own hash *at capture time too* -- a
    corrupt capture is refused immediately, not silently trusted until
    validation.

    Captured once, with real network access (this function itself makes
    no network call -- ``repo_clone_dir`` must already be a local clone),
    by whoever is acquiring a fixture; the resulting attestation is then
    preserved and independently re-verified, entirely offline, by
    :func:`verify_git_object_chain`."""

    def _cat_file(object_type: str, object_sha: str) -> bytes:
        result = subprocess.run(
            ["git", "cat-file", object_type, object_sha],
            cwd=repo_clone_dir,
            capture_output=True,
            timeout=30,
            check=True,
        )
        return result.stdout

    resolved = subprocess.run(
        ["git", "rev-parse", f"{commit}^{{commit}}"],
        cwd=repo_clone_dir,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    resolved_commit = resolved.stdout.strip()
    if not resolved_commit:
        raise RealChainFixtureError(f"could not resolve commit {commit!r} in {repo_clone_dir}")

    commit_bytes = _cat_file("commit", resolved_commit)
    if _git_object_sha1("commit", commit_bytes) != resolved_commit:
        raise RealChainFixtureError(
            f"recomputed commit object hash does not match resolved commit {resolved_commit!r} "
            "-- capture is corrupt"
        )

    components = tuple(c for c in path.split("/") if c)
    if not components:
        raise RealChainFixtureError(f"empty path: {path!r}")

    tree_chain: list[bytes] = []
    current_tree_sha = _parse_git_commit_tree_sha(commit_bytes)
    mode = ""
    blob_sha1 = ""
    for i, component in enumerate(components):
        tree_bytes = _cat_file("tree", current_tree_sha)
        if _git_object_sha1("tree", tree_bytes) != current_tree_sha:
            raise RealChainFixtureError(
                f"recomputed tree object hash does not match {current_tree_sha!r} while walking "
                f"{path!r} -- capture is corrupt"
            )
        tree_chain.append(tree_bytes)
        entries = {name: (m, sha) for m, name, sha in _parse_git_tree_object(tree_bytes)}
        if component not in entries:
            raise RealChainFixtureError(
                f"git tree {current_tree_sha!r} has no entry {component!r} while walking {path!r} "
                f"at commit {resolved_commit!r}"
            )
        mode, next_sha = entries[component]
        if i == len(components) - 1:
            blob_sha1 = next_sha
        else:
            current_tree_sha = next_sha

    if mode not in _REGULAR_FILE_GIT_MODES:
        raise RealChainFixtureError(
            f"{path!r} at {resolved_commit!r} resolves to git mode {mode!r}, not a regular file/"
            "symlink blob"
        )

    return GitTreeAttestation(
        commit_sha=resolved_commit,
        commit_object_b64=base64.b64encode(commit_bytes).decode("ascii"),
        path=path,
        path_components=components,
        tree_object_chain_b64=tuple(base64.b64encode(t).decode("ascii") for t in tree_chain),
        mode=mode,
        blob_sha1=blob_sha1,
        captured_at=(clock or Clock()).utc_now().isoformat(),
    )


def verify_git_object_chain(attestation: GitTreeAttestation) -> str | None:
    """Fully, independently recomputes every object ID along ``commit_sha
    -> root tree -> ... -> blob_sha1`` from the attestation's own
    preserved raw object bytes and confirms the declared path resolves to
    the declared blob -- no ``git`` binary, network access, or trust in
    any single saved summary line required (Phase 1 remediation round 6,
    finding #2). Returns ``None`` if the chain fully verifies, else a
    description of exactly where it diverges."""
    try:
        commit_bytes = base64.b64decode(attestation.commit_object_b64, validate=True)
    except (binascii.Error, ValueError):
        return "commit_object_b64 is not valid base64"
    if _git_object_sha1("commit", commit_bytes) != attestation.commit_sha:
        return "recomputed commit object hash does not match commit_sha"

    try:
        tree_sha = _parse_git_commit_tree_sha(commit_bytes)
    except RealChainFixtureError as exc:
        return str(exc)

    if "/".join(c for c in attestation.path.split("/") if c) != attestation.path:
        return "path is not a normalized '/'-joined sequence of its own components"
    if tuple(c for c in attestation.path.split("/") if c) != attestation.path_components:
        return "path_components does not reconstruct declared path"
    if len(attestation.tree_object_chain_b64) != len(attestation.path_components):
        return "tree_object_chain_b64 length does not match path_components length"
    if not attestation.path_components:
        return "path_components is empty"

    current_tree_sha = tree_sha
    mode = ""
    blob_sha1 = ""
    for i, (component, tree_b64) in enumerate(
        zip(attestation.path_components, attestation.tree_object_chain_b64, strict=True)
    ):
        try:
            tree_bytes = base64.b64decode(tree_b64, validate=True)
        except (binascii.Error, ValueError):
            return f"tree_object_chain_b64[{i}] is not valid base64"
        if _git_object_sha1("tree", tree_bytes) != current_tree_sha:
            return (
                f"recomputed tree object hash at path component {i} ({component!r}) does not "
                f"match the expected {current_tree_sha!r}"
            )
        try:
            entries = {name: (m, sha) for m, name, sha in _parse_git_tree_object(tree_bytes)}
        except RealChainFixtureError as exc:
            return f"tree_object_chain_b64[{i}]: {exc}"
        if component not in entries:
            return f"tree {current_tree_sha!r} has no entry {component!r}"
        mode, next_sha = entries[component]
        if i == len(attestation.path_components) - 1:
            blob_sha1 = next_sha
        else:
            current_tree_sha = next_sha

    if mode != attestation.mode:
        return f"resolved git mode {mode!r} does not match declared mode {attestation.mode!r}"
    if blob_sha1 != attestation.blob_sha1:
        return (
            f"final resolved blob sha1 {blob_sha1!r} does not match declared "
            f"blob_sha1 {attestation.blob_sha1!r}"
        )
    return None


_TS_CONST_EXPORT_RE = re.compile(r"=\s*(\{.*\})\s*\n\nexport default\s+\w+;\s*\n?\Z", re.DOTALL)


def _extract_ts_const_export_default(raw_bytes: bytes) -> tuple[bytes, bool]:
    """Some upstream repositories capture a ``getTransaction`` payload as
    a TypeScript module exporting one const object literal (``const x: T
    = {...};`` ... ``export default x;``) rather than storing bare JSON
    (Phase 1 remediation round 5, finding #3). Detects that exact shape
    and extracts the JSON object text deterministically -- by regex over
    the raw bytes, never by executing/importing the ``.ts`` file -- so
    ``--input`` can be the exact unmodified raw upstream ``.ts`` bytes.
    Returns the bytes unchanged (with ``applied=False``) for anything
    that does not match, including bytes that are already plain JSON."""
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes, False
    match = _TS_CONST_EXPORT_RE.search(text)
    if match is None:
        return raw_bytes, False
    candidate = match.group(1)
    try:
        json.loads(candidate)
    except json.JSONDecodeError:
        return raw_bytes, False
    return candidate.encode("utf-8"), True


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
    """The single deterministic pipeline -- TS-const-export extraction,
    then array-unwrap, then envelope-unwrap, then require-shape, then
    canonicalize -- that derives a sanitized fixture from raw upstream
    bytes. Run once at import time and replayed again, from nothing but
    the preserved raw source bytes, at validation time (Phase 1
    remediation round 4, finding #2): the two call sites sharing this
    exact function is what makes validation a genuine independent
    rebuild, not just a re-comparison of a stored hash against itself."""
    steps: list[TransformStep] = []

    ts_bytes, ts_applied = _extract_ts_const_export_default(raw_bytes)
    steps.append(
        TransformStep(
            name="extract_ts_const_export_default",
            applied=ts_applied,
            # This step runs before JSON parsing (its whole job is
            # producing JSON-parseable text from a non-JSON .ts module),
            # so its output is hashed as raw bytes -- every later step
            # hashes the canonicalized JSON of the payload object instead.
            output_sha256=hashlib.sha256(ts_bytes).hexdigest(),
        )
    )

    try:
        payload: Any = json.loads(ts_bytes)
    except json.JSONDecodeError as exc:
        raise RealChainFixtureError(f"not valid JSON: {exc}") from exc

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


def _licenses_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sources" / "licenses"


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
        "Generated by `argus.golden_fixtures` -- do not hand-edit; "
        "re-run the import to update an entry. Every fixture here is an "
        "authentic `getTransaction` payload traceable to an immutable "
        "upstream GitHub commit via an offline-verifiable Git object chain "
        "(commit -> tree -> ... -> blob, Phase 1 remediation round 6, "
        "finding #2), with a typed, independently-reviewed expectation "
        "(round 5 finding #1; account-level deltas added round 6 finding "
        "#3) checked against -- never defined by -- the parser's own "
        "observed output. See "
        "`SEARCH_LOG.md` (hand-maintained, never overwritten by this "
        "module) for which upstream repositories were searched and which "
        "required categories these fixtures satisfy.\n\n"
    )
    if not records:
        return header + "No real-chain fixtures are imported yet.\n"
    lines = [
        header,
        "| Category | Signature | Slot | Upstream | License | Expected | "
        "Observed | Eligible | Quarantined |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for category, record in sorted(records.items()):
        upstream = f"[{record.upstream_repo}@{record.upstream_commit[:12]}]({record.upstream_path})"
        exp = record.expectation
        agree = "" if exp.classification == record.observed_classification else " ⚠"
        quarantine = f"yes: {record.quarantine_reason}" if record.quarantined else "no"
        lines.append(
            f"| {category} | `{record.signature}` | {record.slot} | {upstream} | "
            f"{record.upstream_license.spdx_id} | {exp.classification} | "
            f"{record.observed_classification}{agree} | {exp.is_copy_eligible} | {quarantine} |"
        )
    lines.append("\n## Per-fixture detail\n")
    for category, record in sorted(records.items()):
        exp = record.expectation
        transform_lines = "\n".join(
            f"  {i + 1}. `{step.name}` (applied={step.applied}): `{step.output_sha256}`"
            for i, step in enumerate(record.transform_manifest)
        )
        deltas_lines = "\n".join(
            f"  - `{d.mint}`: {d.raw_amount} raw ({d.ui_amount} UI, {d.decimals} decimals)"
            + (f" @ account `{d.account_context}`" if d.account_context else "")
            for d in exp.asset_deltas
        )
        account_deltas_lines = "\n".join(
            f"  - account `{d.account_identifier}` (index {d.account_index}) mint `{d.mint}`: "
            f"{d.pre_raw_amount} -> {d.post_raw_amount} raw (net {d.net_raw_delta:+d}, "
            f"{d.ui_delta} UI, {d.decimals} decimals)"
            for d in exp.account_deltas
        )
        tree_att = record.upstream_tree_attestation
        lines.append(
            f"### `{category}`\n\n"
            f"- wallet perspective: `{exp.wallet_perspective.wallet_address}` "
            f"({exp.wallet_perspective.method})\n"
            f"- raw upstream source preserved at: `sources/{record.upstream_git_blob_sha1}"
            ".source.json`\n"
            f"- upstream git object chain: commit `{tree_att.commit_sha}` -> path "
            f"`{tree_att.path}` -> blob `{tree_att.blob_sha1}` (mode `{tree_att.mode}`, "
            f"{len(tree_att.tree_object_chain_b64)} tree object(s) preserved, offline-"
            "reverifiable via argus.golden_fixtures.verify_git_object_chain)\n"
            f"- license: {record.upstream_license.spdx_id} at `{record.upstream_license.path}` "
            f"(`{record.upstream_license.bytes_sha256}`) -- "
            f"{record.upstream_license.compatibility_decision}\n"
            f"- attribution: {record.upstream_license.attribution}\n"
            f"- transform manifest:\n{transform_lines}\n"
            f"- expected asset deltas (by mint):\n{deltas_lines}\n"
            f"- expected account-level deltas (pre-aggregation):\n{account_deltas_lines}\n"
            f"- expected confidence rule: {exp.confidence_rule} "
            f"(exact: {exp.expected_confidence})\n"
            f"- reviewer method: {exp.reviewer.method}\n"
            f"- reviewer rationale: {exp.reviewer.rationale}\n"
            f"- reviewer evidence: {', '.join(exp.reviewer.evidence_refs)}\n"
            f"- observed: {record.observed_classification} / {record.observed_confidence} / "
            f"eligible={record.observed_is_copy_eligible}\n"
            f"- evidence chain hash: `{record.evidence_chain_hash}`\n"
            f"- parser version at import: `{record.parser_version}`\n"
            f"- imported at: {record.imported_at}\n"
        )
    return "\n".join(lines) + "\n"


def _expectation_dict(expectation: ExpectedOutcome) -> dict[str, Any]:
    return dataclasses.asdict(expectation)


def compute_evidence_chain_hash(
    *,
    upstream_repo: str,
    upstream_commit: str,
    upstream_path: str,
    upstream_path_note: str,
    upstream_tree_attestation: GitTreeAttestation,
    upstream_license: LicenseEvidence,
    upstream_git_blob_sha1: str,
    original_sha256: str,
    sanitized_sha256: str,
    transform_manifest: tuple[TransformStep, ...],
    expectation: ExpectedOutcome,
    quarantined: bool,
    quarantine_reason: str | None,
) -> str:
    """One combined hash covering every non-observational field of a
    fixture's evidence -- upstream identity, tree/license attestations,
    preserved-source identity, the transform manifest, and the full
    independent expectation (Phase 1 remediation round 5, finding #2).
    Deliberately excludes ``observed_*``/``parser_version``/``imported_at``,
    which are allowed to reflect the *current* parser without
    invalidating the frozen evidence. A partial edit to any covered field
    without recomputing this hash is caught by
    :func:`validate_real_chain_fixtures` re-deriving it from the record's
    current content."""
    payload = {
        "upstream_repo": upstream_repo,
        "upstream_commit": upstream_commit,
        "upstream_path": upstream_path,
        "upstream_path_note": upstream_path_note,
        "upstream_tree_attestation": dataclasses.asdict(upstream_tree_attestation),
        "upstream_license": dataclasses.asdict(upstream_license),
        "upstream_git_blob_sha1": upstream_git_blob_sha1,
        "original_sha256": original_sha256,
        "sanitized_sha256": sanitized_sha256,
        "transform_manifest": [dataclasses.asdict(s) for s in transform_manifest],
        "expectation": _expectation_dict(expectation),
        "quarantined": quarantined,
        "quarantine_reason": quarantine_reason,
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def import_real_chain_fixture(
    *,
    input_path: Path,
    category: str,
    upstream_repo: str,
    upstream_commit: str,
    upstream_path_note: str,
    upstream_tree_attestation: GitTreeAttestation,
    upstream_license: LicenseEvidence,
    license_bytes: bytes,
    expectation: ExpectedOutcome,
    quarantine_reason: str | None = None,
    fixtures_dir: Path = DEFAULT_REAL_FIXTURES_DIR,
    clock: Clock | None = None,
) -> RealChainFixtureRecord:
    """Validates ``input_path`` as a genuine, *unmodified* raw upstream
    capture, canonicalizes it, runs it through the real parser, and
    writes the fixture file, the raw source bytes, the license bytes, and
    the provenance record.

    ``upstream_tree_attestation``/``upstream_license`` must be real ``git
    ls-tree`` evidence (see :func:`attest_git_tree`) captured separately,
    with real network access, against a local clone of the upstream
    repository -- this function itself performs no network call.

    ``expectation`` is the caller's own independently-reasoned claim
    about what this transaction should parse to from the wallet
    perspective it names -- checked against, never defined by, what the
    parser actually produces (recorded separately as
    ``observed_classification``/``observed_confidence``/
    ``observed_is_copy_eligible``, always computed by genuinely running
    it). A mismatch on any checked field refuses the import (finding #1)
    unless ``quarantine_reason`` is passed explicitly to deliberately
    preserve a known-divergent research fixture -- it is then imported
    with ``quarantined=True``, always fails golden validation, and is
    never counted as passing category coverage."""
    if upstream_tree_attestation.commit_sha != upstream_commit:
        raise RealChainFixtureError(
            f"{category!r}: upstream_commit {upstream_commit!r} does not match the supplied tree "
            f"attestation's own commit_sha {upstream_tree_attestation.commit_sha!r} -- the "
            "attestation was captured against a different commit than declared (Phase 1 "
            "remediation round 6, finding #3)"
        )

    original_bytes = input_path.read_bytes()
    original_sha256 = hashlib.sha256(original_bytes).hexdigest()
    upstream_git_blob_sha1 = _git_blob_sha1(original_bytes)
    if upstream_git_blob_sha1 != upstream_tree_attestation.blob_sha1:
        raise RealChainFixtureError(
            f"{category!r}: raw input bytes hash to git blob {upstream_git_blob_sha1!r}, "
            f"which does not match the supplied tree attestation's blob "
            f"{upstream_tree_attestation.blob_sha1!r} -- the attestation was captured "
            "against different bytes than --input actually contains"
        )

    license_sha256 = hashlib.sha256(license_bytes).hexdigest()
    if license_sha256 != upstream_license.bytes_sha256:
        raise RealChainFixtureError(
            f"{category!r}: license_bytes hash to {license_sha256!r}, which does not match "
            f"upstream_license.bytes_sha256={upstream_license.bytes_sha256!r}"
        )

    payload, sanitized_bytes, transform_manifest = _run_transform_pipeline(original_bytes)
    sanitized_sha256 = hashlib.sha256(sanitized_bytes).hexdigest()

    transaction = payload["transaction"]
    signature: str = transaction["signatures"][0]
    slot = int(payload["slot"])
    transaction_version = str(payload.get("version", "legacy"))

    wallet_address = expectation.wallet_perspective.wallet_address
    if not _wallet_appears_in_payload(payload, wallet_address):
        raise RealChainFixtureError(
            f"{category!r}: expectation.wallet_perspective.wallet_address {wallet_address!r} does "
            "not appear anywhere in the rebuilt payload (neither transaction.message.accountKeys "
            "nor any preTokenBalances/postTokenBalances owner) -- the reviewed wallet identity "
            "must correspond to something real in the transaction, not an arbitrary string "
            "(Phase 1 remediation round 6, finding #3)"
        )
    parsed: ParsedTransaction = parse_transaction(
        payload, wallet_address=wallet_address, slot=slot, block_time=None
    )
    observed_deltas = compute_asset_deltas(payload, wallet_address)
    observed_deltas_expected_shape = tuple(
        ExpectedAssetDelta(
            mint=d.asset,
            account_context=None,
            raw_amount=d.amount_raw,
            decimals=d.decimals,
            ui_amount=str(_scaled(d.amount_raw, d.decimals)),
        )
        for d in observed_deltas
    )
    observed_account_deltas_expected_shape = _account_deltas_expected_shape(payload, wallet_address)

    mismatches = _diff_expectation(
        expectation=expectation,
        parsed=parsed,
        raw_payload=payload,
        observed_deltas=observed_deltas_expected_shape,
        observed_account_deltas=observed_account_deltas_expected_shape,
    )
    if mismatches and quarantine_reason is None:
        raise RealChainFixtureError(
            f"{category!r}: parser output disagrees with the independent expectation on "
            f"{', '.join(mismatches)}. Either the expectation is wrong, or the parser has a "
            "bug -- refusing to import a fixture whose expectation was never actually "
            "reviewed against what the parser produces. Pass quarantine_reason= explicitly "
            "to deliberately preserve a known-divergent research fixture (it will always "
            "fail golden validation and never count as passing category coverage)."
        )

    fixtures_dir.mkdir(parents=True, exist_ok=True)
    (fixtures_dir / f"{category}.json").write_bytes(sanitized_bytes)
    sources_dir = _sources_dir(fixtures_dir)
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / f"{upstream_git_blob_sha1}.source.json").write_bytes(original_bytes)
    licenses_dir = _licenses_dir(fixtures_dir)
    licenses_dir.mkdir(parents=True, exist_ok=True)
    (licenses_dir / f"{upstream_license.tree_attestation.blob_sha1}.license").write_bytes(
        license_bytes
    )

    evidence_chain_hash = compute_evidence_chain_hash(
        upstream_repo=upstream_repo,
        upstream_commit=upstream_commit,
        upstream_path=upstream_tree_attestation.path,
        upstream_path_note=upstream_path_note,
        upstream_tree_attestation=upstream_tree_attestation,
        upstream_license=upstream_license,
        upstream_git_blob_sha1=upstream_git_blob_sha1,
        original_sha256=original_sha256,
        sanitized_sha256=sanitized_sha256,
        transform_manifest=transform_manifest,
        expectation=expectation,
        quarantined=quarantine_reason is not None,
        quarantine_reason=quarantine_reason,
    )

    record = RealChainFixtureRecord(
        category=category,
        chain="solana",
        signature=signature,
        slot=slot,
        transaction_version=transaction_version,
        upstream_repo=upstream_repo,
        upstream_commit=upstream_commit,
        upstream_path=upstream_tree_attestation.path,
        upstream_path_note=upstream_path_note,
        upstream_tree_attestation=upstream_tree_attestation,
        upstream_license=upstream_license,
        upstream_git_blob_sha1=upstream_git_blob_sha1,
        original_sha256=original_sha256,
        sanitized_sha256=sanitized_sha256,
        transform_manifest=transform_manifest,
        observed_classification=parsed.classification,
        observed_confidence=str(parsed.confidence),
        observed_is_copy_eligible=parsed.is_copy_eligible,
        expectation=expectation,
        quarantined=quarantine_reason is not None,
        quarantine_reason=quarantine_reason,
        evidence_chain_hash=evidence_chain_hash,
        parser_version=parsed.parser_version,
        imported_at=(clock or Clock()).utc_now().isoformat(),
    )

    records = load_provenance(fixtures_dir)
    records[category] = record
    _write_provenance(records, fixtures_dir)
    return record


def _scaled(raw_amount: int, decimals: int) -> str:
    from decimal import Decimal

    return str(Decimal(raw_amount).scaleb(-decimals))


def _wallet_appears_in_payload(payload: dict[str, Any], wallet_address: str) -> bool:
    """Whether ``wallet_address`` corresponds to something real in
    ``payload`` -- either a top-level ``accountKeys`` entry, or the
    ``owner`` of some pre/postTokenBalances entry -- rather than an
    arbitrary string never referenced by the transaction at all (Phase 1
    remediation round 6, finding #3: binds the reviewed wallet
    perspective's *identity*, not only its claimed deltas)."""
    if wallet_address in _account_keys(payload.get("transaction", {}).get("message", {})):
        return True
    meta = payload.get("meta", {})
    for entry in (meta.get("preTokenBalances") or []) + (meta.get("postTokenBalances") or []):
        if entry.get("owner") == wallet_address:
            return True
    return False


def _account_deltas_expected_shape(
    payload: dict[str, Any], wallet_address: str
) -> tuple[ExpectedAccountAssetDelta, ...]:
    """Runs :func:`argus.parsing.generic_parser.compute_account_level_deltas`
    and reshapes its output into :class:`ExpectedAccountAssetDelta` for
    direct comparison against an independent expectation's
    ``account_deltas`` (Phase 1 remediation round 6, finding #3)."""
    return tuple(
        ExpectedAccountAssetDelta(
            account_identifier=d.account_identifier,
            account_index=d.account_index,
            owner=d.owner,
            mint=d.mint,
            pre_raw_amount=d.pre_raw_amount,
            post_raw_amount=d.post_raw_amount,
            net_raw_delta=d.net_raw_delta,
            decimals=d.decimals,
            ui_delta=d.ui_delta,
        )
        for d in compute_account_level_deltas(payload, wallet_address)
    )


def _diff_expectation(
    *,
    expectation: ExpectedOutcome,
    parsed: ParsedTransaction,
    raw_payload: dict[str, Any],
    observed_deltas: tuple[ExpectedAssetDelta, ...],
    observed_account_deltas: tuple[ExpectedAccountAssetDelta, ...],
) -> list[str]:
    """Every field :func:`import_real_chain_fixture`/
    :func:`validate_real_chain_fixtures` compare the independent
    expectation against -- returns the names of every field that
    disagrees (empty if none). Comparing every applicable canonical
    field, not only classification/confidence, is finding #1's central
    requirement; comparing ``account_deltas`` (round 6, finding #3) is
    what actually proves multiple-token-account/LP-style evidence, which
    by-mint ``asset_deltas`` alone can silently erase."""
    mismatches: list[str] = []
    if parsed.classification != expectation.classification:
        mismatches.append("classification")
    if parsed.is_copy_eligible != expectation.is_copy_eligible:
        mismatches.append("is_copy_eligible")
    if parsed.input_mint != expectation.expected_input_mint:
        mismatches.append("input_mint")
    if parsed.input_amount_raw != expectation.expected_input_amount_raw:
        mismatches.append("input_amount_raw")
    if parsed.output_mint != expectation.expected_output_mint:
        mismatches.append("output_mint")
    if parsed.output_amount_raw != expectation.expected_output_amount_raw:
        mismatches.append("output_amount_raw")
    if parsed.network_fee_raw != expectation.network_fee_raw:
        mismatches.append("network_fee_raw")
    transaction_failed = raw_payload["meta"].get("err") is not None
    if transaction_failed != expectation.transaction_failed:
        mismatches.append("transaction_failed")
    if str(parsed.confidence) != expectation.expected_confidence:
        mismatches.append("expected_confidence")
    if observed_deltas != expectation.asset_deltas:
        mismatches.append("asset_deltas")
    if observed_account_deltas != expectation.account_deltas:
        mismatches.append("account_deltas")
    return mismatches


def _check_record_identity(
    record: RealChainFixtureRecord, rebuilt_payload: dict[str, Any], *, category: str
) -> str | None:
    """Binds and validates the record identity fields that can otherwise
    silently drift from the rebuilt payload -- category, chain,
    transaction signature, slot, transaction version, and upstream path
    (Phase 1 remediation round 6, finding #3). Every one of these is
    recomputed from ``rebuilt_payload`` (or, for ``upstream_path``, the
    already offline-verified tree attestation) and checked against the
    stored record, never merely fed back into the parser as a trusted
    input. Returns ``None`` if every field agrees, else a description of
    the first divergence found."""
    if record.category != category:
        return f"record.category {record.category!r} does not match its own provenance key {category!r}"
    if record.chain != "solana":
        return f"record.chain {record.chain!r} is not 'solana'"

    transaction = rebuilt_payload.get("transaction")
    if not isinstance(transaction, dict):
        return "rebuilt_payload is missing a 'transaction' object"
    signatures = transaction.get("signatures")
    if not isinstance(signatures, list) or not signatures or not isinstance(signatures[0], str):
        return "rebuilt_payload.transaction.signatures[0] is missing or not a string"
    rebuilt_signature = signatures[0]
    if rebuilt_signature != record.signature:
        return (
            f"record.signature {record.signature!r} does not match the rebuilt payload's own "
            f"signature {rebuilt_signature!r}"
        )

    try:
        rebuilt_slot = int(rebuilt_payload["slot"])
    except (KeyError, TypeError, ValueError):
        return "rebuilt_payload.slot is missing or not an integer"
    if rebuilt_slot != record.slot:
        return f"record.slot {record.slot} does not match the rebuilt payload's own slot {rebuilt_slot}"

    rebuilt_version = str(rebuilt_payload.get("version", "legacy"))
    if rebuilt_version != record.transaction_version:
        return (
            f"record.transaction_version {record.transaction_version!r} does not match the "
            f"rebuilt payload's own version {rebuilt_version!r}"
        )

    if record.upstream_path != record.upstream_tree_attestation.path:
        return (
            f"record.upstream_path {record.upstream_path!r} does not match the offline-verified "
            f"tree attestation's own path {record.upstream_tree_attestation.path!r}"
        )
    return None


@dataclasses.dataclass(frozen=True, slots=True)
class RealChainFixtureValidationResult:
    category: str
    ok: bool
    detail: str
    quarantined: bool = False


def validate_real_chain_fixtures(
    fixtures_dir: Path = DEFAULT_REAL_FIXTURES_DIR,
) -> list[RealChainFixtureValidationResult]:
    """Re-verifies every currently-imported real-chain fixture by
    independently rebuilding it from scratch, entirely offline:

    1. The preserved raw source bytes still exist, still hash to the
       recorded ``original_sha256``, and still have the recorded
       ``upstream_git_blob_sha1``.
    2. The preserved upstream tree attestation is internally
       self-consistent (its structured fields match a fresh re-parse of
       its own raw ``git ls-tree`` line) and its blob SHA matches
       ``upstream_git_blob_sha1`` (Phase 1 remediation round 5, finding
       #2) -- this is an offline consistency check, not a re-fetch; it
       cannot prove the upstream ref still resolves the same way today.
    3. The preserved license bytes exist, hash to the recorded
       ``bytes_sha256``, and the license's own tree attestation is
       self-consistent the same way.
    4. Replaying the transform pipeline on the preserved raw bytes
       reproduces the exact same transform manifest recorded at import
       time, and the freshly-rebuilt sanitized bytes are byte-identical
       to the committed fixture file on disk.
    5. The combined ``evidence_chain_hash`` re-derives to the same value
       from the record's current content -- catching a partial edit to
       any single covered field.
    6. The parser's current output still agrees with the independent
       expectation on every applicable canonical field (finding #1) --
       not only classification/confidence.

    A ``quarantined`` fixture always reports ``ok=False`` (it is known,
    recorded, divergent research evidence, never a passing category) but
    is distinguished via ``quarantined=True`` in the result so a
    consumer can render it differently from a genuine regression.

    Returns an empty list when no real-chain fixtures are imported yet --
    that is itself the honest, currently-expected state, not a
    validation failure."""
    results: list[RealChainFixtureValidationResult] = []
    sources_dir = _sources_dir(fixtures_dir)
    licenses_dir = _licenses_dir(fixtures_dir)
    for category, record in sorted(load_provenance(fixtures_dir).items()):
        fixture_path = fixtures_dir / f"{category}.json"
        source_path = sources_dir / f"{record.upstream_git_blob_sha1}.source.json"
        quarantined = record.quarantined

        def _fail(
            detail: str, *, _category: str = category, _quarantined: bool = quarantined
        ) -> RealChainFixtureValidationResult:
            return RealChainFixtureValidationResult(
                category=_category, ok=False, detail=detail, quarantined=_quarantined
            )

        if not source_path.exists():
            results.append(_fail(f"preserved raw source missing: {source_path}"))
            continue
        if not fixture_path.exists():
            results.append(_fail(f"fixture file missing: {fixture_path}"))
            continue

        raw_bytes = source_path.read_bytes()
        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        if raw_sha256 != record.original_sha256:
            results.append(
                _fail(
                    f"raw source hash mismatch: recorded {record.original_sha256}, "
                    f"current {raw_sha256}"
                )
            )
            continue
        actual_blob_sha1 = _git_blob_sha1(raw_bytes)
        if actual_blob_sha1 != record.upstream_git_blob_sha1:
            results.append(
                _fail(
                    "git blob SHA-1 mismatch: recorded "
                    f"{record.upstream_git_blob_sha1}, current {actual_blob_sha1}"
                )
            )
            continue

        tree_check = verify_git_object_chain(record.upstream_tree_attestation)
        if tree_check is not None:
            results.append(_fail(f"upstream tree object chain invalid: {tree_check}"))
            continue
        if record.upstream_tree_attestation.commit_sha != record.upstream_commit:
            results.append(
                _fail(
                    "upstream tree attestation commit_sha "
                    f"{record.upstream_tree_attestation.commit_sha} does not match "
                    f"upstream_commit {record.upstream_commit}"
                )
            )
            continue
        if record.upstream_tree_attestation.blob_sha1 != record.upstream_git_blob_sha1:
            results.append(
                _fail(
                    "upstream tree attestation blob SHA "
                    f"{record.upstream_tree_attestation.blob_sha1} does not match "
                    f"upstream_git_blob_sha1 {record.upstream_git_blob_sha1}"
                )
            )
            continue

        license_check = verify_git_object_chain(record.upstream_license.tree_attestation)
        if license_check is not None:
            results.append(_fail(f"license tree object chain invalid: {license_check}"))
            continue
        license_path = (
            licenses_dir / f"{record.upstream_license.tree_attestation.blob_sha1}.license"
        )
        if not license_path.exists():
            results.append(_fail(f"preserved license bytes missing: {license_path}"))
            continue
        license_bytes = license_path.read_bytes()
        license_sha256 = hashlib.sha256(license_bytes).hexdigest()
        if license_sha256 != record.upstream_license.bytes_sha256:
            results.append(
                _fail(
                    "license bytes hash mismatch: recorded "
                    f"{record.upstream_license.bytes_sha256}, current {license_sha256}"
                )
            )
            continue

        try:
            rebuilt_payload, rebuilt_bytes, rebuilt_manifest = _run_transform_pipeline(raw_bytes)
        except RealChainFixtureError as exc:
            results.append(_fail(f"rebuild from preserved source failed: {exc}"))
            continue

        if rebuilt_manifest != record.transform_manifest:
            results.append(_fail("transform manifest diverged from a fresh rebuild"))
            continue

        identity_mismatch = _check_record_identity(record, rebuilt_payload, category=category)
        if identity_mismatch is not None:
            results.append(_fail(identity_mismatch))
            continue

        current_fixture_bytes = fixture_path.read_bytes()
        if rebuilt_bytes != current_fixture_bytes:
            results.append(
                _fail(
                    "rebuilt sanitized bytes do not match the committed fixture file "
                    "-- the fixture file was modified outside the import pipeline"
                )
            )
            continue
        current_sha256 = hashlib.sha256(current_fixture_bytes).hexdigest()
        if current_sha256 != record.sanitized_sha256:
            results.append(
                _fail(
                    f"sanitized hash mismatch: recorded {record.sanitized_sha256}, "
                    f"current {current_sha256}"
                )
            )
            continue

        recomputed_chain_hash = compute_evidence_chain_hash(
            upstream_repo=record.upstream_repo,
            upstream_commit=record.upstream_commit,
            upstream_path=record.upstream_path,
            upstream_path_note=record.upstream_path_note,
            upstream_tree_attestation=record.upstream_tree_attestation,
            upstream_license=record.upstream_license,
            upstream_git_blob_sha1=record.upstream_git_blob_sha1,
            original_sha256=record.original_sha256,
            sanitized_sha256=record.sanitized_sha256,
            transform_manifest=record.transform_manifest,
            expectation=record.expectation,
            quarantined=record.quarantined,
            quarantine_reason=record.quarantine_reason,
        )
        if recomputed_chain_hash != record.evidence_chain_hash:
            results.append(
                _fail(
                    "evidence chain hash mismatch -- some covered field (upstream identity, "
                    "attestation, license, transform manifest, or expectation) was edited "
                    "without recomputing the chain hash: recorded "
                    f"{record.evidence_chain_hash}, current {recomputed_chain_hash}"
                )
            )
            continue

        if quarantined:
            results.append(
                RealChainFixtureValidationResult(
                    category=category,
                    ok=False,
                    detail=f"quarantined research fixture: {record.quarantine_reason}",
                    quarantined=True,
                )
            )
            continue

        wallet_address = record.expectation.wallet_perspective.wallet_address
        if not _wallet_appears_in_payload(rebuilt_payload, wallet_address):
            results.append(
                _fail(
                    f"expectation wallet_address {wallet_address!r} does not appear anywhere in "
                    "the rebuilt payload"
                )
            )
            continue
        parsed = parse_transaction(
            rebuilt_payload, wallet_address=wallet_address, slot=record.slot, block_time=None
        )
        observed_deltas = compute_asset_deltas(rebuilt_payload, wallet_address)
        observed_deltas_expected_shape = tuple(
            ExpectedAssetDelta(
                mint=d.asset,
                account_context=None,
                raw_amount=d.amount_raw,
                decimals=d.decimals,
                ui_amount=_scaled(d.amount_raw, d.decimals),
            )
            for d in observed_deltas
        )
        observed_account_deltas_expected_shape = _account_deltas_expected_shape(
            rebuilt_payload, wallet_address
        )
        mismatches = _diff_expectation(
            expectation=record.expectation,
            parsed=parsed,
            raw_payload=rebuilt_payload,
            observed_deltas=observed_deltas_expected_shape,
            observed_account_deltas=observed_account_deltas_expected_shape,
        )
        if mismatches:
            results.append(
                _fail(
                    f"parser output disagrees with the independent expectation on: "
                    f"{', '.join(mismatches)}"
                )
            )
            continue
        results.append(RealChainFixtureValidationResult(category=category, ok=True, detail="ok"))
    return results


def _tree_attestation_from_dict(data: dict[str, Any]) -> GitTreeAttestation:
    data = dict(data)
    data["path_components"] = tuple(data["path_components"])
    data["tree_object_chain_b64"] = tuple(data["tree_object_chain_b64"])
    return GitTreeAttestation(**data)


def _license_evidence_from_dict(data: dict[str, Any]) -> LicenseEvidence:
    data = dict(data)
    data["tree_attestation"] = _tree_attestation_from_dict(data["tree_attestation"])
    return LicenseEvidence(**data)


def _expectation_from_dict(data: dict[str, Any]) -> ExpectedOutcome:
    data = dict(data)
    data["wallet_perspective"] = WalletPerspective(**data["wallet_perspective"])
    data["asset_deltas"] = tuple(ExpectedAssetDelta(**d) for d in data["asset_deltas"])
    data["account_deltas"] = tuple(ExpectedAccountAssetDelta(**d) for d in data["account_deltas"])
    reviewer = dict(data["reviewer"])
    reviewer["evidence_refs"] = tuple(reviewer["evidence_refs"])
    data["reviewer"] = ReviewerEvidence(**reviewer)
    return ExpectedOutcome(**data)


def import_real_chain_fixture_from_evidence_file(
    *,
    input_path: Path,
    evidence_path: Path,
    license_bytes_path: Path,
    fixtures_dir: Path = DEFAULT_REAL_FIXTURES_DIR,
    clock: Clock | None = None,
) -> RealChainFixtureRecord:
    """CLI-friendly wrapper around :func:`import_real_chain_fixture`:
    the new schema's nested typed evidence (tree attestations, license
    evidence, the full independent expectation) is impractical to pass
    as individual command-line flags, so ``evidence_path`` names a single
    JSON file bundling all of it -- see
    ``tests/golden/fixtures/real/EVIDENCE_FILE_SCHEMA.md`` for the exact
    shape. ``license_bytes_path`` is the exact preserved license file
    bytes (hashed and checked against ``upstream_license.bytes_sha256``
    in the evidence file)."""
    evidence = json.loads(evidence_path.read_text())
    return import_real_chain_fixture(
        input_path=input_path,
        category=evidence["category"],
        upstream_repo=evidence["upstream_repo"],
        upstream_commit=evidence["upstream_commit"],
        upstream_path_note=evidence["upstream_path_note"],
        upstream_tree_attestation=_tree_attestation_from_dict(
            evidence["upstream_tree_attestation"]
        ),
        upstream_license=_license_evidence_from_dict(evidence["upstream_license"]),
        license_bytes=license_bytes_path.read_bytes(),
        expectation=_expectation_from_dict(evidence["expectation"]),
        quarantine_reason=evidence.get("quarantine_reason"),
        fixtures_dir=fixtures_dir,
        clock=clock,
    )
