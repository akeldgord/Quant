from __future__ import annotations

import json

from typer.testing import CliRunner

from argus.cli import app

runner = CliRunner()


def test_cli_health_runs_and_prints_expected_fields() -> None:
    result = runner.invoke(app, ["health"])

    assert result.exit_code in (0, 1)  # 1 only if a real check legitimately fails
    assert "config_hash:" in result.stdout
    assert "master_spec_hash:" in result.stdout
    assert "LIVE_READY_SOFTWARE: false" in result.stdout
    assert "LIVE_CANARY_PASSED: false" in result.stdout
    assert "LIVE_ARMED: false" in result.stdout


def test_cli_config_show() -> None:
    result = runner.invoke(app, ["config-show"])

    assert result.exit_code == 0
    assert "config_hash:" in result.stdout
    assert "master_spec_hash:" in result.stdout


def test_cli_checkpoint_bundle_writes_file(tmp_path) -> None:
    checkpoint_file = tmp_path / "checkpoint.txt"
    checkpoint_file.write_text("STATUS: PASS\n")

    result = runner.invoke(
        app, ["checkpoint", "bundle", "--phase", "0", "--checkpoint-file", str(checkpoint_file)]
    )

    assert result.exit_code == 0
    assert "wrote" in result.stdout


def test_cli_fixtures_validate_real_chain_default_validates_current_fixtures() -> None:
    """Phase 1 remediation round 2, finding #12: the committed real-chain
    fixtures (see tests/golden/fixtures/real/SEARCH_LOG.md) must still
    validate cleanly via the default (no --fixtures-dir) invocation."""
    result = runner.invoke(app, ["fixtures", "validate-real-chain"])

    assert result.exit_code == 0
    assert "real_mainnet_sol_transfer_single: ok" in result.stdout
    assert "FAIL" not in result.stdout


def _git_blob_sha1(data: bytes) -> str:
    import hashlib

    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324


def _git_object_sha1(object_type: str, content: bytes) -> str:
    import hashlib

    header = f"{object_type} {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()  # noqa: S324


def _attestation(raw_bytes: bytes, path: str) -> dict:
    """A real, independently-recomputable Git object chain -- same
    construction as tests/unit/test_golden_fixtures.py's helper of the
    same purpose (Phase 1 remediation round 6, finding #2), just returning
    a plain JSON-serializable dict here since this is fed straight into a
    CLI evidence file."""
    import base64

    blob_sha1 = _git_blob_sha1(raw_bytes)
    components = path.split("/")
    chain: list[bytes] = []
    current_sha = blob_sha1
    current_mode = "100644"
    for component in reversed(components):
        entry_bytes = f"{current_mode} {component}".encode() + b"\0" + bytes.fromhex(current_sha)
        chain.append(entry_bytes)
        current_sha = _git_object_sha1("tree", entry_bytes)
        current_mode = "40000"
    chain.reverse()
    root_tree_sha = _git_object_sha1("tree", chain[0])
    commit_content = (
        f"tree {root_tree_sha}\n"
        "author Test <test@example.invalid> 1735689600 +0000\n"
        "committer Test <test@example.invalid> 1735689600 +0000\n\n"
        "synthetic test commit\n"
    ).encode()
    commit_sha = _git_object_sha1("commit", commit_content)
    return {
        "commit_sha": commit_sha,
        "commit_object_b64": base64.b64encode(commit_content).decode("ascii"),
        "path": path,
        "path_components": components,
        "tree_object_chain_b64": [base64.b64encode(t).decode("ascii") for t in chain],
        "mode": "100644",
        "blob_sha1": blob_sha1,
        "captured_at": "2026-01-01T00:00:00+00:00",
    }


def test_cli_fixtures_import_real_chain_round_trip(tmp_path) -> None:
    """Phase 1 remediation round 5, findings #1/#2: the CLI's
    --evidence-file/--license-file flow round-trips through
    import-real-chain and validate-real-chain the same way the old
    individual-flag flow did."""
    import hashlib

    payload = {
        "slot": 42,
        "version": "legacy",
        "transaction": {
            "signatures": ["CliRoundTripSignatureNotReal11111111111111111111111111111111111111"],
            "message": {"accountKeys": ["CliRoundTripWalletNotReal1111111111111111111"]},
        },
        "meta": {
            "fee": 5000,
            "preBalances": [2_000_000_000],
            "postBalances": [1_000_000_000],
            "status": {"Ok": None},
            "err": None,
        },
    }
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload))
    fixtures_dir = tmp_path / "real"

    license_bytes = b"MIT License\n\nCopyright (c) 2026 Example Org contributors\n"
    license_path = tmp_path / "LICENSE"
    license_path.write_bytes(license_bytes)

    tree_attestation = _attestation(input_path.read_bytes(), "tests/example.json")
    evidence = {
        "category": "cli_round_trip",
        "upstream_repo": "example-org/example-repo",
        "upstream_commit": tree_attestation["commit_sha"],
        "upstream_path_note": "cli self-test fixture, not a real upstream capture.",
        "upstream_tree_attestation": tree_attestation,
        "upstream_license": {
            "spdx_id": "MIT",
            "path": "LICENSE",
            "tree_attestation": _attestation(license_bytes, "LICENSE"),
            "bytes_sha256": hashlib.sha256(license_bytes).hexdigest(),
            "compatibility_decision": "MIT is fully permissive.",
            "attribution": "Example Org contributors",
        },
        "expectation": {
            "classification": "TRANSFER_OUT",
            "is_copy_eligible": False,
            "wallet_perspective": {
                "wallet_address": "CliRoundTripWalletNotReal1111111111111111111",
                "method": "accountKeys[0] -- the transaction's fee payer.",
            },
            "asset_deltas": [
                {
                    "mint": "SOL",
                    "account_context": None,
                    "raw_amount": -999_995_000,
                    "decimals": 9,
                    "ui_amount": "-0.999995000",
                }
            ],
            "account_deltas": [
                {
                    "account_identifier": "CliRoundTripWalletNotReal1111111111111111111",
                    "account_index": 0,
                    "owner": "CliRoundTripWalletNotReal1111111111111111111",
                    "mint": "SOL",
                    "pre_raw_amount": 2_000_000_000,
                    "post_raw_amount": 1_000_000_000,
                    "net_raw_delta": -999_995_000,
                    "decimals": 9,
                    "ui_delta": "-0.999995000",
                }
            ],
            "expected_input_mint": "SOL",
            "expected_input_amount_raw": 999_995_000,
            "expected_output_mint": None,
            "expected_output_amount_raw": None,
            "network_fee_raw": 5000,
            "transaction_failed": False,
            "expected_confidence": "1.000",
            "confidence_rule": "exact: single-asset pure SOL outflow.",
            "reviewer": {
                "method": "manual review of meta.preBalances/postBalances/fee",
                "rationale": "Only the wallet's own SOL balance moves; a single clean outflow.",
                "evidence_refs": ["cli self-test -- not a real upstream reference"],
            },
        },
        "quarantine_reason": None,
    }
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence))

    import_result = runner.invoke(
        app,
        [
            "fixtures",
            "import-real-chain",
            "--input",
            str(input_path),
            "--evidence-file",
            str(evidence_path),
            "--license-file",
            str(license_path),
            "--fixtures-dir",
            str(fixtures_dir),
        ],
    )
    assert import_result.exit_code == 0, import_result.stdout
    assert "imported 'cli_round_trip'" in import_result.stdout

    validate_result = runner.invoke(
        app, ["fixtures", "validate-real-chain", "--fixtures-dir", str(fixtures_dir)]
    )
    assert validate_result.exit_code == 0, validate_result.stdout
    assert "cli_round_trip" in validate_result.stdout
    assert "ok" in validate_result.stdout


def test_cli_fixtures_import_real_chain_rejects_malformed_input(tmp_path) -> None:
    input_path = tmp_path / "input.json"
    input_path.write_text("not json")

    license_bytes = b"MIT License\n"
    license_path = tmp_path / "LICENSE"
    license_path.write_bytes(license_bytes)

    import hashlib

    tree_attestation = _attestation(input_path.read_bytes(), "tests/example.json")
    evidence: dict = {
        "category": "bad",
        "upstream_repo": "example-org/example-repo",
        "upstream_commit": tree_attestation["commit_sha"],
        "upstream_path_note": "malformed-input self-test.",
        "upstream_tree_attestation": tree_attestation,
        "upstream_license": {
            "spdx_id": "MIT",
            "path": "LICENSE",
            "tree_attestation": _attestation(license_bytes, "LICENSE"),
            "bytes_sha256": hashlib.sha256(license_bytes).hexdigest(),
            "compatibility_decision": "MIT is fully permissive.",
            "attribution": "Example Org contributors",
        },
        "expectation": {
            "classification": "UNKNOWN",
            "is_copy_eligible": False,
            "wallet_perspective": {"wallet_address": "irrelevant", "method": "n/a"},
            "asset_deltas": [],
            "account_deltas": [],
            "expected_input_mint": None,
            "expected_input_amount_raw": None,
            "expected_output_mint": None,
            "expected_output_amount_raw": None,
            "network_fee_raw": 0,
            "transaction_failed": False,
            "expected_confidence": "0.000",
            "confidence_rule": "n/a -- input is malformed, this import must be rejected first.",
            "reviewer": {"method": "n/a", "rationale": "n/a", "evidence_refs": []},
        },
        "quarantine_reason": None,
    }
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence))

    result = runner.invoke(
        app,
        [
            "fixtures",
            "import-real-chain",
            "--input",
            str(input_path),
            "--evidence-file",
            str(evidence_path),
            "--license-file",
            str(license_path),
            "--fixtures-dir",
            str(tmp_path / "real"),
        ],
    )
    assert result.exit_code == 1
    assert "rejected" in result.stdout
