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


def _valid_transaction_result(**overrides: Any) -> dict[str, Any]:
    """A minimal but fully contract-valid getTransaction result -- every
    field round 5, finding #5 requires is present. Individual "malformed"
    tests below override exactly the one field under test, isolating
    that check the same way `_jsonparsed_token_account` already does for
    get_token_accounts."""
    result: dict[str, Any] = {
        "slot": 12345,
        "meta": {
            "fee": 5000,
            "err": None,
            "preBalances": [2_000_000_000, 0],
            "postBalances": [1_000_000_000, 995_000_000],
        },
        "transaction": {
            # Matches the "some-signature" argument every
            # client.get_transaction(...) call in this file passes, so the
            # response's primary signature agrees with the requested one
            # by default (Phase 1 remediation round 6, finding #4's
            # identity-binding check) -- a test exercising a genuine
            # mismatch constructs its own transaction.signatures override.
            "signatures": ["some-signature"],
            "message": {"accountKeys": ["WalletAddress1", "WalletAddress2"]},
        },
    }
    result.update(overrides)
    return result


async def test_helius_get_transaction_via_mock_transport() -> None:
    transaction_result = _valid_transaction_result()

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
                    "transaction": {
                        "message": {"accountKeys": []},
                        "signatures": [123],
                    },
                },
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError, match="'transaction.signatures' is not a non-empty list of non-empty"
    ):
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
                    "transaction": {
                        "message": {"accountKeys": []},
                        "signatures": ["some-signature"],
                    },
                },
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'meta.err' has an invalid type"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


# --- R5 finding #5: deepened getTransaction contract validation --------


async def test_helius_get_transaction_empty_signatures_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": _valid_transaction_result(
                    transaction={"message": {"accountKeys": []}, "signatures": []}
                ),
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError, match="'transaction.signatures' is not a non-empty list of non-empty"
    ):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_missing_err_key_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        del result["meta"]["err"]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'meta.err' is required but missing"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_bool_as_fee_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["fee"] = True
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'meta.fee' is not a valid unsigned-64-bit integer"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_negative_fee_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["fee"] = -1
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'meta.fee' is not a valid unsigned-64-bit integer"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_invalid_account_keys_shape_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["transaction"]["message"]["accountKeys"] = [123]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError, match="'transaction.message.accountKeys' is not a list of pubkey"
    ):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_accepts_dict_shaped_account_keys() -> None:
    """The jsonParsed/versioned-transaction accountKeys shape --
    ``{"pubkey": str, ...}`` objects rather than bare strings -- must be
    accepted, matching what `argus.parsing.generic_parser` already
    tolerates."""

    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["transaction"]["message"]["accountKeys"] = [
            {"pubkey": "WalletAddress1", "signer": True, "writable": True},
            {"pubkey": "WalletAddress2", "signer": False, "writable": True},
        ]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    result = await client.get_transaction("some-signature")
    assert result["transaction"]["message"]["accountKeys"][0]["pubkey"] == "WalletAddress1"
    await http_client.aclose()


@pytest.mark.parametrize("balances_key", ["preBalances", "postBalances"])
async def test_helius_get_transaction_negative_balance_entry_rejected(balances_key: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"][balances_key] = [-1, 0]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError, match=f"'meta.{balances_key}' is not a list of valid unsigned-64-bit"
    ):
        await client.get_transaction("some-signature")
    await http_client.aclose()


@pytest.mark.parametrize("balances_key", ["preBalances", "postBalances"])
async def test_helius_get_transaction_balance_length_mismatch_rejected(balances_key: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"][balances_key] = [1, 2, 3]  # accountKeys only has 2 entries
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError, match=f"'meta.{balances_key}' has 3 entries, which does not match"
    ):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_missing_slot_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        del result["slot"]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'slot' is not a valid unsigned-64-bit integer"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_bool_as_block_time_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["blockTime"] = True
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError, match="'blockTime' is not null or a valid unsigned-64-bit integer"
    ):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_null_block_time_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["blockTime"] = None
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    result = await client.get_transaction("some-signature")
    assert result["blockTime"] is None
    await http_client.aclose()


def _valid_token_balance_entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "accountIndex": 0,
        "mint": "SomeMint",
        "owner": "WalletAddress1",
        "uiTokenAmount": {"amount": "1000000", "decimals": 6},
    }
    entry.update(overrides)
    return entry


async def test_helius_get_transaction_accepts_valid_token_balance_entries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["preTokenBalances"] = [_valid_token_balance_entry()]
        result["meta"]["postTokenBalances"] = [_valid_token_balance_entry(accountIndex=1)]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    result = await client.get_transaction("some-signature")
    assert result["meta"]["preTokenBalances"][0]["mint"] == "SomeMint"
    await http_client.aclose()


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("accountIndex", 99, "out-of-range or invalid accountIndex"),
        ("accountIndex", True, "out-of-range or invalid accountIndex"),
        ("accountIndex", -1, "out-of-range or invalid accountIndex"),
        ("mint", 123, "missing a non-empty 'mint'/'owner' identity string"),
        ("owner", None, "missing a non-empty 'mint'/'owner' identity string"),
    ],
)
async def test_helius_get_transaction_malformed_token_balance_entry_rejected(
    field: str, value: Any, match: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["preTokenBalances"] = [_valid_token_balance_entry(**{field: value})]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match=match):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_token_balance_bad_amount_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["preTokenBalances"] = [
            _valid_token_balance_entry(uiTokenAmount={"amount": "-5", "decimals": 6})
        ]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'uiTokenAmount.amount' is not a valid ASCII-digit"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_token_balance_out_of_bounds_decimals_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["preTokenBalances"] = [
            _valid_token_balance_entry(uiTokenAmount={"amount": "5", "decimals": 300})
        ]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'uiTokenAmount.decimals' is out of bounds"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_token_balances_not_a_list_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["preTokenBalances"] = "not-a-list"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'meta.preTokenBalances' is not a list"):
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
    with pytest.raises(
        HeliusRpcError,
        match="'signature'/'slot' are not a non-empty string / valid unsigned-64-bit integer",
    ):
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
    with pytest.raises(HeliusRpcError, match="'slot' is not a valid unsigned-64-bit integer"):
        await client.get_signature_statuses(["sig-1"])
    await http_client.aclose()


async def test_helius_get_signature_statuses_invalid_err_type_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "value": [
                        {"confirmationStatus": "confirmed", "slot": 100, "err": ["not", "valid"]}
                    ]
                },
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
    def __init__(
        self,
        messages: list[str],
        *,
        disconnect_after: bool = False,
        ping_behavior: str = "pong",
    ) -> None:
        self._messages = list(messages)
        self._disconnect_after = disconnect_after
        self.sent: list[str] = []
        # "pong" (default): ping() returns an already-resolved pong
        # waiter, matching a healthy connection. "hang": the pong waiter
        # never resolves (simulates a dead/unresponsive connection --
        # check_liveness must time out, not hang forever). "raise":
        # ping() itself raises (e.g. the underlying socket is already
        # closed).
        self._ping_behavior = ping_behavior
        self.ping_calls = 0

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

    async def ping(self) -> Any:
        self.ping_calls += 1
        if self._ping_behavior == "raise":
            raise ConnectionError("ping failed: connection already closed")
        pong_waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        if self._ping_behavior == "pong":
            pong_waiter.set_result(None)
        # "hang": leave pong_waiter unresolved -- the caller must time out.
        return pong_waiter


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

    async def ping(self) -> Any:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover


class _TrackingWebSocketConnector:
    """Like ``_FakeWebSocketConnector``, but records whether ``__aexit__``
    was actually invoked (proving cleanup happened after a timeout) and
    can simulate a ``connect`` that never resolves."""

    def __init__(
        self, connection: Any, *, hang_on_connect: bool = False, hang_on_exit: bool = False
    ) -> None:
        self._connection = connection
        self._hang_on_connect = hang_on_connect
        self._hang_on_exit = hang_on_exit
        self.aexit_called = False
        self.aexit_completed = False

    @asynccontextmanager
    async def _cm(self, url: str) -> AsyncIterator[Any]:
        if self._hang_on_connect:
            await asyncio.Event().wait()
        try:
            yield self._connection
        finally:
            self.aexit_called = True
            if self._hang_on_exit:
                await asyncio.Event().wait()
            self.aexit_completed = True

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


# --- R5 finding #6: WebSocket ack type-equality bug, early-notification --
# --- buffering, bounded cleanup, and transport-level liveness probing. --


async def test_helius_ws_stream_bool_id_never_matches_the_real_request_id() -> None:
    """Finding #6's core bug: Python's ``==`` treats ``True == 1``, so a
    message carrying JSON ``"id": true`` must never be misread as
    acknowledging request id 1 -- proven observably: it's skipped, and
    the *real* matching ack (a later message with the genuine integer id)
    is still found and used."""
    bool_id_message = json.dumps({"jsonrpc": "2.0", "id": True, "result": 999})
    real_ack = json.dumps({"jsonrpc": "2.0", "id": 1, "result": 12345})
    connection = _FakeWebSocketConnection([bool_id_message, real_ack])
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    subscription = await stream.open_subscription("SomeWallet")
    await subscription.close()


async def test_helius_ws_stream_buffers_an_early_notification_before_the_ack() -> None:
    """Finding #6: a genuine logsNotification arriving before this
    subscription's own ack must never be silently discarded -- it is
    buffered and replayed, in order, as soon as `notifications()` is
    iterated, without ever going back to `recv()` for it again."""
    early_notification = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "logsNotification",
            "params": {
                "subscription": 12345,
                "result": {
                    "context": {"slot": 7},
                    "value": {"signature": "early-sig", "err": None, "logs": []},
                },
            },
        }
    )
    ack = json.dumps({"jsonrpc": "2.0", "id": 1, "result": 12345})
    connection = _FakeWebSocketConnection([early_notification, ack])
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    subscription = await stream.open_subscription("SomeWallet")
    # Nothing further was ever queued on the connection -- the only way
    # to get a notification here is from the buffer, proving it survived.
    received = []
    async for note in subscription.notifications():
        received.append(note)
        break
    assert len(received) == 1
    assert received[0].signature == "early-sig"
    assert received[0].slot == 7


async def test_helius_ws_stream_buffers_multiple_unrelated_messages_in_order() -> None:
    """Several non-matching messages (a stray response to a different
    request id, then a genuine early notification) arriving before the
    ack must all be preserved, in the order they arrived."""
    unrelated = json.dumps({"jsonrpc": "2.0", "id": 999, "result": 42})
    early_notification = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "logsNotification",
            "params": {
                "subscription": 12345,
                "result": {
                    "context": {"slot": 1},
                    "value": {"signature": "buffered-sig", "err": None, "logs": []},
                },
            },
        }
    )
    ack = json.dumps({"jsonrpc": "2.0", "id": 1, "result": 12345})
    connection = _FakeWebSocketConnection([unrelated, early_notification, ack])
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    subscription = await stream.open_subscription("SomeWallet")
    received = []
    async for note in subscription.notifications():
        received.append(note)
        break
    assert len(received) == 1
    assert received[0].signature == "buffered-sig"


async def test_helius_ws_stream_buffered_notification_is_parsed_exactly_once() -> None:
    """No duplicate canonicalization: a buffered message is already
    parsed JSON by the time it reaches `notifications()` -- draining it
    from the buffer must never re-run `json.loads` on it (which would be
    both wasteful and a second, redundant validation pass)."""
    early_notification_dict = {
        "jsonrpc": "2.0",
        "method": "logsNotification",
        "params": {
            "subscription": 12345,
            "result": {
                "context": {"slot": 1},
                "value": {"signature": "once-sig", "err": None, "logs": []},
            },
        },
    }
    ack = json.dumps({"jsonrpc": "2.0", "id": 1, "result": 12345})
    connection = _FakeWebSocketConnection([json.dumps(early_notification_dict), ack])
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    subscription = await stream.open_subscription("SomeWallet")
    # The buffered entry is the exact same dict object `_read_matching_ack`
    # parsed -- not a fresh re-parse of the same text.
    assert len(subscription._buffered) == 1  # noqa: SLF001 - direct fake introspection in tests
    assert subscription._buffered[0] == early_notification_dict  # noqa: SLF001
    received = []
    async for note in subscription.notifications():
        received.append(note)
        break
    assert len(received) == 1
    assert len(subscription._buffered) == 0  # noqa: SLF001 - drained, not left behind


async def test_helius_ws_stream_check_liveness_true_on_pong() -> None:
    ack = json.dumps({"jsonrpc": "2.0", "id": 1, "result": 12345})
    connection = _FakeWebSocketConnection([ack], ping_behavior="pong")
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    subscription = await stream.open_subscription("SomeWallet")
    alive = await subscription.check_liveness(timeout_seconds=1.0)
    assert alive is True
    assert connection.ping_calls == 1


async def test_helius_ws_stream_check_liveness_false_on_timeout() -> None:
    """A ping whose pong never arrives (a genuinely dead or badly
    stalled connection) must report not-alive within the given timeout,
    never hang forever."""
    ack = json.dumps({"jsonrpc": "2.0", "id": 1, "result": 12345})
    connection = _FakeWebSocketConnection([ack], ping_behavior="hang")
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    subscription = await stream.open_subscription("SomeWallet")
    alive = await subscription.check_liveness(timeout_seconds=0.01)
    assert alive is False


async def test_helius_ws_stream_check_liveness_false_on_ping_error() -> None:
    ack = json.dumps({"jsonrpc": "2.0", "id": 1, "result": 12345})
    connection = _FakeWebSocketConnection([ack], ping_behavior="raise")
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    subscription = await stream.open_subscription("SomeWallet")
    alive = await subscription.check_liveness(timeout_seconds=1.0)
    assert alive is False


async def test_helius_ws_stream_check_liveness_propagates_cancellation() -> None:
    """Genuine cancellation during a liveness probe must propagate, not
    be reported as `False` -- only real ping/pong failures are."""
    ack = json.dumps({"jsonrpc": "2.0", "id": 1, "result": 12345})
    connection = _FakeWebSocketConnection([ack], ping_behavior="hang")
    connector = _FakeWebSocketConnector(connection)
    stream = HeliusWebSocketStream("fake-key", connector=connector)

    subscription = await stream.open_subscription("SomeWallet")
    task = asyncio.ensure_future(subscription.check_liveness(timeout_seconds=30.0))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_helius_ws_stream_close_is_bounded_even_if_underlying_close_hangs() -> None:
    """Finding #6: close() is a best-effort cleanup call -- one that
    itself hangs must not block the caller forever."""
    connection = _FakeWebSocketConnection([json.dumps({"jsonrpc": "2.0", "id": 1, "result": 1})])
    connector = _TrackingWebSocketConnector(connection, hang_on_exit=True)
    stream = HeliusWebSocketStream("fake-key", connector=connector, close_timeout_seconds=0.01)

    subscription = await stream.open_subscription("SomeWallet")
    await asyncio.wait_for(subscription.close(), timeout=1.0)
    assert connector.aexit_called is True
    # The underlying __aexit__ is still hanging in the background (this
    # test doesn't wait for it -- that's the whole point), so
    # aexit_completed is never observed True here.
    assert connector.aexit_completed is False


async def test_helius_ws_stream_cleanup_after_ack_failure_is_bounded_even_if_close_hangs() -> None:
    """The same bound applies to the cleanup path inside
    open_subscription itself (connect succeeded, ack failed) -- a
    hanging close() there must not turn a bounded ack-timeout failure
    into an unbounded one."""
    connection = _HangingWebSocketConnection(hang_on="recv")
    connector = _TrackingWebSocketConnector(connection, hang_on_exit=True)
    stream = HeliusWebSocketStream(
        "fake-key", connector=connector, ack_timeout_seconds=0.01, close_timeout_seconds=0.01
    )

    with pytest.raises(HeliusRpcError, match="no matching acknowledgement"):
        await asyncio.wait_for(stream.open_subscription("SomeWallet"), timeout=1.0)
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
    with pytest.raises(
        HeliusRpcError,
        match="'signature'/'slot' are not a non-empty string / valid unsigned-64-bit integer",
    ):
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
    with pytest.raises(
        HeliusRpcError, match="'tokenAmount.decimals' is not a nonnegative integer within bounds"
    ):
        await client.get_token_accounts("SomeWallet")
    await http_client.aclose()


async def test_helius_get_token_accounts_out_of_bounds_decimals_rejected() -> None:
    """SPL token decimals is a single unsigned byte on-chain -- a value
    above 255 is definitionally impossible and must be rejected the same
    as a negative one."""
    accounts = [_jsonparsed_token_account(decimals=256)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError, match="'tokenAmount.decimals' is not a nonnegative integer within bounds"
    ):
        await client.get_token_accounts("SomeWallet")
    await http_client.aclose()


async def test_helius_get_token_accounts_non_numeric_amount_rejected() -> None:
    accounts = [_jsonparsed_token_account(amount="not-a-number")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'tokenAmount.amount' is not a valid ASCII-digit"):
        await client.get_token_accounts("SomeWallet")
    await http_client.aclose()


async def test_helius_get_token_accounts_wrong_owner_rejected() -> None:
    """Phase 1 remediation round 5, finding #5: an entry whose own
    reported owner does not match the wallet_address this call was made
    for must never be silently trusted -- this is the whole contract of
    getTokenAccountsByOwner."""
    accounts = [_jsonparsed_token_account(owner="SomeoneElsesWallet")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="does not match the requested wallet_address"):
        await client.get_token_accounts("SomeWallet")
    await http_client.aclose()


async def test_helius_get_token_accounts_returns_immutable_raw_mapping() -> None:
    accounts = [_jsonparsed_token_account()]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    [account] = await client.get_token_accounts("SomeWallet")
    with pytest.raises(TypeError):
        account.raw["pubkey"] = "tampered"  # type: ignore[index]
    await http_client.aclose()


# --- R6 finding #4: TokenAccountInfo.raw must be *deeply* immutable and --
# --- alias-safe -- a shallow MappingProxyType(entry) only freezes the ---
# --- top level. -----------------------------------------------------------


async def test_helius_get_token_accounts_raw_nested_dict_is_immutable() -> None:
    accounts = [_jsonparsed_token_account()]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    [account] = await client.get_token_accounts("SomeWallet")
    nested_info = account.raw["account"]["data"]["parsed"]["info"]  # type: ignore[index]
    with pytest.raises(TypeError):
        nested_info["mint"] = "tampered"
    await http_client.aclose()


async def test_helius_get_token_accounts_raw_nested_list_is_immutable_tuple() -> None:
    accounts = [_jsonparsed_token_account()]
    accounts[0]["account"]["data"]["parsed"]["info"]["extraList"] = [1, 2, 3]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    [account] = await client.get_token_accounts("SomeWallet")
    nested_info = account.raw["account"]["data"]["parsed"]["info"]  # type: ignore[index]
    extra_list = nested_info["extraList"]
    assert isinstance(extra_list, tuple)
    with pytest.raises(TypeError):
        extra_list[0] = 99  # type: ignore[index]
    await http_client.aclose()


def test_deep_freeze_source_mutation_does_not_alter_the_frozen_copy() -> None:
    """Direct unit test of ``_deep_freeze`` itself (Phase 1 remediation
    round 6, finding #4): unlike an HTTP round trip (which already forces
    a fresh ``json.loads`` on the client side, incidentally de-aliasing
    from whatever the test constructed), this proves the alias-safety
    property ``_deep_freeze`` is actually responsible for -- mutating the
    *source* structure after freezing must never retroactively alter the
    frozen copy, at any nesting depth."""
    from argus.providers.helius.client import _deep_freeze

    source = {"a": {"b": [1, 2, {"c": "original"}]}}
    frozen = _deep_freeze(source)

    # Mutate the source structure -- top level, nested dict, and nested
    # list-of-dicts -- after freezing.
    source["a"]["b"][2]["c"] = "mutated"
    source["a"]["new_key"] = "also mutated"
    source["b"] = "top-level mutation"

    assert frozen["a"]["b"][2]["c"] == "original"  # type: ignore[index]
    assert "new_key" not in frozen["a"]  # type: ignore[operator]
    assert "b" not in frozen or frozen is not source


def test_deep_freeze_produces_immutable_structures_at_every_level() -> None:
    from argus.providers.helius.client import _deep_freeze

    frozen = _deep_freeze({"a": {"b": [1, {"c": 2}]}})
    with pytest.raises(TypeError):
        frozen["a"] = "tampered"  # type: ignore[index]
    with pytest.raises(TypeError):
        frozen["a"]["b"] = []  # type: ignore[index]
    assert isinstance(frozen["a"]["b"], tuple)  # type: ignore[index]
    with pytest.raises(TypeError):
        frozen["a"]["b"][1]["c"] = 99  # type: ignore[index]


async def test_helius_get_token_accounts_raw_does_not_alias_the_source_entry() -> None:
    """End-to-end control alongside the direct ``_deep_freeze`` tests
    above: even though an HTTP round trip already forces a fresh
    ``json.loads`` on the client side (so this alone cannot discriminate
    old vs. new behavior), the returned evidence must still agree with
    what was actually sent, unaffected by any later mutation to whatever
    object the test harness happens to still hold a reference to."""
    accounts = [_jsonparsed_token_account()]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    [account] = await client.get_token_accounts("SomeWallet")

    # Mutate the original source structure the mock handler still holds a
    # reference to, *after* the call has already returned.
    accounts[0]["account"]["data"]["parsed"]["info"]["mint"] = "MutatedAfterTheFact"

    nested_info = account.raw["account"]["data"]["parsed"]["info"]  # type: ignore[index]
    assert nested_info["mint"] == "MintA"
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
    transaction_result = _valid_transaction_result()

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


# --- R6 finding #4: the JSON-RPC envelope itself is validated for every --
# --- HTTP RPC call -- exact jsonrpc version, exact request-id type/value, -
# --- and result/error mutual exclusivity. ----------------------------------


async def test_helius_rpc_envelope_id_mismatch_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": 12345})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="response 'id' 2 does not match the request id 1"):
        await client.get_slot()
    await http_client.aclose()


async def test_helius_rpc_envelope_bool_id_never_matches_the_real_request_id() -> None:
    """``bool`` is an ``int`` subclass in Python -- a response carrying
    ``"id": true`` must never be silently misread as acknowledging request
    id ``1``."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": True, "result": 12345})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="response 'id' True does not match the request id 1"):
        await client.get_slot()
    await http_client.aclose()


async def test_helius_rpc_envelope_missing_id_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": 12345})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="response 'id' None does not match"):
        await client.get_slot()
    await http_client.aclose()


async def test_helius_rpc_envelope_version_mismatch_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "1.0", "id": 1, "result": 12345})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="unsupported/missing 'jsonrpc' version"):
        await client.get_slot()
    await http_client.aclose()


async def test_helius_rpc_envelope_missing_version_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 1, "result": 12345})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="unsupported/missing 'jsonrpc' version"):
        await client.get_slot()
    await http_client.aclose()


async def test_helius_rpc_envelope_result_and_error_both_present_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": 12345,
                "error": {"code": -32000, "message": "also an error?"},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="both 'result' and 'error' present"):
        await client.get_slot()
    await http_client.aclose()


async def test_helius_rpc_envelope_non_object_response_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="expected a JSON object envelope"):
        await client.get_slot()
    await http_client.aclose()


async def test_helius_rpc_envelope_valid_boundary_accepted() -> None:
    """Positive control: an exactly-matching id/version and a bare
    'result' key is accepted -- the envelope checks above are not
    over-eager."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": 12345})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    assert await client.get_slot() == 12345
    await http_client.aclose()


# --- R6 finding #4: get_transaction binds response identity to the -------
# --- request -- a structurally valid response for a *different* ----------
# --- transaction must never be accepted or persisted under the requested -
# --- identity. --------------------------------------------------------------


async def test_helius_get_transaction_wrong_returned_signature_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["transaction"]["signatures"] = ["a-completely-different-signature"]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError,
        match="response's primary signature 'a-completely-different-signature' does not match "
        "the requested signature 'some-signature'",
    ):
        await client.get_transaction("some-signature")
    await http_client.aclose()


# --- R6 finding #4: strict numeric domains -- unsigned-64-bit width -------
# --- bounds, ASCII-only decimal-digit amount strings, bounded digit ------
# --- counts before an expensive int() conversion. --------------------------


async def test_helius_get_transaction_overflow_fee_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["fee"] = 2**64  # one past the real unsigned-64-bit maximum
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'meta.fee' is not a valid unsigned-64-bit integer"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_fee_at_u64_max_accepted() -> None:
    """Positive control: the exact unsigned-64-bit maximum is a valid
    boundary value, not an off-by-one rejection."""

    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["fee"] = 2**64 - 1
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    result = await client.get_transaction("some-signature")
    assert result["meta"]["fee"] == 2**64 - 1
    await http_client.aclose()


async def test_helius_get_transaction_overflow_slot_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["slot"] = 2**64
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'slot' is not a valid unsigned-64-bit integer"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_overflow_balance_entry_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["preBalances"] = [2**64, 0]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError, match="'meta.preBalances' is not a list of valid unsigned-64-bit"
    ):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_huge_token_amount_string_rejected() -> None:
    """A numeric string far longer than any real unsigned-64-bit amount
    could ever be must be rejected on digit-count alone, before an
    expensive arbitrary-precision ``int()`` conversion is ever attempted."""

    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["preTokenBalances"] = [
            _valid_token_balance_entry(uiTokenAmount={"amount": "9" * 100, "decimals": 6})
        ]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'uiTokenAmount.amount' is not a valid ASCII-digit"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_token_amount_string_overflowing_u64_rejected() -> None:
    """20 ASCII digits alone does not guarantee the value fits in an
    unsigned 64-bit integer (2**64 - 1 is also 20 digits) -- the numeric
    value itself, not merely the digit count, must be bounded."""

    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["preTokenBalances"] = [
            _valid_token_balance_entry(uiTokenAmount={"amount": "9" * 20, "decimals": 6})
        ]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'uiTokenAmount.amount' is not a valid ASCII-digit"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_token_amount_at_u64_max_accepted() -> None:
    """Positive control: the exact unsigned-64-bit maximum, as a 20-digit
    ASCII decimal string, is a valid boundary value."""

    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["preTokenBalances"] = [
            _valid_token_balance_entry(uiTokenAmount={"amount": str(2**64 - 1), "decimals": 6})
        ]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    result = await client.get_transaction("some-signature")
    assert result["meta"]["preTokenBalances"][0]["uiTokenAmount"]["amount"] == str(2**64 - 1)
    await http_client.aclose()


async def test_helius_get_transaction_unicode_digit_token_amount_rejected() -> None:
    """Python's ``str.isdigit()``/``int()`` both accept a wide range of
    non-ASCII Unicode digit characters (e.g. Arabic-Indic digits) -- a
    real Solana RPC response never emits these, and this client must
    never silently normalize them on-the-fly."""

    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["preTokenBalances"] = [
            # "١٢٣" -- Arabic-Indic digits for "123"; int("١٢٣") == 123 in
            # real Python, and "١٢٣".isdigit() is also True.
            _valid_token_balance_entry(uiTokenAmount={"amount": "١٢٣", "decimals": 6})
        ]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'uiTokenAmount.amount' is not a valid ASCII-digit"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_signatures_for_address_negative_slot_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": [{"signature": "sig-1", "slot": -1, "err": None}],
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError,
        match="'signature'/'slot' are not a non-empty string / valid unsigned-64-bit integer",
    ):
        await client.get_signatures_for_address("SomeWallet")
    await http_client.aclose()


async def test_helius_get_signatures_for_address_negative_block_time_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": [{"signature": "sig-1", "slot": 100, "blockTime": -1, "err": None}],
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError, match="'blockTime' is not null or a valid unsigned-64-bit integer"
    ):
        await client.get_signatures_for_address("SomeWallet")
    await http_client.aclose()


async def test_helius_get_signatures_for_address_block_time_too_large_for_datetime_rejected() -> (
    None
):
    """Bounded to a valid unsigned-64-bit integer, but still far outside
    any value ``datetime.fromtimestamp`` can represent -- the conversion
    itself must be safely validated, never allowed to crash the caller
    with an unhandled exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": [{"signature": "sig-1", "slot": 100, "blockTime": 2**63, "err": None}],
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="cannot be represented as a UTC timestamp"):
        await client.get_signatures_for_address("SomeWallet")
    await http_client.aclose()


# --- R6 finding #4: getSignatureStatuses -- a missing 'err' key must not -
# --- become an implicit successful None through bare .get(). --------------


async def test_helius_get_signature_statuses_missing_err_key_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"value": [{"confirmationStatus": "confirmed", "slot": 100}]},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'err' is required but missing"):
        await client.get_signature_statuses(["sig-1"])
    await http_client.aclose()


async def test_helius_get_signature_statuses_missing_slot_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"value": [{"confirmationStatus": "confirmed", "err": None}]},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="'slot' is required but missing"):
        await client.get_signature_statuses(["sig-1"])
    await http_client.aclose()


# --- R6 finding #4: empty identity strings must fail the adapter contract -


async def test_helius_get_transaction_empty_signature_string_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["transaction"]["signatures"] = [""]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError, match="'transaction.signatures' is not a non-empty list of non-empty"
    ):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_empty_account_key_string_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["transaction"]["message"]["accountKeys"] = ["WalletAddress1", ""]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError, match="'transaction.message.accountKeys' is not a list of pubkey"
    ):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_transaction_empty_token_balance_mint_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = _valid_transaction_result()
        result["meta"]["preTokenBalances"] = [_valid_token_balance_entry(mint="")]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="missing a non-empty 'mint'/'owner' identity string"):
        await client.get_transaction("some-signature")
    await http_client.aclose()


async def test_helius_get_token_accounts_empty_pubkey_rejected() -> None:
    accounts = [_jsonparsed_token_account(pubkey="")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="malformed entry, missing a non-empty 'pubkey'"):
        await client.get_token_accounts("SomeWallet")
    await http_client.aclose()


async def test_helius_get_token_accounts_empty_owner_rejected() -> None:
    accounts = [_jsonparsed_token_account(owner="")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": accounts}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(HeliusRpcError, match="missing non-empty 'mint'/'owner' identity strings"):
        await client.get_token_accounts("SomeWallet")
    await http_client.aclose()


async def test_helius_get_signatures_for_address_empty_signature_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": [{"signature": "", "slot": 100}]},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HeliusRpcClient("fake-key", http_client=http_client)
    with pytest.raises(
        HeliusRpcError,
        match="'signature'/'slot' are not a non-empty string / valid unsigned-64-bit integer",
    ):
        await client.get_signatures_for_address("SomeWallet")
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
