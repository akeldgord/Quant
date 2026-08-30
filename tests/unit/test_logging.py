from __future__ import annotations

import json

from argus.logging import configure_logging, get_logger


def test_configure_logging_json_output_emits_parseable_json(capsys) -> None:
    configure_logging(level="INFO", json_output=True)
    logger = get_logger(component="test")
    logger.info("hello", extra_field=1)

    captured = capsys.readouterr().out.strip().splitlines()
    assert captured, "expected at least one log line"
    payload = json.loads(captured[-1])
    assert payload["event"] == "hello"
    assert payload["component"] == "test"
    assert payload["extra_field"] == 1
    assert payload["level"] == "info"
    assert "timestamp" in payload


def test_configure_logging_is_idempotent() -> None:
    configure_logging(level="DEBUG", json_output=True)
    configure_logging(level="INFO", json_output=False)
    # no exception on reconfiguration; nothing further to assert structurally
