"""FSR-01 (``argus-final-spec-recovery-001``): production-capable
Solana transaction broadcast adapter. Exercised entirely against
``httpx.MockTransport`` (no real network, no real signature/broadcast) --
mirrors ``tests/unit/test_provider_adapters.py``'s own Helius test
pattern.
"""

from __future__ import annotations

import json

import httpx
import pytest

from argus.executor.live_submission import SolanaSubmissionClient, SubmissionRpcError


async def test_send_transaction_returns_signature_on_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api-key"] == "fake-key"
        body = json.loads(request.content)
        assert body["method"] == "sendTransaction"
        assert body["params"][0] == "AAAA=="
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "TestSignature111"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = SolanaSubmissionClient(http_client=http_client, api_key="fake-key")
    signature = await client.send_transaction("AAAA==")
    assert signature == "TestSignature111"
    await http_client.aclose()


async def test_send_transaction_raises_on_rpc_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32002, "message": "bad tx"}},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = SolanaSubmissionClient(http_client=http_client, api_key="fake-key")
    with pytest.raises(SubmissionRpcError, match="bad tx"):
        await client.send_transaction("AAAA==")
    await http_client.aclose()


async def test_send_transaction_raises_on_missing_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = SolanaSubmissionClient(http_client=http_client, api_key="fake-key")
    with pytest.raises(SubmissionRpcError, match="malformed response"):
        await client.send_transaction("AAAA==")
    await http_client.aclose()


async def test_send_transaction_raises_on_id_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 999, "result": "TestSignature111"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = SolanaSubmissionClient(http_client=http_client, api_key="fake-key")
    with pytest.raises(SubmissionRpcError, match="does not match"):
        await client.send_transaction("AAAA==")
    await http_client.aclose()


async def test_skip_preflight_flag_is_forwarded() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["options"] = body["params"][1]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "sig"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = SolanaSubmissionClient(http_client=http_client, api_key="fake-key")
    await client.send_transaction("AAAA==", skip_preflight=True)
    assert captured["options"] == {"encoding": "base64", "skipPreflight": True}
    await http_client.aclose()
