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


def test_cli_fixtures_import_real_chain_round_trip(tmp_path) -> None:
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

    import_result = runner.invoke(
        app,
        [
            "fixtures",
            "import-real-chain",
            "--input",
            str(input_path),
            "--category",
            "cli_round_trip",
            "--upstream-repo",
            "example-org/example-repo",
            "--upstream-commit",
            "a" * 40,
            "--upstream-path",
            "tests/example.json",
            "--upstream-license",
            "MIT",
            "--expected-classification",
            "TRANSFER_OUT",
            "--expected-confidence",
            "1.000",
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

    result = runner.invoke(
        app,
        [
            "fixtures",
            "import-real-chain",
            "--input",
            str(input_path),
            "--category",
            "bad",
            "--upstream-repo",
            "example-org/example-repo",
            "--upstream-commit",
            "a" * 40,
            "--upstream-path",
            "tests/example.json",
            "--upstream-license",
            "MIT",
            "--expected-classification",
            "UNKNOWN",
            "--expected-confidence",
            "0.000",
            "--fixtures-dir",
            str(tmp_path / "real"),
        ],
    )
    assert result.exit_code == 1
    assert "rejected" in result.stdout
