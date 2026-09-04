"""argus.executor.live_submission — MASTER_SPEC.md section 70 (LIVE
EXECUTION SECURITY MODEL), FSR-01 (``argus-final-spec-recovery-001``).

The ONE module in this codebase that may ever broadcast a signed
transaction to the Solana network. Deliberately kept physically inside
``argus.executor`` rather than added to the shared
``argus.providers.helius.client.HeliusRpcClient`` (used by research/
ingestion for read-only chain queries): a real broadcast capability must
never become reachable from a non-executor import graph just because it
shares a client class with read-only methods those callers legitimately
use. Reuses the SAME generic retry/usage-accounting plumbing every other
provider adapter uses (``argus.providers.http.send_with_usage``,
``argus.providers.retry.RetryPolicy``) -- those are provider-agnostic
utilities, not something this module reimplements.

Read-only chain-confirmation queries (``getSignatureStatuses``/
``getTransaction``) deliberately are NOT duplicated here --
``argus.executor.confirmation`` takes a already-constructed
``HeliusRpcClient`` (or any object satisfying its narrow ``Protocol``) for
those, since read-only queries are not a live-broadcast capability and
that client is already validated/tested Phase 1 infrastructure.
"""

from __future__ import annotations

from typing import Any, TypeGuard

import httpx

from argus.clock import Clock
from argus.providers.contract import ProviderResponseError
from argus.providers.http import send_with_usage
from argus.providers.retry import RetryPolicy
from argus.providers.usage import UsageRecorder

DEFAULT_RPC_BASE_URL = "https://mainnet.helius-rpc.com/"

_JSON_RPC_REQUEST_ID = 1


class SubmissionRpcError(ProviderResponseError):
    """Raised on a malformed/error JSON-RPC response to ``sendTransaction``
    -- mirrors ``argus.providers.helius.client.HeliusRpcError``'s envelope
    validation discipline (never trust an unvalidated ``result``)."""

    def __init__(self, message: str, *, usage_status: str = "rpc_error") -> None:
        super().__init__(message)
        self.usage_status = usage_status


def _is_nonempty_str(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value)


class SolanaSubmissionClient:
    """Production-capable ``sendTransaction`` broadcast adapter. Takes an
    already-SIGNED transaction's wire bytes (base64) -- this class never
    signs anything itself (that seam is exclusively
    ``argus.executor.live_signing.FileKeypairSigner``, upstream of this
    class in ``argus.executor.dispatch.DispatchGuard``'s ordering)."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        api_key: str,
        base_url: str = DEFAULT_RPC_BASE_URL,
        retry_policy: RetryPolicy | None = None,
        usage_recorder: UsageRecorder | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._http = http_client
        self._api_key = api_key
        self._base_url = base_url
        self._retry_policy = retry_policy or RetryPolicy()
        self._usage_recorder = usage_recorder
        self._clock = clock or Clock()

    async def send_transaction(
        self, signed_transaction_base64: str, *, skip_preflight: bool = False
    ) -> str:
        """Broadcasts an already-signed transaction. Returns the
        transaction signature. Raises :class:`SubmissionRpcError` on any
        malformed/error RPC response -- never returns a fabricated
        signature."""
        payload = {
            "jsonrpc": "2.0",
            "id": _JSON_RPC_REQUEST_ID,
            "method": "sendTransaction",
            "params": [
                signed_transaction_base64,
                {"encoding": "base64", "skipPreflight": skip_preflight},
            ],
        }

        def _process(response: httpx.Response) -> str:
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise SubmissionRpcError(f"sendTransaction: malformed response: {data!r}")
            if data.get("id") != _JSON_RPC_REQUEST_ID:
                raise SubmissionRpcError(
                    f"sendTransaction: response 'id' {data.get('id')!r} does not match request "
                    f"id {_JSON_RPC_REQUEST_ID!r}"
                )
            if "error" in data:
                raise SubmissionRpcError(f"sendTransaction failed: {data['error']}")
            result = data.get("result")
            if not _is_nonempty_str(result):
                raise SubmissionRpcError(
                    f"sendTransaction: malformed response, missing/invalid 'result': {data!r}"
                )
            return result

        return await send_with_usage(
            lambda: self._http.post(
                self._base_url, params={"api-key": self._api_key}, json=payload
            ),
            process=_process,
            policy=self._retry_policy,
            usage_recorder=self._usage_recorder,
            clock=self._clock,
            provider="helius",
            endpoint="sendTransaction",
            request_class="submission",
        )
