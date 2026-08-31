"""Tests for argus.golden_fixtures (Phase 1 remediation round 2, finding
#12): the offline real-chain fixture import/validation tool itself.

These tests prove the TOOL works correctly using a self-authored,
clearly-synthetic input payload -- they are not, and must never be read
as, a real-chain fixture. Every test here writes into a pytest ``tmp_path``
directory, never into the committed ``tests/golden/fixtures/real/``
directory, so the tool's own test coverage can never be mistaken for an
actual imported real-chain fixture.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from argus.clock import Clock
from argus.golden_fixtures import (
    RealChainFixtureError,
    import_real_chain_fixture,
    load_provenance,
    validate_real_chain_fixtures,
)

# Deliberately shaped like a real Solana getTransaction RPC response, but
# every address/signature is a clearly-fake placeholder -- this exercises
# the tool's own logic, not a claim of authenticity.
_TOOL_TEST_PAYLOAD: dict = {
    "slot": 123456789,
    "version": "legacy",
    "transaction": {
        "signatures": ["ToolSelfTestSignatureNotReal1111111111111111111111111111111111111"],
        "message": {
            "accountKeys": [
                "ToolSelfTestWalletNotReal11111111111111111",
                "ToolSelfTestCounterpartyNotReal111111111111",
            ],
            "header": {
                "numReadonlySignedAccounts": 0,
                "numReadonlyUnsignedAccounts": 1,
                "numRequiredSignatures": 1,
            },
            "instructions": [],
            "recentBlockhash": "ToolSelfTestBlockhashNotReal111111111111111",
        },
    },
    "meta": {
        "fee": 5000,
        "preBalances": [2_000_000_000, 0],
        "postBalances": [1_000_000_000, 995_000_000],
        "status": {"Ok": None},
        "err": None,
    },
}


def _write_payload(tmp_path: Path, payload: dict = _TOOL_TEST_PAYLOAD) -> Path:
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload))
    return input_path


def _fixed_clock() -> Clock:
    class _Frozen(Clock):
        def utc_now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    return _Frozen()


def test_import_validates_and_records_full_provenance(tmp_path: Path) -> None:
    input_path = _write_payload(tmp_path)
    fixtures_dir = tmp_path / "real"

    record = import_real_chain_fixture(
        input_path=input_path,
        category="tool_self_test",
        upstream_repo="example-org/example-repo",
        upstream_commit="a" * 40,
        upstream_path="tests/example.json",
        upstream_license="MIT",
        fixtures_dir=fixtures_dir,
        clock=_fixed_clock(),
    )

    assert record.category == "tool_self_test"
    assert record.chain == "solana"
    assert record.signature == "ToolSelfTestSignatureNotReal1111111111111111111111111111111111111"
    assert record.slot == 123456789
    assert record.transaction_version == "legacy"
    assert record.upstream_repo == "example-org/example-repo"
    assert record.upstream_commit == "a" * 40
    assert record.upstream_license == "MIT"
    # Defaulted to accountKeys[0] since no --wallet-address was given.
    assert record.wallet_address == "ToolSelfTestWalletNotReal11111111111111111"
    assert record.imported_at == "2026-01-01T00:00:00+00:00"
    assert record.sanitization_transform == (
        "canonicalized JSON formatting only (no envelope to unwrap)"
    )

    # The fixture file and provenance.json were both written.
    fixture_path = fixtures_dir / "tool_self_test.json"
    assert fixture_path.exists()
    on_disk = json.loads(fixture_path.read_text())
    assert on_disk == _TOOL_TEST_PAYLOAD

    provenance = load_provenance(fixtures_dir)
    assert provenance == {"tool_self_test": record}

    # PROVENANCE.md was rendered and mentions the category and signature.
    markdown = (fixtures_dir / "PROVENANCE.md").read_text()
    assert "tool_self_test" in markdown
    assert record.signature in markdown


def test_import_computes_expected_classification_by_actually_parsing(tmp_path: Path) -> None:
    """The recorded expected_classification/confidence must come from
    actually running the real parser, not be hand-asserted -- this proves
    it, by comparing against a direct call to parse_transaction."""
    from argus.parsing.generic_parser import parse_transaction

    input_path = _write_payload(tmp_path)
    record = import_real_chain_fixture(
        input_path=input_path,
        category="tool_self_test",
        upstream_repo="example-org/example-repo",
        upstream_commit="a" * 40,
        upstream_path="tests/example.json",
        upstream_license="MIT",
        fixtures_dir=tmp_path / "real",
    )

    directly = parse_transaction(
        _TOOL_TEST_PAYLOAD,
        wallet_address="ToolSelfTestWalletNotReal11111111111111111",
        slot=123456789,
        block_time=None,
    )
    assert record.expected_classification == directly.classification
    assert record.expected_confidence == str(directly.confidence)
    assert record.parser_version == directly.parser_version


def test_import_honors_explicit_wallet_address_override(tmp_path: Path) -> None:
    record = import_real_chain_fixture(
        input_path=_write_payload(tmp_path),
        category="tool_self_test",
        upstream_repo="example-org/example-repo",
        upstream_commit="a" * 40,
        upstream_path="tests/example.json",
        upstream_license="MIT",
        wallet_address="ToolSelfTestCounterpartyNotReal111111111111",
        fixtures_dir=tmp_path / "real",
    )
    assert record.wallet_address == "ToolSelfTestCounterpartyNotReal111111111111"


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ("not json at all", "not valid JSON"),
        (json.dumps([1, 2, 3]), "expected a JSON object"),
        (json.dumps({"meta": {}, "slot": 1}), "missing required key 'transaction'"),
        (json.dumps({"transaction": {}, "slot": 1}), "missing required key 'meta'"),
        (json.dumps({"transaction": {}, "meta": {}}), "missing required key 'slot'"),
        (
            json.dumps({"transaction": {"message": {}}, "meta": {}, "slot": 1}),
            "missing 'signatures'",
        ),
        (
            json.dumps({"transaction": {"signatures": []}, "meta": {}, "slot": 1}),
            "non-empty string",
        ),
        (
            json.dumps({"transaction": {"signatures": [123]}, "meta": {}, "slot": 1}),
            "non-empty string",
        ),
        (
            json.dumps(
                {"transaction": {"signatures": ["sig"]}, "meta": "not an object", "slot": 1}
            ),
            "must be an object",
        ),
    ],
)
def test_import_rejects_malformed_input(tmp_path: Path, payload: str, match: str) -> None:
    input_path = tmp_path / "input.json"
    input_path.write_text(payload)

    with pytest.raises(RealChainFixtureError, match=match):
        import_real_chain_fixture(
            input_path=input_path,
            category="tool_self_test",
            upstream_repo="example-org/example-repo",
            upstream_commit="a" * 40,
            upstream_path="tests/example.json",
            upstream_license="MIT",
            fixtures_dir=tmp_path / "real",
        )


def test_import_rejects_when_no_wallet_address_available(tmp_path: Path) -> None:
    payload = {
        "transaction": {"signatures": ["sig"], "message": {"accountKeys": []}},
        "meta": {},
        "slot": 1,
    }
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload))

    with pytest.raises(RealChainFixtureError, match="no wallet_address"):
        import_real_chain_fixture(
            input_path=input_path,
            category="tool_self_test",
            upstream_repo="example-org/example-repo",
            upstream_commit="a" * 40,
            upstream_path="tests/example.json",
            upstream_license="MIT",
            fixtures_dir=tmp_path / "real",
        )


def test_import_unwraps_a_raw_json_rpc_envelope(tmp_path: Path) -> None:
    """A payload captured via a raw curl/RPC call is the full
    {"jsonrpc": "2.0", "result": {...}, "id": 1} envelope, not just the
    `result` object every fixture in this project stores -- the import
    tool must detect and unwrap that automatically rather than rejecting
    a perfectly genuine capture on a technicality."""
    wrapped = {"jsonrpc": "2.0", "id": 1, "result": _TOOL_TEST_PAYLOAD}
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(wrapped))
    fixtures_dir = tmp_path / "real"

    record = import_real_chain_fixture(
        input_path=input_path,
        category="tool_self_test",
        upstream_repo="example-org/example-repo",
        upstream_commit="a" * 40,
        upstream_path="tests/example.json",
        upstream_license="MIT",
        fixtures_dir=fixtures_dir,
    )

    assert record.signature == "ToolSelfTestSignatureNotReal1111111111111111111111111111111111111"
    assert record.sanitization_transform == (
        "unwrapped JSON-RPC envelope down to `result`; canonicalized JSON formatting"
    )
    # original_sha256 is of the envelope bytes exactly as captured; the
    # fixture file on disk is the unwrapped, canonicalized `result` only.
    assert record.original_sha256 == hashlib.sha256(json.dumps(wrapped).encode("utf-8")).hexdigest()
    on_disk = json.loads((fixtures_dir / "tool_self_test.json").read_text())
    assert on_disk == _TOOL_TEST_PAYLOAD


def test_import_does_not_unwrap_when_top_level_already_looks_like_a_transaction(
    tmp_path: Path,
) -> None:
    """A getTransaction-shaped payload that happens to also carry a
    'result' key at the top level (unusual, but not impossible for a
    hand-edited or re-wrapped file) must not be misinterpreted as an
    envelope -- unwrapping only applies when the top level does NOT
    already have transaction/meta/slot."""
    payload_with_stray_result_key = dict(_TOOL_TEST_PAYLOAD)
    payload_with_stray_result_key["result"] = {"unrelated": "data"}
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload_with_stray_result_key))

    record = import_real_chain_fixture(
        input_path=input_path,
        category="tool_self_test",
        upstream_repo="example-org/example-repo",
        upstream_commit="a" * 40,
        upstream_path="tests/example.json",
        upstream_license="MIT",
        fixtures_dir=tmp_path / "real",
    )
    assert record.sanitization_transform == (
        "canonicalized JSON formatting only (no envelope to unwrap)"
    )


def test_validate_reports_empty_list_when_nothing_imported(tmp_path: Path) -> None:
    assert validate_real_chain_fixtures(tmp_path / "real") == []


def test_validate_passes_for_a_freshly_imported_untouched_fixture(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "real"
    import_real_chain_fixture(
        input_path=_write_payload(tmp_path),
        category="tool_self_test",
        upstream_repo="example-org/example-repo",
        upstream_commit="a" * 40,
        upstream_path="tests/example.json",
        upstream_license="MIT",
        fixtures_dir=fixtures_dir,
    )

    results = validate_real_chain_fixtures(fixtures_dir)
    assert len(results) == 1
    assert results[0].category == "tool_self_test"
    assert results[0].ok is True


def test_validate_detects_a_tampered_fixture_file(tmp_path: Path) -> None:
    """Hash-drift detection: if the fixture file's bytes change after
    import without going through the import command again, validation
    must fail loudly, not silently keep trusting stale provenance."""
    fixtures_dir = tmp_path / "real"
    import_real_chain_fixture(
        input_path=_write_payload(tmp_path),
        category="tool_self_test",
        upstream_repo="example-org/example-repo",
        upstream_commit="a" * 40,
        upstream_path="tests/example.json",
        upstream_license="MIT",
        fixtures_dir=fixtures_dir,
    )

    tampered = dict(_TOOL_TEST_PAYLOAD)
    tampered["slot"] = 999
    (fixtures_dir / "tool_self_test.json").write_text(json.dumps(tampered))

    results = validate_real_chain_fixtures(fixtures_dir)
    assert len(results) == 1
    assert results[0].ok is False
    assert "hash mismatch" in results[0].detail


def test_validate_detects_a_parser_regression_against_a_real_fixture(tmp_path: Path) -> None:
    """If the parser's output for a previously-imported fixture no longer
    matches what was recorded at import time, validation must fail --
    the same "golden fixture output changes until reviewed" discipline
    the synthetic fixtures already enforce."""
    fixtures_dir = tmp_path / "real"
    import_real_chain_fixture(
        input_path=_write_payload(tmp_path),
        category="tool_self_test",
        upstream_repo="example-org/example-repo",
        upstream_commit="a" * 40,
        upstream_path="tests/example.json",
        upstream_license="MIT",
        fixtures_dir=fixtures_dir,
    )

    # Simulate a parser regression by corrupting the recorded expectation
    # directly in provenance.json (never hand-editing the fixture itself).
    provenance_path = fixtures_dir / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["tool_self_test"]["expected_classification"] = "SWAP_SIMPLE"
    provenance_path.write_text(json.dumps(provenance))

    results = validate_real_chain_fixtures(fixtures_dir)
    assert len(results) == 1
    assert results[0].ok is False
    assert "parser output changed" in results[0].detail


def test_reimporting_the_same_category_overwrites_its_record(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "real"
    first = import_real_chain_fixture(
        input_path=_write_payload(tmp_path),
        category="tool_self_test",
        upstream_repo="example-org/example-repo",
        upstream_commit="a" * 40,
        upstream_path="tests/example.json",
        upstream_license="MIT",
        fixtures_dir=fixtures_dir,
    )

    other_payload = dict(_TOOL_TEST_PAYLOAD)
    other_payload["slot"] = 42
    second = import_real_chain_fixture(
        input_path=_write_payload(tmp_path, other_payload),
        category="tool_self_test",
        upstream_repo="example-org/example-repo",
        upstream_commit="b" * 40,
        upstream_path="tests/example.json",
        upstream_license="MIT",
        fixtures_dir=fixtures_dir,
    )

    assert first.slot != second.slot
    provenance = load_provenance(fixtures_dir)
    assert len(provenance) == 1
    assert provenance["tool_self_test"] == second


def test_real_fixtures_directory_currently_has_10_genuinely_imported_fixtures() -> None:
    """Regression guard on the honest current state. Round 2 (finding
    #12) found `solana-labs/explorer` (MIT-licensed) embedding genuine
    captured mainnet `getTransaction` payloads with their own upstream
    `mainnet-*` naming/typing distinguishing them from synthetic/devnet/
    local-validator fixtures. Round 3 (argus-phase-1-remediation-003,
    finding #1) found `0xjeffro/tx-parser` (MPL-2.0) embedding genuine
    captured DEX-swap/DCA transactions, named after the exact program
    instruction each one captures -- see
    `tests/golden/fixtures/real/SEARCH_LOG.md` for the full search log
    and which required categories these do and do not satisfy. Two
    categories (multiple token-account/LP-style action, and a genuinely
    failed transaction) remain NOT TESTED. This test intentionally
    targets the real, committed tests/golden/fixtures/real/ directory
    (not a tmp_path) -- it is a regression guard on the fixtures'
    continued internal consistency (hash + parser output), not a claim
    that all required categories are covered."""
    results = validate_real_chain_fixtures()
    assert {r.category for r in results} == {
        "real_mainnet_sol_transfer_single",
        "real_mainnet_sol_transfer_received",
        "real_mainnet_sol_transfer_multi",
        "real_mainnet_usdc_transfer",
        "real_mainnet_sol_to_token_swap",
        "real_mainnet_token_to_sol_swap",
        "real_mainnet_token_to_usdc_swap",
        "real_mainnet_multi_hop_swap",
        "real_mainnet_partial_sell",
        "real_mainnet_ambiguous_multi_asset",
    }
    assert all(r.ok for r in results), results
