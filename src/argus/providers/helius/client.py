"""Helius standard RPC + standard WebSocket adapter (MASTER_SPEC.md
section 12, PROV-001: standard RPC/WSS only -- Helius-exclusive paid
historical APIs are never a Phase 1 dependency).

Credential-gated on ``HELIUS_API_KEY``: if unset, every method raises
:class:`~argus.providers.credentials.MissingProviderCredentialError`
immediately at client construction, never proceeding with a mocked
response while claiming live acceptance (MASTER_SPEC.md section 108).

Both the RPC client and the WebSocket stream take their transport as an
injected dependency (``httpx.AsyncClient`` / a :class:`WebSocketConnector`)
so unit tests exercise the real request/response/reconnect logic against a
fake transport instead of a live network connection.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from argus.clock import Clock
from argus.providers import SignatureInfo, SignatureStatusInfo, StreamNotification
from argus.providers.credentials import require_env_credential
from argus.providers.retry import RetryPolicy, request_with_retry
from argus.providers.usage import RequestUsageRecord, UsageRecorder

HELIUS_API_KEY_ENV_VAR = "HELIUS_API_KEY"
DEFAULT_RPC_BASE_URL = "https://mainnet.helius-rpc.com/"
DEFAULT_WS_BASE_URL = "wss://mainnet.helius-rpc.com/"

TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


class HeliusRpcError(RuntimeError):
    """A well-formed JSON-RPC error response from Helius."""


def resolve_helius_api_key(env: Mapping[str, str]) -> str:
    return require_env_credential(env, HELIUS_API_KEY_ENV_VAR)


class HeliusRpcClient:
    """Implements :class:`argus.providers.ChainProvider` against Helius's
    standard Solana JSON-RPC endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        http_client: httpx.AsyncClient,
        base_url: str = DEFAULT_RPC_BASE_URL,
        retry_policy: RetryPolicy | None = None,
        usage_recorder: UsageRecorder | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._api_key = api_key
        self._http = http_client
        self._base_url = base_url
        self._retry_policy = retry_policy or RetryPolicy()
        self._usage_recorder = usage_recorder
        self._clock = clock or Clock()

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        requested_at = self._clock.utc_now()
        start = time.monotonic()
        outcome = await request_with_retry(
            lambda: self._http.post(
                self._base_url, params={"api-key": self._api_key}, json=payload
            ),
            policy=self._retry_policy,
        )
        response = outcome.response
        latency_ms = int((time.monotonic() - start) * 1000)
        if self._usage_recorder is not None:
            await self._usage_recorder.record_request(
                RequestUsageRecord(
                    provider="helius",
                    endpoint=method,
                    request_class="rpc",
                    requested_at=requested_at,
                    status="ok" if not response.is_error else "http_error",
                    cache_hit=False,
                    response_at=self._clock.utc_now(),
                    latency_ms=latency_ms,
                    retry_count=outcome.retry_count,
                    bytes_received=len(response.content),
                )
            )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise HeliusRpcError(f"{method} failed: {data['error']}")
        if "result" not in data:
            # Malformed/unexpected-shape response: neither a well-formed
            # JSON-RPC error nor a result. Rejected explicitly here rather
            # than left to raise a bare KeyError below (acceptance
            # criterion #14: adapter contract validation must reject
            # malformed provider responses, not crash unpredictably).
            raise HeliusRpcError(
                f"{method}: malformed response, missing both 'result' and 'error': {data!r}"
            )
        return data["result"]

    async def get_transaction(self, signature: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._rpc(
            "getTransaction",
            [signature, {"maxSupportedTransactionVersion": 0, "encoding": "json"}],
        )
        if not isinstance(result, dict) or "meta" not in result or "transaction" not in result:
            raise HeliusRpcError(
                f"getTransaction: malformed response for {signature!r}, missing 'meta'/"
                f"'transaction': {result!r}"
            )
        if not isinstance(result["meta"], dict):
            raise HeliusRpcError(f"getTransaction: 'meta' is not an object: {result['meta']!r}")
        return result

    async def get_signatures_for_address(
        self,
        wallet_address: str,
        *,
        until_signature: str | None = None,
        before_signature: str | None = None,
        limit: int = 1000,
    ) -> list[SignatureInfo]:
        options: dict[str, Any] = {"limit": limit}
        if until_signature is not None:
            options["until"] = until_signature
        if before_signature is not None:
            options["before"] = before_signature
        result = await self._rpc("getSignaturesForAddress", [wallet_address, options])
        if not isinstance(result, list):
            raise HeliusRpcError(f"getSignaturesForAddress: expected a list, got {result!r}")
        entries = []
        for entry in result:
            if not isinstance(entry, dict) or "signature" not in entry or "slot" not in entry:
                raise HeliusRpcError(
                    f"getSignaturesForAddress: malformed entry, missing 'signature'/'slot': {entry!r}"
                )
            if not isinstance(entry["signature"], str) or not isinstance(entry["slot"], int):
                raise HeliusRpcError(
                    f"getSignaturesForAddress: 'signature'/'slot' have wrong type: {entry!r}"
                )
            block_time_raw = entry.get("blockTime")
            if block_time_raw is not None and not isinstance(block_time_raw, int):
                raise HeliusRpcError(f"getSignaturesForAddress: non-integer blockTime: {entry!r}")
            entries.append(
                SignatureInfo(
                    signature=entry["signature"],
                    slot=entry["slot"],
                    block_time=(
                        datetime.fromtimestamp(block_time_raw, tz=UTC)
                        if block_time_raw is not None
                        else None
                    ),
                    err=entry.get("err"),
                )
            )
        return entries

    async def get_signature_statuses(self, signatures: list[str]) -> list[SignatureStatusInfo]:
        result = await self._rpc(
            "getSignatureStatuses", [signatures, {"searchTransactionHistory": True}]
        )
        if not isinstance(result, dict) or "value" not in result:
            raise HeliusRpcError(
                f"getSignatureStatuses: malformed response, missing 'value': {result!r}"
            )
        values = result["value"]
        if not isinstance(values, list) or len(values) != len(signatures):
            raise HeliusRpcError(
                f"getSignatureStatuses: expected {len(signatures)} status entries, got {values!r}"
            )
        statuses = []
        for signature, entry in zip(signatures, values, strict=True):
            if entry is None:
                statuses.append(
                    SignatureStatusInfo(
                        signature=signature, confirmation_status=None, err=None, slot=None
                    )
                )
                continue
            if not isinstance(entry, dict):
                raise HeliusRpcError(f"getSignatureStatuses: malformed status entry: {entry!r}")
            confirmation_status = entry.get("confirmationStatus")
            if confirmation_status is not None and confirmation_status not in (
                "processed",
                "confirmed",
                "finalized",
            ):
                raise HeliusRpcError(
                    f"getSignatureStatuses: unknown confirmationStatus {confirmation_status!r}"
                )
            statuses.append(
                SignatureStatusInfo(
                    signature=signature,
                    confirmation_status=confirmation_status,
                    err=entry.get("err"),
                    slot=entry.get("slot"),
                )
            )
        return statuses

    async def get_balance(self, wallet_address: str) -> int:
        result = await self._rpc("getBalance", [wallet_address])
        if (
            not isinstance(result, dict)
            or "value" not in result
            or not isinstance(result["value"], int)
        ):
            raise HeliusRpcError(
                f"getBalance: malformed response, expected {{'value': int}}: {result!r}"
            )
        value: int = result["value"]
        return value

    async def get_token_accounts(self, wallet_address: str) -> list[dict[str, Any]]:
        result = await self._rpc(
            "getTokenAccountsByOwner",
            [wallet_address, {"programId": TOKEN_PROGRAM_ID}, {"encoding": "jsonParsed"}],
        )
        if (
            not isinstance(result, dict)
            or "value" not in result
            or not isinstance(result["value"], list)
        ):
            raise HeliusRpcError(
                f"getTokenAccountsByOwner: malformed response, expected {{'value': list}}: {result!r}"
            )
        value: list[dict[str, Any]] = result["value"]
        return value

    async def get_slot(self) -> int:
        result = await self._rpc("getSlot", [])
        if not isinstance(result, int):
            raise HeliusRpcError(f"getSlot: expected an integer, got {result!r}")
        return result


class WebSocketConnection(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


class WebSocketConnector(Protocol):
    """Abstracts the underlying WebSocket library so tests never open a
    real socket. ``connect`` returns an async context manager yielding a
    :class:`WebSocketConnection`."""

    def connect(self, url: str) -> Any: ...


class HeliusWebSocketStream:
    """Implements :class:`argus.providers.LiveChainStream` against
    Helius's standard WebSocket ``logsSubscribe`` endpoint.

    ``subscribe_wallet`` never treats a dropped connection as "no new
    activity": any read/connect failure raises out of the async generator
    so the caller (the stream manager) can detect the disconnect and
    trigger truth-path reconciliation, per MASTER_SPEC.md section 19.
    """

    def __init__(
        self,
        api_key: str,
        *,
        connector: WebSocketConnector,
        base_url: str = DEFAULT_WS_BASE_URL,
    ) -> None:
        self._api_key = api_key
        self._connector = connector
        self._base_url = base_url

    async def subscribe_wallet(self, wallet_address: str) -> AsyncIterator[StreamNotification]:
        url = f"{self._base_url}?api-key={self._api_key}"
        async with self._connector.connect(url) as connection:
            subscribe_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "logsSubscribe",
                "params": [{"mentions": [wallet_address]}, {"commitment": "confirmed"}],
            }
            await connection.send(json.dumps(subscribe_request))
            ack_raw = await connection.recv()
            ack = json.loads(ack_raw)
            if "result" not in ack or not isinstance(ack["result"], int):
                raise HeliusRpcError(f"logsSubscribe failed for {wallet_address!r}: {ack}")
            subscription_id = ack["result"]

            while True:
                raw = await connection.recv()
                message = json.loads(raw)
                if message.get("method") != "logsNotification":
                    # A message that isn't this subscription's notification
                    # (e.g. an unrelated ack) is not "no new activity" --
                    # it must not be silently swallowed as if it were.
                    if "params" not in message and "id" in message:
                        continue  # a benign response to a different request id
                    raise HeliusRpcError(f"unexpected WebSocket message shape: {message!r}")
                params = message.get("params")
                if not isinstance(params, dict) or params.get("subscription") != subscription_id:
                    raise HeliusRpcError(
                        f"logsNotification for the wrong subscription id: {message!r}"
                    )
                result = params.get("result")
                if not isinstance(result, dict):
                    raise HeliusRpcError(f"logsNotification missing 'result': {message!r}")
                context = result.get("context")
                value = result.get("value")
                if not isinstance(context, dict) or not isinstance(context.get("slot"), int):
                    raise HeliusRpcError(f"logsNotification missing context.slot: {message!r}")
                if (
                    not isinstance(value, dict)
                    or not isinstance(value.get("signature"), str)
                    or "err" not in value
                ):
                    raise HeliusRpcError(
                        f"logsNotification missing value.signature/value.err: {message!r}"
                    )
                yield StreamNotification(
                    wallet_address=wallet_address,
                    signature=value["signature"],
                    slot=context["slot"],
                )

    async def unsubscribe_wallet(self, wallet_address: str) -> None:
        # This minimal Phase 1 stream keeps one subscription per
        # subscribe_wallet() call/connection; callers stop iterating (or
        # cancel the task) to unsubscribe, which closes the connection via
        # the `async with` block above. Explicit per-subscription-id
        # unsubscribe (multiple wallets sharing one connection) is left to
        # a later phase's stream manager.
        return
