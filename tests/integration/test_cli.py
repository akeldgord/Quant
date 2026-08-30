from __future__ import annotations

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
