"""argus.executor.simulation — real (never fabricated) pre/post account
evidence for an UNSIGNED transaction, R2-01 (``argus-final-spec-recovery-002``).

Read-only, side-effect-free chain queries only (``getMultipleAccounts`` +
``simulateTransaction`` with ``sigVerify: false`` -- neither call ever
signs or broadcasts anything), so this is safe to construct even outside
the executor's live-armed path; it is what makes a real
:class:`~argus.executor.attestation.UnsignedTransactionShape` possible at
all (see ``tx_deserialize.py``). Kept physically inside ``argus.executor``
rather than folded into the shared read-only Helius client, matching
FSR-01's isolation precedent for ``live_submission.py``: a future reader
must never conflate "this queries chain state for the executor's own
pre-signing checks" with "this is generic read-only research
infrastructure everyone should call."
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from argus.clock import Clock
from argus.providers.contract import ProviderResponseError
from argus.providers.http import send_with_usage
from argus.providers.retry import RetryPolicy
from argus.providers.usage import UsageRecorder

DEFAULT_RPC_BASE_URL = "https://mainnet.helius-rpc.com/"

_ACCOUNTS_ID = 1
_SIMULATE_ID = 2


class SimulationRpcError(ProviderResponseError):
    """Raised on a malformed/error JSON-RPC response -- never proceeds
    with a partially-parsed or guessed account snapshot."""


@dataclass(frozen=True)
class AccountSnapshot:
    address: str
    exists: bool
    owner_program: str | None
    """The program that OWNS this account at the account level (e.g. the
    SPL Token program id) -- ``None`` when ``exists`` is ``False``."""
    lamports: int
    data: bytes


@dataclass(frozen=True)
class SimulationResult:
    err: Any | None
    """The ``simulateTransaction`` RPC's own ``err`` field -- non-``None``
    means the transaction would fail if actually submitted."""
    pre_accounts: dict[str, AccountSnapshot]
    post_accounts: dict[str, AccountSnapshot]


class TransactionSimulationProvider(Protocol):
    async def simulate(
        self, unsigned_transaction_base64: str, *, watch_addresses: list[str]
    ) -> SimulationResult: ...


def _parse_account_value(address: str, value: dict[str, Any] | None) -> AccountSnapshot:
    if value is None:
        return AccountSnapshot(
            address=address, exists=False, owner_program=None, lamports=0, data=b""
        )
    owner = value.get("owner")
    lamports = value.get("lamports")
    raw_data = value.get("data")
    if not isinstance(owner, str) or not isinstance(lamports, int):
        raise SimulationRpcError(f"malformed account value for {address}: {value!r}")
    data_b64 = raw_data[0] if isinstance(raw_data, list) and raw_data else None
    data = base64.b64decode(data_b64) if isinstance(data_b64, str) else b""
    return AccountSnapshot(
        address=address, exists=True, owner_program=owner, lamports=lamports, data=data
    )


class SolanaTransactionSimulationClient:
    """Production-capable simulation adapter -- ``getMultipleAccounts``
    for the PRE state, then ``simulateTransaction`` (``sigVerify: false``,
    ``replaceRecentBlockhash: true``, requesting post-execution account
    data for the SAME address list) for the POST state. Never signs or
    submits anything; both RPC methods are read-only by design."""

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

    async def _rpc(self, payload: dict[str, Any], *, endpoint: str) -> dict[str, Any]:
        def _process(response: httpx.Response) -> dict[str, Any]:
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise SimulationRpcError(f"{endpoint}: malformed response: {data!r}")
            if data.get("id") != payload["id"]:
                raise SimulationRpcError(
                    f"{endpoint}: response 'id' {data.get('id')!r} does not match request "
                    f"id {payload['id']!r}"
                )
            if "error" in data:
                raise SimulationRpcError(f"{endpoint} failed: {data['error']}")
            result = data.get("result")
            if not isinstance(result, dict):
                raise SimulationRpcError(
                    f"{endpoint}: malformed response, missing 'result': {data!r}"
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
            endpoint=endpoint,
            request_class="simulation",
        )

    async def simulate(
        self, unsigned_transaction_base64: str, *, watch_addresses: list[str]
    ) -> SimulationResult:
        pre_result = await self._rpc(
            {
                "jsonrpc": "2.0",
                "id": _ACCOUNTS_ID,
                "method": "getMultipleAccounts",
                "params": [watch_addresses, {"encoding": "base64"}],
            },
            endpoint="getMultipleAccounts",
        )
        pre_values = pre_result.get("value")
        if not isinstance(pre_values, list) or len(pre_values) != len(watch_addresses):
            raise SimulationRpcError(f"getMultipleAccounts: unexpected value shape: {pre_values!r}")
        pre_accounts = {
            address: _parse_account_value(address, value)
            for address, value in zip(watch_addresses, pre_values, strict=True)
        }

        sim_result = await self._rpc(
            {
                "jsonrpc": "2.0",
                "id": _SIMULATE_ID,
                "method": "simulateTransaction",
                "params": [
                    unsigned_transaction_base64,
                    {
                        "encoding": "base64",
                        "sigVerify": False,
                        "replaceRecentBlockhash": True,
                        "accounts": {"encoding": "base64", "addresses": watch_addresses},
                    },
                ],
            },
            endpoint="simulateTransaction",
        )
        sim_value = sim_result.get("value")
        if not isinstance(sim_value, dict):
            raise SimulationRpcError(f"simulateTransaction: malformed 'value': {sim_value!r}")
        post_values = sim_value.get("accounts")
        if not isinstance(post_values, list) or len(post_values) != len(watch_addresses):
            raise SimulationRpcError(
                f"simulateTransaction: unexpected 'accounts' shape: {post_values!r}"
            )
        post_accounts = {
            address: _parse_account_value(address, value)
            for address, value in zip(watch_addresses, post_values, strict=True)
        }

        return SimulationResult(
            err=sim_value.get("err"), pre_accounts=pre_accounts, post_accounts=post_accounts
        )
