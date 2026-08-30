from __future__ import annotations

from argus.checkpoint import CommandResult, _section, run


def test_run_captures_stdout_and_ok_true_on_success() -> None:
    result = run(["python3", "-c", "print('hello')"])
    assert result.ok is True
    assert "hello" in result.output


def test_run_reports_not_available_for_missing_binary() -> None:
    result = run(["this-binary-does-not-exist-xyz"])
    assert result.ok is False
    assert "not available" in result.output


def test_run_captures_nonzero_exit_as_not_ok() -> None:
    result = run(["python3", "-c", "import sys; sys.exit(1)"])
    assert result.ok is False


def test_section_formats_ok_and_failure_states() -> None:
    ok_result = CommandResult(command="echo hi", output="hi", ok=True)
    text = _section("title", ok_result)
    assert "(ok)" in text
    assert "$ echo hi" in text
    assert "hi" in text

    failed_result = CommandResult(command="false", output="", ok=False)
    text2 = _section("title2", failed_result)
    assert "non-zero exit / unavailable" in text2
    assert "(no output)" in text2
