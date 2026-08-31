"""Real :class:`argus.providers.helius.client.WebSocketConnector`, backed
by the ``websockets`` library.

Never exercised against a live Helius endpoint in this sandbox (no
network egress) -- every test in this repository uses the fake connector
in ``tests/unit/test_provider_adapters.py`` instead. This module is the
real implementation a live deployment wires in; it is a thin, honest
passthrough (``websockets.connect()`` already satisfies
``WebSocketConnector``/``WebSocketConnection`` structurally -- ``send``/
``recv``/``close`` match exactly), not a mock claiming to be one.
"""

from __future__ import annotations

from typing import Any

import websockets


class WebSocketsConnector:
    """Implements :class:`argus.providers.helius.client.WebSocketConnector`."""

    def connect(self, url: str) -> Any:
        return websockets.connect(url)
