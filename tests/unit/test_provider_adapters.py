"""Provider adapter tests. Every HTTP call goes through
`httpx.MockTransport` (no real network); the Helius WebSocket stream goes
through a fake `WebSocketConnector`. Credential-gating is tested directly
against `argus.providers.credentials`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import httpx
import pytest

from argus.providers.credentials import MissingProviderCredentialError, require_env_credential
from argus.providers.dexscreener.client import DexScreenerClient
from argus.providers.geckoterminal.client import GeckoTerminalClient
from argus.providers.helius.client import (
    HeliusRpcClient,
    HeliusRpcError,
    HeliusWebSocketStream,
    resolve_helius_api_key,
)
from argus.providers.jupiter.client import JupiterClient
from argus.providers.models import ExecutableQuote
from argus.providers.usage import RequestUsageRecord, StreamingUsageRecord


class _InMemoryUsageRecorder:
    def __init__(self) -> None:
        self.requests: list[RequestUsageRecord] = []

    async def record_request(self, record: RequestUsageRecord) -> None:
        self.requests.append(record)

    async def record_streaming(self, record: StreamingUsageRecord) -> None:
        raise NotImplementedError


def test_missing_helius_api_key_raises_local_credential_required() -> None:
    with pytest.raises(MissingProviderCredentialError) as exc_info:
        resolve_helius_api_key({})
    message = str(exc_info.value)
    assert message.startswith("LOCAL CREDENTIAL REQUIRED:\nHELIUS_API_KEY")
    assert "DO NOT paste its value into chat" in message


def test_present_helius_api_key_resolves() -> None:
    assert resolve_helius_api_key({"HELIUS_API_KEY": "test-key-123"}) == "test-key-123"


def test_require_env_credential_generic() -> None:
    with pytest.raises(MissingProviderCredentialError):
        require_env_credential({}, "SOME_VAR")
    assert require_env_credential({"SOME_VAR": "x"}, "SOME_VAR") == "x"


async def test_helius_get_transaction_via_mock_transport() -> None:
    transaction_result = {"meta": {"fee": 5000}, "transaction": {"message": {}, "signatures": []}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api-key"] == "fake-key"
        body = json.loads(request.content)
        assert body["method"] == "getTransaction"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": transaction_result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    result = await client.get_transaction("some-signature")
    assert result == transaction_result
    await http_client.aclose()


async def test_helius_get_transaction_null_transaction_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"meta": {"fee": 5000}, "transaction": None},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'transaction' is not an object"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_missing_message_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"meta": {"fee": 5000}, "transaction": {"signatures": []}},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'transaction.message' is not an object"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_non_string_signature_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "meta": {"fee": 5000},
                    "transaction": {"message": {}, "signatures": [123]},
                },
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'transaction.signatures' is not a list of strings"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_invalid_meta_err_type_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "meta": {"fee": 5000, "err": 42},
                    "transaction": {"message": {}, "signatures": []},
                },
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'meta.err' has an invalid type"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_signatures_for_address_parses_entries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": [
                    {"signature": "sig-2", "slot": 200, "blockTime": 1735000200, "err": None},
                    {"signature": "sig-1", "slot": 100, "blockTime": None, "err": {"x": 1}},
                ],
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    signatures = await client.get_signatures_for_address("SomeWallet")
    assert [s.signature for s in signatures] == ["sig-2", "sig-1"]
    assert signatures[0].block_time is not None
    assert signatures[1].block_time is None
    assert signatures[1].err == {"x": 1}
    await http_client.aclose()


async def test_helius_get_signatures_for_address_bool_as_slot_rejected() -> None:
    """``bool`` is an ``int`` subclass in Python -- ``slot: true`` must
    never silently pass an ``isinstance(value, int)`` check."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": [{"signature": "sig-1", "slot": True, "err": None}],
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'signature'/'slot' have wrong type"):
        await client.get_signatures_for_address("SomeWallet")
    await http_client.aclose()


async def test_helius_get_signatures_for_address_invalid_err_type_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": [{"signature": "sig-1", "slot": 100, "err": 7}],
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'err' has an invalid type"):
        await client.get_signatures_for_address("SomeWallet")
    await http_client.aclose()


async def test_helius_get_signature_statuses_bool_as_slot_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"value": [{"confirmationStatus": "confirmed", "slot": True}]},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'slot' has an invalid type"):
        await client.get_signature_statuses(["sig-1"])
    await http_client.aclose()


async def test_helius_get_signature_statuses_invalid_err_type_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"value": [{"confirmationStatus": "confirmed", "err": ["not", "valid"]}]},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'err' has an invalid type"):
        await client.get_signature_statuses(["sig-1"])
    await http_client.aclose()


async def test_helius_get_signature_statuses_object_err_and_slot_accepted() -> None:
    """A real object-variant ``TransactionError`` and a genuine slot must
    still be accepted -- this is a positive control for the two rejection
    tests immediately above."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "value": [
                        {
                            "confirmationStatus": "finalized",
                            "slot": 999,
                            "err": {"InstructionError": [0, "Custom"]},
                        }
                    ]
                },
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    [status] = await client.get_signature_statuses(["sig-1"])
    assert status.slot == 999
    assert status.err == {"InstructionError": [0, "Custom"]}
    await http_client.aclose()


async def test_helius_rpc_error_response_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "bad request"}},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="bad request"):
        await client.get_balance("SomeWallet")
    await http_client.aclose()


async def test_helius_http_error_status_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_slot()
    await http_client.aclose()


class _FakeWebSocketConnection:
    def __init__(self, messages: list[str], *, disconnect_after: bool = False) -> None:
        self._messages = list(messages)
        self._disconnect_after = disconnect_after
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        if not self._messages:
            if self._disconnect_after:
                raise ConnectionError("connection closed")
            raise AssertionError("no more fake messages queued")
        return self._messages.pop(0)

    async def close(self) -> None:
        return None


class _FakeWebSocketConnector:
    def __init__(self, connection: _FakeWebSocketConnection) -> None:
        self._connection = connection

    @asynccontextmanager
    async def _cm(self, url: str) -> AsyncIterator[_FakeWebSocketConnection]:
        yield self._connection

    def connect(self, url: str) -> Any:
        return self._cm(url)


async def test_helius_ws_stream_yields_notifications() -> None:
    ack = json.dumps({"jsonrpc": "2.0", "id": 1, "result": 12345})
    notification = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "logsNotification",
            "params": {
                "subscription": 12345,
                "result": {
                    "context": {"slot": 42},
                    "value": {"signature": "ws-sig-1", "err": None, "logs": []},
                },
            },
        }
    )
    connection = _FakeWebSocketConnection([ack, notification])
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    subscription = await stream.open_subscription("SomeWallet")
    received = []
    async for note in subscription.notifications():
        received.append(note)
        break  # one notification is enough to prove the parsing path
    await subscription.close()

    assert len(received) == 1
    assert received[0].signature == "ws-sig-1"
    assert received[0].slot == 42
    assert received[0].wallet_address == "SomeWallet"
    assert "logsSubscribe" in connection.sent[0]


async def test_helius_ws_stream_raises_on_disconnect_not_silent_stop() -> None:
    """A dropped connection must raise, not just stop yielding -- the
    stream manager needs to be able to distinguish "quiet wallet" from
    "the connection actually died" to trigger reconciliation."""
    ack = json.dumps({"jsonrpc": "2.0", "id": 1, "result": 12345})
    connection = _FakeWebSocketConnection([ack], disconnect_after=True)
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    subscription = await stream.open_subscription("SomeWallet")
    with pytest.raises(ConnectionError):
        async for _note in subscription.notifications():
            pass  # pragma: no cover - no notifications are ever queued


async def test_helius_ws_stream_bad_subscribe_ack_raises() -> None:
    """Finding #1: a bad/failed acknowledgement must raise from
    ``open_subscription`` itself -- eagerly, before a subscription object
    is ever returned -- not lazily on first iteration."""
    bad_ack = json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"message": "invalid params"}})
    connection = _FakeWebSocketConnection([bad_ack])
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    with pytest.raises(HeliusRpcError, match="logsSubscribe failed"):
        await stream.open_subscription("SomeWallet")


async def test_helius_ws_stream_skips_mismatched_id_before_matching_ack() -> None:
    """An ack (or any message) for a different request id must be
    skipped, not mistaken for this subscription's own acknowledgement --
    the real acceptance signal is a matching ``id``, not just "the next
    message that arrived". Proven observably: a notification tagged with
    the *real* (post-skip) subscription id is correctly recognized and
    yielded."""
    unrelated = json.dumps({"jsonrpc": "2.0", "id": 999, "result": 42})
    ack = json.dumps({"jsonrpc": "2.0", "id": 1, "result": 12345})
    notification = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "logsNotification",
            "params": {
                "subscription": 12345,
                "result": {
                    "context": {"slot": 7},
                    "value": {"signature": "ws-sig-2", "err": None, "logs": []},
                },
            },
        }
    )
    connection = _FakeWebSocketConnection([unrelated, ack, notification])
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    subscription = await stream.open_subscription("SomeWallet")
    received = []
    async for note in subscription.notifications():
        received.append(note)
        break
    assert len(received) == 1
    assert received[0].signature == "ws-sig-2"
    assert received[0].slot == 7


async def test_helius_ws_stream_wrong_jsonrpc_version_on_matching_id_raises() -> None:
    bad_ack = json.dumps({"jsonrpc": "1.0", "id": 1, "result": 12345})
    connection = _FakeWebSocketConnection([bad_ack])
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    with pytest.raises(HeliusRpcError, match="logsSubscribe failed"):
        await stream.open_subscription("SomeWallet")


async def test_helius_ws_stream_bool_result_on_ack_rejected() -> None:
    """``bool`` is an ``int`` subclass -- ``result: true`` must never be
    accepted as a genuine subscription id."""
    bad_ack = json.dumps({"jsonrpc": "2.0", "id": 1, "result": True})
    connection = _FakeWebSocketConnection([bad_ack])
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    with pytest.raises(HeliusRpcError, match="logsSubscribe failed"):
        await stream.open_subscription("SomeWallet")


class _HangingWebSocketConnection:
    """Never resolves ``recv``/``send`` -- used to exercise the bounded
    connect/send/ack timeouts (Phase 1 remediation round 4, finding #4).
    """

    def __init__(self, *, hang_on: str) -> None:
        self._hang_on = hang_on
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        if self._hang_on == "send":
            await asyncio.Event().wait()
        self.sent.append(message)

    async def recv(self) -> str:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    async def close(self) -> None:
        return None


class _TrackingWebSocketConnector:
    """Like ``_FakeWebSocketConnector``, but records whether ``__aexit__``
    was actually invoked (proving cleanup happened after a timeout) and
    can simulate a ``connect`` that never resolves."""

    def __init__(self, connection: Any, *, hang_on_connect: bool = False) -> None:
        self._connection = connection
        self._hang_on_connect = hang_on_connect
        self.aexit_called = False

    @asynccontextmanager
    async def _cm(self, url: str) -> AsyncIterator[Any]:
        if self._hang_on_connect:
            await asyncio.Event().wait()
        try:
            yield self._connection
        finally:
            self.aexit_called = True

    def connect(self, url: str) -> Any:
        return self._cm(url)


async def test_helius_ws_stream_connect_timeout_raises_and_leaves_nothing_to_clean_up() -> None:
    connector = _TrackingWebSocketConnector(
        _HangingWebSocketConnection(hang_on="recv"), hang_on_connect=True
    )
    stream = HeliusWebSocketStream("fake-key", connector=connector, connect_timeout_seconds=0.01)

    with pytest.raises(HeliusRpcError, match="connect timed out"):
        await stream.open_subscription("SomeWallet")
    # __aenter__ never completed -- there is no entered context, so
    # __aexit__ (and its cleanup) never runs, and never should.
    assert connector.aexit_called is False


async def test_helius_ws_stream_send_timeout_raises_and_cleans_up() -> None:
    connection = _HangingWebSocketConnection(hang_on="send")
    connector = _TrackingWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector, send_timeout_seconds=0.01)

    with pytest.raises(HeliusRpcError, match="send timed out"):
        await stream.open_subscription("SomeWallet")
    assert connector.aexit_called is True


async def test_helius_ws_stream_ack_timeout_raises_and_cleans_up() -> None:
    connection = _HangingWebSocketConnection(hang_on="recv")
    connector = _TrackingWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector, ack_timeout_seconds=0.01)

    with pytest.raises(HeliusRpcError, match="no matching acknowledgement"):
        await stream.open_subscription("SomeWallet")
    assert connector.aexit_called is True


async def test_helius_ws_stream_cancellation_during_ack_wait_cleans_up() -> None:
    connection = _HangingWebSocketConnection(hang_on="recv")
    connector = _TrackingWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector, ack_timeout_seconds=30.0)

    task = asyncio.ensure_future(stream.open_subscription("SomeWallet"))
    await asyncio.sleep(0)  # let it reach the hanging recv()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert connector.aexit_called is True


async def test_dexscreener_token_snapshot() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/latest/dex/tokens/SomeMint")
        return httpx.Response(200, json={"pairs": [{"priceUsd": "1.23"}]})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = DexScreenerClient(http_client=http_client)
    result = await client.token_snapshot("SomeMint")
    assert result.price_usd == Decimal("1.23")
    assert result.raw["pairs"][0]["priceUsd"] == "1.23"
    await http_client.aclose()


async def test_dexscreener_has_no_historical_ohlcv() -> None:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    client = DexScreenerClient(http_client=http_client)
    with pytest.raises(NotImplementedError, match="GeckoTerminal"):
        from datetime import UTC, datetime

        await client.historical_ohlcv("SomeMint", start=datetime.now(UTC), end=datetime.now(UTC))
    await http_client.aclose()


async def test_geckoterminal_historical_ohlcv_filters_by_start() -> None:
    from datetime import UTC, datetime

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "attributes": {
                        "ohlcv_list": [
                            [1_735_003_600, 1.0, 1.1, 0.9, 1.05, 1000],
                            [1_735_000_000, 0.5, 0.6, 0.4, 0.55, 500],
                        ]
                    }
                }
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GeckoTerminalClient(http_client=http_client)
    page = await client.historical_ohlcv(
        "SomeMint",
        start=datetime.fromtimestamp(1_735_002_000, tz=UTC),
        end=datetime.fromtimestamp(1_735_004_000, tz=UTC),
    )
    assert len(page.candles) == 1
    assert page.candles[0].close == Decimal("1.05")
    await http_client.aclose()


async def test_jupiter_quote_and_unsigned_order_never_signs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v6/quote"):
            assert request.url.params["inputMint"] == "MintA"
            return httpx.Response(200, json={"outAmount": "500", "inAmount": "1000000000"})
        if request.url.path.endswith("/v6/swap"):
            body = json.loads(request.content)
            assert body["userPublicKey"] == "SomeWallet"
            assert "quoteResponse" in body
            return httpx.Response(200, json={"swapTransaction": "base64-unsigned-tx-not-real"})
        raise AssertionError(f"unexpected path {request.url.path}")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = JupiterClient(http_client=http_client)
    quote = await client.get_quote(
        input_mint="MintA", output_mint="MintB", amount_raw=1_000_000_000
    )
    assert quote.out_amount_raw == 500
    assert quote.in_amount_raw == 1_000_000_000

    order = await client.build_unsigned_order(quote=quote, wallet_address="SomeWallet")
    assert order.unsigned_transaction_base64 == "base64-unsigned-tx-not-real"

    # No signing/execute/broadcast method exists anywhere on this client.
    assert not hasattr(client, "sign")
    assert not hasattr(client, "execute")
    assert not hasattr(client, "broadcast")
    await http_client.aclose()


async def test_helius_rpc_call_records_usage_when_recorder_provided() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": 42})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    slot = await client.get_slot()
    assert slot == 42
    assert len(usage.requests) == 1
    record = usage.requests[0]
    assert record.provider == "helius"
    assert record.endpoint == "getSlot"
    assert record.status == "ok"
    assert record.retry_count == 0
    assert record.latency_ms is not None
    assert record.bytes_received is not None
    await http_client.aclose()


async def test_helius_rpc_malformed_response_raises_clean_error_not_keyerror() -> None:
    """Neither 'result' nor 'error' present -- acceptance criterion #14:
    adapter contract validation must reject malformed provider responses
    with a typed error, not crash with a bare KeyError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="malformed response"):
        await client.get_slot()
    await http_client.aclose()


async def test_helius_rpc_retries_on_5xx_then_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": 7})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    from argus.providers.retry import RetryPolicy

    client = HeliusRpcClient(
        "fake-key",
        http_client=http_client,
        # Tiny delays so this test doesn't spend real wall-clock time
        # sleeping -- the retry *mechanism* is what's under test, not the
        # backoff timing (that's covered exactly in tests/unit/test_retry.py).
        retry_policy=RetryPolicy(max_attempts=5, base_delay_seconds=0.001, max_delay_seconds=0.005),
    )
    result = await client.get_slot()
    assert result == 7
    assert attempts == 3
    await http_client.aclose()


async def test_geckoterminal_records_usage_for_both_endpoints() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"attributes": {"ohlcv_list": []}}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = GeckoTerminalClient(http_client=http_client, usage_recorder=usage)
    from datetime import UTC, datetime

    await client.token_snapshot("SomeMint")
    await client.historical_ohlcv("SomeMint", start=datetime.now(UTC), end=datetime.now(UTC))
    assert len(usage.requests) == 2
    assert {r.endpoint for r in usage.requests} == {"token_snapshot", "historical_ohlcv"}
    await http_client.aclose()


# --- Finding #6: adversarial malformed-response contract tests ---------


async def test_dexscreener_malformed_pair_price_rejected() -> None:
    from argus.providers.contract import ProviderContractError

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"pairs": [{"priceUsd": "not-a-number"}]})
        )
    )
    client = DexScreenerClient(http_client=http_client)
    with pytest.raises(ProviderContractError, match="priceUsd"):
        await client.token_snapshot("SomeMint")
    await http_client.aclose()


async def test_dexscreener_pairs_not_a_list_rejected() -> None:
    from argus.providers.contract import ProviderContractError

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"pairs": "not-a-list"}))
    )
    client = DexScreenerClient(http_client=http_client)
    with pytest.raises(ProviderContractError):
        await client.token_snapshot("SomeMint")
    await http_client.aclose()


async def test_geckoterminal_malformed_candle_row_rejected() -> None:
    from argus.providers.contract import ProviderContractError

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={"data": {"attributes": {"ohlcv_list": [[1, 2, 3]]}}},  # only 3 elements
            )
        )
    )
    client = GeckoTerminalClient(http_client=http_client)
    with pytest.raises(ProviderContractError, match="6-element"):
        from datetime import UTC, datetime

        await client.historical_ohlcv("SomeMint", start=datetime.now(UTC), end=datetime.now(UTC))
    await http_client.aclose()


async def test_geckoterminal_ohlcv_list_not_a_list_rejected() -> None:
    from argus.providers.contract import ProviderContractError

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"data": {"attributes": {"ohlcv_list": "nope"}}})
        )
    )
    client = GeckoTerminalClient(http_client=http_client)
    with pytest.raises(ProviderContractError):
        from datetime import UTC, datetime

        await client.historical_ohlcv("SomeMint", start=datetime.now(UTC), end=datetime.now(UTC))
    await http_client.aclose()


async def test_jupiter_quote_missing_amount_rejected() -> None:
    from argus.providers.contract import ProviderContractError

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"outAmount": "1"}))
    )
    client = JupiterClient(http_client=http_client)
    with pytest.raises(ProviderContractError, match="inAmount"):
        await client.get_quote(input_mint="A", output_mint="B", amount_raw=1)
    await http_client.aclose()


async def test_jupiter_unsigned_order_missing_swap_transaction_rejected() -> None:
    from argus.providers.contract import ProviderContractError

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"notTheRightField": 1}))
    )
    client = JupiterClient(http_client=http_client)
    fake_quote = ExecutableQuote(
        provider="jupiter",
        input_mint="A",
        output_mint="B",
        in_amount_raw=1,
        out_amount_raw=1,
        raw={},
    )
    with pytest.raises(ProviderContractError, match="swapTransaction"):
        await client.build_unsigned_order(quote=fake_quote, wallet_address="Wallet")
    await http_client.aclose()


# --- Finding #7: usage accounting must survive transport exhaustion ----


async def test_transport_exhaustion_still_records_usage_then_reraises() -> None:
    from argus.providers.retry import RetryPolicy

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient(
        "fake-key",
        http_client=http_client,
        usage_recorder=usage,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.001, max_delay_seconds=0.005),
    )
    with pytest.raises(httpx.ConnectError):
        await client.get_slot()

    assert len(usage.requests) == 1
    record = usage.requests[0]
    assert record.status == "transport_error"
    assert record.retry_count == 2  # max_attempts - 1: every attempt was exhausted
    assert record.bytes_received is None
    await http_client.aclose()


async def test_recorder_failure_never_masks_the_real_provider_outcome() -> None:
    """A DB error while recording usage must never replace or hide the
    real success/failure the caller actually gets back."""

    class _FailingUsageRecorder:
        async def record_request(self, record):  # noqa: ANN001
            raise RuntimeError("usage DB is down")

        async def record_streaming(self, record):  # noqa: ANN001
            raise RuntimeError("usage DB is down")

    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": 99})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(ok_handler))
    client = HeliusRpcClient(
        "fake-key", http_client=http_client, usage_recorder=_FailingUsageRecorder()
    )
    result = await client.get_slot()
    assert result == 99  # the real success is returned despite the recorder failing
    await http_client.aclose()

    def raising_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    from argus.providers.retry import RetryPolicy

    http_client2 = httpx.AsyncClient(transport=httpx.MockTransport(raising_handler))
    client2 = HeliusRpcClient(
        "fake-key",
        http_client=http_client2,
        usage_recorder=_FailingUsageRecorder(),
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.001, max_delay_seconds=0.005),
    )
    with pytest.raises(
        httpx.ConnectError
    ):  # the real transport failure, not the recorder's RuntimeError
        await client2.get_slot()
    await http_client2.aclose()


async def test_recorder_failure_emits_a_visible_operational_health_signal(capsys) -> None:  # noqa: ANN001
    """Finding #8: a usage-recorder failure must not disappear silently --
    it must emit a visible signal a human/monitor can act on, distinct
    from (and never instead of) the real provider outcome."""

    class _FailingUsageRecorder:
        async def record_request(self, record):  # noqa: ANN001
            raise RuntimeError("usage DB is down")

        async def record_streaming(self, record):  # noqa: ANN001
            raise NotImplementedError

    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": 7})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(ok_handler))
    client = HeliusRpcClient(
        "fake-key", http_client=http_client, usage_recorder=_FailingUsageRecorder()
    )
    result = await client.get_slot()
    assert result == 7  # the real success is still returned
    await http_client.aclose()

    captured = capsys.readouterr()
    assert "usage_recorder_failed" in captured.out
    assert "usage DB is down" in captured.out
    assert "helius" in captured.out


# --- Finding #8: usage records exactly one outcome, decided only after ---
# --- decode/validation, never a premature "ok" -----------------------------


async def test_usage_not_recorded_ok_before_decode_failure() -> None:
    """A 200 response whose body isn't valid JSON must never leave an "ok"
    usage row behind -- the old code recorded "ok" as soon as the status
    code wasn't an error, before ``response.json()`` was ever called."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    with pytest.raises(Exception, match="not json at all|Expecting value"):
        await client.get_slot()
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "decode_error"
    await http_client.aclose()


async def test_usage_records_http_error_not_ok_for_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_slot()
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "http_error"
    await http_client.aclose()


async def test_usage_records_rpc_error_not_ok_for_well_formed_rpc_error() -> None:
    """A well-formed JSON-RPC error response is a 200 at the transport
    level -- the old code recorded it as "ok"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "bad request"}},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    with pytest.raises(HeliusRpcError):
        await client.get_balance("SomeWallet")
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "rpc_error"
    await http_client.aclose()


async def test_usage_records_contract_error_for_malformed_rpc_envelope() -> None:
    """Missing both 'result' and 'error' is a contract violation, not a
    well-formed application-level error -- distinct from rpc_error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    with pytest.raises(HeliusRpcError, match="malformed response"):
        await client.get_slot()
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "contract_error"
    await http_client.aclose()


async def test_usage_records_contract_error_for_dexscreener_bad_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"pairs": [{"priceUsd": "not-a-number"}]})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = DexScreenerClient(http_client=http_client, usage_recorder=usage)
    from argus.providers.contract import ProviderContractError

    with pytest.raises(ProviderContractError):
        await client.token_snapshot("SomeMint")
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "contract_error"
    await http_client.aclose()


async def test_usage_records_timeout_distinct_from_transport_error() -> None:
    from argus.providers.retry import RetryPolicy

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient(
        "fake-key",
        http_client=http_client,
        usage_recorder=usage,
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.001, max_delay_seconds=0.005),
    )
    with pytest.raises(httpx.ConnectTimeout):
        await client.get_slot()
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "timeout"
    await http_client.aclose()


async def test_usage_records_ok_exactly_once_for_a_real_success() -> None:
    """No duplicate/contradictory rows for the ordinary success path --
    exactly one row, and it says "ok"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": 42})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    result = await client.get_slot()
    assert result == 42
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "ok"
    await http_client.aclose()


# --- R3 finding #3: every Helius method's nested contract validation ---
# --- runs inside the single accounted operation -- a malformed method- ---
# --- specific result must never leave behind an "ok" usage row. --------


async def test_helius_get_transaction_missing_meta_records_contract_error_not_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"transaction": {}}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    with pytest.raises(HeliusRpcError, match="missing 'meta'"):
        await client.get_transaction("some-signature")
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "contract_error"
    await http_client.aclose()


async def test_helius_get_transaction_meta_not_object_records_contract_error_not_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"meta": "not-an-object", "transaction": {}},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    with pytest.raises(HeliusRpcError, match="'meta' is not an object"):
        await client.get_transaction("some-signature")
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "contract_error"
    await http_client.aclose()


async def test_helius_get_signatures_malformed_entry_records_contract_error_not_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": [{"signature": "sig", "slot": "not-an-int"}],
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    with pytest.raises(HeliusRpcError, match="wrong type"):
        await client.get_signatures_for_address("SomeWallet")
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "contract_error"
    await http_client.aclose()


async def test_helius_get_signatures_result_not_a_list_records_contract_error_not_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "not-a-list"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    with pytest.raises(HeliusRpcError, match="expected a list"):
        await client.get_signatures_for_address("SomeWallet")
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "contract_error"
    await http_client.aclose()


async def test_helius_signature_statuses_length_mismatch_records_contract_error_not_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": []}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    with pytest.raises(HeliusRpcError, match="expected 1 status entries"):
        await client.get_signature_statuses(["sig-1"])
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "contract_error"
    await http_client.aclose()


async def test_helius_signature_statuses_unknown_confirmation_status_records_contract_error() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"value": [{"confirmationStatus": "bogus"}]},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    with pytest.raises(HeliusRpcError, match="unknown confirmationStatus"):
        await client.get_signature_statuses(["sig-1"])
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "contract_error"
    await http_client.aclose()


async def test_helius_get_balance_malformed_response_records_contract_error_not_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": "nope"}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    with pytest.raises(HeliusRpcError, match="getBalance: malformed response"):
        await client.get_balance("SomeWallet")
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "contract_error"
    await http_client.aclose()


def _jsonparsed_token_account(
    *,
    pubkey: str = "acct-1",
    mint: str = "MintA",
    owner: str = "SomeWallet",
    amount: str = "1000000",
    decimals: Any = 6,
) -> dict[str, Any]:
    return {
        "pubkey": pubkey,
        "account": {
            "data": {
                "parsed": {
                    "info": {
                        "mint": mint,
                        "owner": owner,
                        "tokenAmount": {"amount": amount, "decimals": decimals},
                    }
                }
            }
        },
    }


async def test_helius_get_token_accounts_happy_path_records_ok() -> None:
    accounts = [_jsonparsed_token_account()]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    result = await client.get_token_accounts("SomeWallet")
    assert len(result) == 1
    account = result[0]
    assert account.pubkey == "acct-1"
    assert account.mint == "MintA"
    assert account.owner == "SomeWallet"
    assert account.amount_raw == 1_000_000
    assert account.decimals == 6
    assert account.raw == accounts[0]
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "ok"
    await http_client.aclose()


async def test_helius_get_token_accounts_missing_parsed_info_rejected() -> None:
    accounts = [{"pubkey": "acct-1", "account": {"data": {}}}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    with pytest.raises(HeliusRpcError, match="missing 'account.data.parsed.info'"):
        await client.get_token_accounts("SomeWallet")
    assert usage.requests[0].status == "contract_error"
    await http_client.aclose()


async def test_helius_get_token_accounts_non_object_account_rejected() -> None:
    accounts = [{"pubkey": "acct-1", "account": "not-an-object"}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'account' is not an object"):
        await client.get_token_accounts("SomeWallet")
    await http_client.aclose()


async def test_helius_get_token_accounts_bool_as_decimals_rejected() -> None:
    """``bool`` is an ``int`` subclass in Python -- a provider response
    with ``decimals: true`` must never silently pass an
    ``isinstance(value, int)`` check."""
    accounts = [_jsonparsed_token_account(decimals=True)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'tokenAmount.decimals' is not an integer"):
        await client.get_token_accounts("SomeWallet")
    await http_client.aclose()


async def test_helius_get_token_accounts_non_numeric_amount_rejected() -> None:
    accounts = [_jsonparsed_token_account(amount="not-a-number")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'tokenAmount.amount' is not a numeric string"):
        await client.get_token_accounts("SomeWallet")
    await http_client.aclose()


async def test_helius_get_token_accounts_malformed_response_records_contract_error_not_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": "nope"}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    with pytest.raises(HeliusRpcError, match="getTokenAccountsByOwner: malformed response"):
        await client.get_token_accounts("SomeWallet")
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "contract_error"
    await http_client.aclose()


async def test_helius_get_transaction_happy_path_records_ok_and_returns_result() -> None:
    transaction_result = {"meta": {"fee": 5000}, "transaction": {"message": {}, "signatures": []}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": transaction_result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    client = HeliusRpcClient("fake-key", http_client=http_client, usage_recorder=usage)
    result = await client.get_transaction("some-signature")
    assert result == transaction_result
    assert len(usage.requests) == 1
    assert usage.requests[0].status == "ok"
    await http_client.aclose()


async def test_cancellation_during_process_records_nothing() -> None:
    """A cancellation while ``process`` (decode/validation) is running must
    never leave behind a fabricated row -- no terminal outcome actually
    happened, so nothing is recorded, not even a "cancelled" status.
    Exercised directly against ``send_with_usage`` (not through an
    adapter) so the assertion is deterministic rather than dependent on
    real task-scheduling timing."""
    import asyncio

    from argus.clock import Clock
    from argus.providers.http import send_with_usage
    from argus.providers.retry import RetryPolicy

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    def _process(response: httpx.Response) -> Any:
        raise asyncio.CancelledError

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    usage = _InMemoryUsageRecorder()
    with pytest.raises(asyncio.CancelledError):
        await send_with_usage(
            lambda: http_client.get("https://example.invalid/x"),
            process=_process,
            policy=RetryPolicy(),
            usage_recorder=usage,
            clock=Clock(),
            provider="test",
            endpoint="test_endpoint",
            request_class="rest",
        )
    assert usage.requests == []
    await http_client.aclose()
