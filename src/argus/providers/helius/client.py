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

import asyncio
import collections
import contextlib
import json
import sys
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Protocol, TypeGuard

import httpx

from argus.clock import Clock
from argus.providers import SignatureInfo, SignatureStatusInfo, StreamNotification
from argus.providers.contract import ProviderResponseError
from argus.providers.credentials import require_env_credential
from argus.providers.http import send_with_usage
from argus.providers.models import TokenAccountInfo
from argus.providers.retry import RetryPolicy
from argus.providers.usage import UsageRecorder

HELIUS_API_KEY_ENV_VAR = "HELIUS_API_KEY"
DEFAULT_RPC_BASE_URL = "https://mainnet.helius-rpc.com/"
DEFAULT_WS_BASE_URL = "wss://mainnet.helius-rpc.com/"

TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

_DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
_DEFAULT_SEND_TIMEOUT_SECONDS = 10.0
_DEFAULT_ACK_TIMEOUT_SECONDS = 10.0
_DEFAULT_CLOSE_TIMEOUT_SECONDS = 10.0


def _is_strict_int(value: Any) -> TypeGuard[int]:
    """``True``/``False`` are ``int`` subclasses in Python -- a provider
    response with a bool where an integer slot/id/decimals field belongs
    must never silently pass an ``isinstance(value, int)`` check (Phase 1
    remediation round 4, finding #4)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_strict_nonneg_int(value: Any) -> TypeGuard[int]:
    """As :func:`_is_strict_int`, plus rejecting negative values -- every
    slot/fee/balance/decimals field this client validates is a Solana
    concept with no legitimate negative value (Phase 1 remediation round
    5, finding #5)."""
    return _is_strict_int(value) and value >= 0


# SPL token decimals is stored on-chain as a single unsigned byte
# (Solana's Mint account layout) -- any larger value is definitionally
# impossible, not merely implausible.
_MAX_TOKEN_DECIMALS = 255


def _is_matching_request_id(value: Any, expected: int) -> bool:
    """Exact type+value match against a JSON-RPC request id. Plain ``==``
    is not safe here: Python's ``bool`` is an ``int`` subclass and
    ``True == 1``, so a WebSocket message carrying JSON ``"id": true``
    would otherwise be silently misread as acknowledging request id 1
    (Phase 1 remediation round 5, finding #6)."""
    return _is_strict_int(value) and value == expected


def _is_valid_tx_err(value: Any) -> bool:
    """A Solana ``TransactionError`` is either ``null`` (success), a bare
    string variant (e.g. ``"AccountInUse"``), or an object variant (e.g.
    ``{"InstructionError": [...]}"``) -- never a number, bool, or list at
    the top level."""
    return value is None or isinstance(value, str | dict)


def _resolved_account_keys(value: Any) -> list[str] | None:
    """``transaction.message.accountKeys`` is either a bare list of
    base58 pubkey strings, or (``jsonParsed``/versioned-transaction
    encodings) a list of ``{"pubkey": str, ...}`` objects -- the same two
    shapes :func:`argus.parsing.generic_parser._account_keys` and
    :func:`argus.golden_fixtures._account_keys` already accept. Returns
    the resolved pubkey strings, or ``None`` if the shape is invalid
    (Phase 1 remediation round 5, finding #5)."""
    if not isinstance(value, list):
        return None
    resolved: list[str] = []
    for key in value:
        if isinstance(key, str):
            resolved.append(key)
        elif isinstance(key, dict) and isinstance(key.get("pubkey"), str):
            resolved.append(key["pubkey"])
        else:
            return None
    return resolved


class HeliusRpcError(ProviderResponseError):
    """A well-formed JSON-RPC error response from Helius, or a
    malformed/unexpected-shape response body.

    ``usage_status`` defaults to ``"rpc_error"`` -- a genuine well-formed
    provider-level error response is the common case this exception
    represents. The one raise site inside :meth:`HeliusRpcClient._rpc` for
    a response missing both ``result`` and ``error`` overrides it to
    ``"contract_error"`` (Phase 1 remediation round 2, finding #8): that
    case is a contract violation -- neither a well-formed RPC error nor a
    successful result -- not an application-level error the provider
    actually reported."""

    usage_status: str

    def __init__(self, message: str, *, usage_status: str = "rpc_error") -> None:
        super().__init__(message)
        self.usage_status = usage_status


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

    async def _rpc[T](self, method: str, params: list[Any], *, validate: Callable[[Any], T]) -> T:
        # Phase 1 remediation round 3, finding #3: the caller's full nested
        # contract validation (``validate``) runs *inside* this single
        # accounted operation, not after it returns. Previously each public
        # method re-validated the raw ``result`` after ``_rpc`` had already
        # returned -- so a malformed method-specific shape left an "ok"
        # usage row behind and only then raised. Now a malformed nested
        # result is classified as a genuine terminal outcome of this same
        # call (see ``send_with_usage``'s ``process`` contract), never a
        # second, unaccounted failure after an "ok" was already recorded.
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}

        def _process(response: httpx.Response) -> T:
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
                    f"{method}: malformed response, missing both 'result' and 'error': {data!r}",
                    usage_status="contract_error",
                )
            return validate(data["result"])

        return await send_with_usage(
            lambda: self._http.post(
                self._base_url, params={"api-key": self._api_key}, json=payload
            ),
            process=_process,
            policy=self._retry_policy,
            usage_recorder=self._usage_recorder,
            clock=self._clock,
            provider="helius",
            endpoint=method,
            request_class="rpc",
        )

    async def get_transaction(self, signature: str) -> dict[str, Any]:
        def _validate_token_balances(key: str, num_accounts: int, meta: dict[str, Any]) -> None:
            # Phase 1 remediation round 5, finding #5: preTokenBalances/
            # postTokenBalances are optional keys (a transaction that
            # never touches an SPL token account legitimately omits or
            # empties them), but when present every entry is fully
            # validated -- never trusted as opaque pass-through data, the
            # same discipline every other field on this response gets.
            entries = meta.get(key)
            if entries is None:
                return
            if not isinstance(entries, list):
                raise HeliusRpcError(
                    f"getTransaction: 'meta.{key}' is not a list: {entries!r}",
                    usage_status="contract_error",
                )
            for entry in entries:
                if not isinstance(entry, dict):
                    raise HeliusRpcError(
                        f"getTransaction: 'meta.{key}' entry is not an object: {entry!r}",
                        usage_status="contract_error",
                    )
                account_index = entry.get("accountIndex")
                if not _is_strict_nonneg_int(account_index) or account_index >= num_accounts:
                    raise HeliusRpcError(
                        f"getTransaction: 'meta.{key}' entry has an out-of-range or invalid "
                        f"accountIndex (accountKeys has {num_accounts} entries): {entry!r}",
                        usage_status="contract_error",
                    )
                mint = entry.get("mint")
                owner = entry.get("owner")
                if not isinstance(mint, str) or not isinstance(owner, str):
                    raise HeliusRpcError(
                        f"getTransaction: 'meta.{key}' entry is missing a string 'mint'/'owner': "
                        f"{entry!r}",
                        usage_status="contract_error",
                    )
                ui_token_amount = entry.get("uiTokenAmount")
                if not isinstance(ui_token_amount, dict):
                    raise HeliusRpcError(
                        f"getTransaction: 'meta.{key}' entry is missing 'uiTokenAmount': {entry!r}",
                        usage_status="contract_error",
                    )
                amount = ui_token_amount.get("amount")
                if not isinstance(amount, str) or not amount.isdigit():
                    raise HeliusRpcError(
                        f"getTransaction: 'meta.{key}' entry 'uiTokenAmount.amount' is not a "
                        f"nonnegative decimal string: {entry!r}",
                        usage_status="contract_error",
                    )
                decimals = ui_token_amount.get("decimals")
                if not _is_strict_nonneg_int(decimals) or decimals > _MAX_TOKEN_DECIMALS:
                    raise HeliusRpcError(
                        f"getTransaction: 'meta.{key}' entry 'uiTokenAmount.decimals' is out of "
                        f"bounds (0-{_MAX_TOKEN_DECIMALS}): {entry!r}",
                        usage_status="contract_error",
                    )

        def _validate(result: Any) -> dict[str, Any]:
            if not isinstance(result, dict) or "meta" not in result or "transaction" not in result:
                raise HeliusRpcError(
                    f"getTransaction: malformed response for {signature!r}, missing 'meta'/"
                    f"'transaction': {result!r}",
                    usage_status="contract_error",
                )
            meta = result["meta"]
            if not isinstance(meta, dict):
                raise HeliusRpcError(
                    f"getTransaction: 'meta' is not an object: {meta!r}",
                    usage_status="contract_error",
                )
            transaction = result["transaction"]
            if not isinstance(transaction, dict):
                raise HeliusRpcError(
                    f"getTransaction: 'transaction' is not an object: {transaction!r}",
                    usage_status="contract_error",
                )
            message = transaction.get("message")
            if not isinstance(message, dict):
                raise HeliusRpcError(
                    f"getTransaction: 'transaction.message' is not an object: {message!r}",
                    usage_status="contract_error",
                )
            account_keys = _resolved_account_keys(message.get("accountKeys"))
            if account_keys is None:
                raise HeliusRpcError(
                    "getTransaction: 'transaction.message.accountKeys' is not a list of pubkey "
                    f"strings/objects: {message.get('accountKeys')!r}",
                    usage_status="contract_error",
                )
            signatures = transaction.get("signatures")
            if (
                not isinstance(signatures, list)
                or not signatures
                or not all(isinstance(sig, str) for sig in signatures)
            ):
                raise HeliusRpcError(
                    "getTransaction: 'transaction.signatures' is not a non-empty list of "
                    f"strings: {signatures!r}",
                    usage_status="contract_error",
                )

            # Phase 1 remediation round 5, finding #5: deepen validation
            # beyond the structural shape checks above -- meta.err is
            # required (never merely validated-if-present), meta.fee and
            # the balance arrays must be genuinely well-formed integers
            # coherent with accountKeys' length, the top-level slot is
            # required, and any present token-balance entries are fully
            # validated field-by-field.
            if "err" not in meta:
                raise HeliusRpcError(
                    f"getTransaction: 'meta.err' is required but missing: {meta!r}",
                    usage_status="contract_error",
                )
            if not _is_valid_tx_err(meta["err"]):
                raise HeliusRpcError(
                    f"getTransaction: 'meta.err' has an invalid type: {meta['err']!r}",
                    usage_status="contract_error",
                )
            fee = meta.get("fee")
            if not _is_strict_nonneg_int(fee):
                raise HeliusRpcError(
                    f"getTransaction: 'meta.fee' is not a strict nonnegative integer: {fee!r}",
                    usage_status="contract_error",
                )
            num_accounts = len(account_keys)
            for balances_key in ("preBalances", "postBalances"):
                balances = meta.get(balances_key)
                if not isinstance(balances, list) or not all(
                    _is_strict_nonneg_int(v) for v in balances
                ):
                    raise HeliusRpcError(
                        f"getTransaction: 'meta.{balances_key}' is not a list of strict "
                        f"nonnegative integers: {balances!r}",
                        usage_status="contract_error",
                    )
                if len(balances) != num_accounts:
                    raise HeliusRpcError(
                        f"getTransaction: 'meta.{balances_key}' has {len(balances)} entries, "
                        f"which does not match accountKeys' {num_accounts} entries",
                        usage_status="contract_error",
                    )
            slot = result.get("slot")
            if not _is_strict_nonneg_int(slot):
                raise HeliusRpcError(
                    f"getTransaction: 'slot' is not a strict nonnegative integer: {slot!r}",
                    usage_status="contract_error",
                )
            block_time = result.get("blockTime")
            if block_time is not None and not _is_strict_nonneg_int(block_time):
                raise HeliusRpcError(
                    "getTransaction: 'blockTime' is not null or a strict nonnegative integer: "
                    f"{block_time!r}",
                    usage_status="contract_error",
                )
            _validate_token_balances("preTokenBalances", num_accounts, meta)
            _validate_token_balances("postTokenBalances", num_accounts, meta)
            return result

        return await self._rpc(
            "getTransaction",
            [signature, {"maxSupportedTransactionVersion": 0, "encoding": "json"}],
            validate=_validate,
        )

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

        def _validate(result: Any) -> list[SignatureInfo]:
            if not isinstance(result, list):
                raise HeliusRpcError(
                    f"getSignaturesForAddress: expected a list, got {result!r}",
                    usage_status="contract_error",
                )
            entries = []
            for entry in result:
                if not isinstance(entry, dict) or "signature" not in entry or "slot" not in entry:
                    raise HeliusRpcError(
                        "getSignaturesForAddress: malformed entry, missing "
                        f"'signature'/'slot': {entry!r}",
                        usage_status="contract_error",
                    )
                if not isinstance(entry["signature"], str) or not _is_strict_int(entry["slot"]):
                    raise HeliusRpcError(
                        f"getSignaturesForAddress: 'signature'/'slot' have wrong type: {entry!r}",
                        usage_status="contract_error",
                    )
                block_time_raw = entry.get("blockTime")
                if block_time_raw is not None and not _is_strict_int(block_time_raw):
                    raise HeliusRpcError(
                        f"getSignaturesForAddress: non-integer blockTime: {entry!r}",
                        usage_status="contract_error",
                    )
                err = entry.get("err")
                if not _is_valid_tx_err(err):
                    raise HeliusRpcError(
                        f"getSignaturesForAddress: 'err' has an invalid type: {entry!r}",
                        usage_status="contract_error",
                    )
                entries.append(
                    SignatureInfo(
                        signature=entry["signature"],
                        slot=entry["slot"],
                        block_time=(
                            datetime.fromtimestamp(block_time_raw, tz=UTC)
                            if block_time_raw is not None
                            else None
                        ),
                        err=err,
                    )
                )
            return entries

        return await self._rpc(
            "getSignaturesForAddress", [wallet_address, options], validate=_validate
        )

    async def get_signature_statuses(self, signatures: list[str]) -> list[SignatureStatusInfo]:
        def _validate(result: Any) -> list[SignatureStatusInfo]:
            if not isinstance(result, dict) or "value" not in result:
                raise HeliusRpcError(
                    f"getSignatureStatuses: malformed response, missing 'value': {result!r}",
                    usage_status="contract_error",
                )
            values = result["value"]
            if not isinstance(values, list) or len(values) != len(signatures):
                raise HeliusRpcError(
                    f"getSignatureStatuses: expected {len(signatures)} status entries, "
                    f"got {values!r}",
                    usage_status="contract_error",
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
                    raise HeliusRpcError(
                        f"getSignatureStatuses: malformed status entry: {entry!r}",
                        usage_status="contract_error",
                    )
                confirmation_status = entry.get("confirmationStatus")
                if confirmation_status is not None and confirmation_status not in (
                    "processed",
                    "confirmed",
                    "finalized",
                ):
                    raise HeliusRpcError(
                        f"getSignatureStatuses: unknown confirmationStatus {confirmation_status!r}",
                        usage_status="contract_error",
                    )
                slot = entry.get("slot")
                if slot is not None and not _is_strict_nonneg_int(slot):
                    raise HeliusRpcError(
                        f"getSignatureStatuses: 'slot' is not null or a strict nonnegative "
                        f"integer: {entry!r}",
                        usage_status="contract_error",
                    )
                err = entry.get("err")
                if not _is_valid_tx_err(err):
                    raise HeliusRpcError(
                        f"getSignatureStatuses: 'err' has an invalid type: {entry!r}",
                        usage_status="contract_error",
                    )
                statuses.append(
                    SignatureStatusInfo(
                        signature=signature,
                        confirmation_status=confirmation_status,
                        err=err,
                        slot=slot,
                    )
                )
            return statuses

        return await self._rpc(
            "getSignatureStatuses",
            [signatures, {"searchTransactionHistory": True}],
            validate=_validate,
        )

    async def get_balance(self, wallet_address: str) -> int:
        def _validate(result: Any) -> int:
            if (
                not isinstance(result, dict)
                or "value" not in result
                or not _is_strict_nonneg_int(result["value"])
            ):
                raise HeliusRpcError(
                    "getBalance: malformed response, expected {'value': strict nonnegative "
                    f"int}}: {result!r}",
                    usage_status="contract_error",
                )
            value: int = result["value"]
            return value

        return await self._rpc("getBalance", [wallet_address], validate=_validate)

    async def get_token_accounts(self, wallet_address: str) -> list[TokenAccountInfo]:
        def _validate_entry(entry: Any) -> TokenAccountInfo:
            if not isinstance(entry, dict) or not isinstance(entry.get("pubkey"), str):
                raise HeliusRpcError(
                    f"getTokenAccountsByOwner: malformed entry, missing 'pubkey': {entry!r}",
                    usage_status="contract_error",
                )
            account = entry.get("account")
            if not isinstance(account, dict):
                raise HeliusRpcError(
                    f"getTokenAccountsByOwner: 'account' is not an object: {entry!r}",
                    usage_status="contract_error",
                )
            data = account.get("data")
            parsed = data.get("parsed") if isinstance(data, dict) else None
            info = parsed.get("info") if isinstance(parsed, dict) else None
            if not isinstance(info, dict):
                raise HeliusRpcError(
                    f"getTokenAccountsByOwner: missing 'account.data.parsed.info': {entry!r}",
                    usage_status="contract_error",
                )
            mint = info.get("mint")
            owner = info.get("owner")
            token_amount = info.get("tokenAmount")
            if (
                not isinstance(mint, str)
                or not isinstance(owner, str)
                or not isinstance(token_amount, dict)
            ):
                raise HeliusRpcError(
                    f"getTokenAccountsByOwner: missing 'mint'/'owner'/'tokenAmount': {entry!r}",
                    usage_status="contract_error",
                )
            # Phase 1 remediation round 5, finding #5: an entry whose own
            # reported owner does not match the wallet this call was made
            # *for* is never silently trusted -- this endpoint's whole
            # contract is "token accounts owned by wallet_address", so a
            # mismatch is a genuine, fail-closed contract violation, not
            # a value to pass through and let a caller misattribute.
            if owner != wallet_address:
                raise HeliusRpcError(
                    f"getTokenAccountsByOwner: entry's 'owner' ({owner!r}) does not match the "
                    f"requested wallet_address ({wallet_address!r}): {entry!r}",
                    usage_status="contract_error",
                )
            amount_str = token_amount.get("amount")
            decimals = token_amount.get("decimals")
            if not isinstance(amount_str, str) or not amount_str.isdigit():
                raise HeliusRpcError(
                    f"getTokenAccountsByOwner: 'tokenAmount.amount' is not a nonnegative "
                    f"decimal string: {entry!r}",
                    usage_status="contract_error",
                )
            if not _is_strict_nonneg_int(decimals) or decimals > _MAX_TOKEN_DECIMALS:
                raise HeliusRpcError(
                    "getTokenAccountsByOwner: 'tokenAmount.decimals' is not a nonnegative "
                    f"integer within bounds (0-{_MAX_TOKEN_DECIMALS}): {entry!r}",
                    usage_status="contract_error",
                )
            return TokenAccountInfo(
                pubkey=entry["pubkey"],
                mint=mint,
                owner=owner,
                amount_raw=int(amount_str),
                decimals=decimals,
                # An immutable snapshot, never the same live dict a
                # caller elsewhere could still hold a mutable reference
                # to -- TokenAccountInfo's whole point is to be a
                # canonical, immutable typed model (finding #5).
                raw=MappingProxyType(entry),
            )

        def _validate(result: Any) -> list[TokenAccountInfo]:
            if (
                not isinstance(result, dict)
                or "value" not in result
                or not isinstance(result["value"], list)
            ):
                raise HeliusRpcError(
                    "getTokenAccountsByOwner: malformed response, expected "
                    f"{{'value': list}}: {result!r}",
                    usage_status="contract_error",
                )
            return [_validate_entry(entry) for entry in result["value"]]

        return await self._rpc(
            "getTokenAccountsByOwner",
            [wallet_address, {"programId": TOKEN_PROGRAM_ID}, {"encoding": "jsonParsed"}],
            validate=_validate,
        )

    async def get_slot(self) -> int:
        def _validate(result: Any) -> int:
            if not _is_strict_nonneg_int(result):
                raise HeliusRpcError(
                    f"getSlot: expected a strict nonnegative integer, got {result!r}",
                    usage_status="contract_error",
                )
            return result

        return await self._rpc("getSlot", [], validate=_validate)


class WebSocketConnection(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...
    async def ping(self) -> Any:
        """Sends a transport-level ping frame and returns an awaitable
        ("pong waiter") that resolves once the matching pong is received
        -- matching the real ``websockets`` library's own ``ping()``
        contract exactly (Phase 1 remediation round 5, finding #6)."""
        ...


class WebSocketConnector(Protocol):
    """Abstracts the underlying WebSocket library so tests never open a
    real socket. ``connect`` returns an async context manager yielding a
    :class:`WebSocketConnection`."""

    def connect(self, url: str) -> Any: ...


class HeliusSubscription:
    """Implements :class:`argus.providers.StreamSubscription`. Constructed
    only by :meth:`HeliusWebSocketStream.open_subscription` once connect +
    subscribe + a valid matching acknowledgement have all genuinely
    happened (Phase 1 remediation round 2, finding #1) -- never before.
    """

    def __init__(
        self,
        *,
        connection: WebSocketConnection,
        connector_cm: Any,
        subscription_id: int,
        wallet_address: str,
        buffered_messages: list[Any] | None = None,
        close_timeout_seconds: float = _DEFAULT_CLOSE_TIMEOUT_SECONDS,
    ) -> None:
        self._connection = connection
        self._connector_cm = connector_cm
        self._subscription_id = subscription_id
        self._wallet_address = wallet_address
        # Phase 1 remediation round 5, finding #6: any message that
        # arrived while HeliusWebSocketStream was still waiting for this
        # subscription's own acknowledgement -- including a genuine
        # logsNotification the server happened to deliver before the ack
        # -- is preserved here, already parsed, so it is replayed in
        # order rather than lost. `notifications()` drains this before
        # ever calling `recv()` again.
        self._buffered: collections.deque[Any] = collections.deque(buffered_messages or [])
        self._close_timeout_seconds = close_timeout_seconds

    def _parse_notification(self, message: Any) -> StreamNotification | None:
        """Validates and converts one already-parsed WebSocket message.
        Returns ``None`` for a benign response to a different request id
        (not this subscription's notification, but not an error either);
        raises on any other unexpected shape. Shared by both the buffered
        and the live-``recv()`` path in :meth:`notifications` so a
        message is validated/parsed exactly once, however it arrived
        (never re-parsed if it came from the buffer)."""
        if not isinstance(message, dict):
            raise HeliusRpcError(f"unexpected WebSocket message shape: {message!r}")
        if message.get("method") != "logsNotification":
            # A message that isn't this subscription's notification
            # (e.g. an unrelated ack) is not "no new activity" -- it
            # must not be silently swallowed as if it were.
            if "params" not in message and "id" in message:
                return None  # a benign response to a different request id
            raise HeliusRpcError(f"unexpected WebSocket message shape: {message!r}")
        params = message.get("params")
        if not isinstance(params, dict) or params.get("subscription") != self._subscription_id:
            raise HeliusRpcError(f"logsNotification for the wrong subscription id: {message!r}")
        result = params.get("result")
        if not isinstance(result, dict):
            raise HeliusRpcError(f"logsNotification missing 'result': {message!r}")
        context = result.get("context")
        value = result.get("value")
        if not isinstance(context, dict) or not _is_strict_int(context.get("slot")):
            raise HeliusRpcError(f"logsNotification missing context.slot: {message!r}")
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("signature"), str)
            or "err" not in value
        ):
            raise HeliusRpcError(f"logsNotification missing value.signature/value.err: {message!r}")
        return StreamNotification(
            wallet_address=self._wallet_address,
            signature=value["signature"],
            slot=context["slot"],
        )

    async def notifications(self) -> AsyncIterator[StreamNotification]:
        # `notifications` never treats a dropped connection as "no new
        # activity": any read failure raises out of this async generator
        # so the caller (the stream manager) can detect the disconnect
        # and trigger truth-path reconciliation, per MASTER_SPEC.md
        # section 19.
        while True:
            if self._buffered:
                message = self._buffered.popleft()
            else:
                raw = await self._connection.recv()
                message = json.loads(raw)
            notification = self._parse_notification(message)
            if notification is not None:
                yield notification

    async def check_liveness(self, *, timeout_seconds: float) -> bool:
        # Phase 1 remediation round 5, finding #6: a transport-level
        # ping/pong round trip, entirely separate from waiting for a
        # notification -- see StreamSubscription.check_liveness's
        # docstring for why this exists. Never raises except on genuine
        # cancellation (a BaseException, not caught by `except
        # Exception` below).
        async def _ping_pong() -> None:
            pong_waiter = await self._connection.ping()
            await pong_waiter

        try:
            await asyncio.wait_for(_ping_pong(), timeout=timeout_seconds)
            return True
        except Exception:
            return False

    async def close(self) -> None:
        # Already a best-effort cleanup call -- a close() that itself
        # hangs must not block the caller forever (Phase 1 remediation
        # round 5, finding #6). Nothing further to do on a timeout: the
        # caller has already decided to stop using this subscription
        # either way.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                self._connector_cm.__aexit__(None, None, None),
                timeout=self._close_timeout_seconds,
            )


class HeliusWebSocketStream:
    """Implements :class:`argus.providers.LiveChainStream` against
    Helius's standard WebSocket ``logsSubscribe`` endpoint.
    """

    def __init__(
        self,
        api_key: str,
        *,
        connector: WebSocketConnector,
        base_url: str = DEFAULT_WS_BASE_URL,
        connect_timeout_seconds: float = _DEFAULT_CONNECT_TIMEOUT_SECONDS,
        send_timeout_seconds: float = _DEFAULT_SEND_TIMEOUT_SECONDS,
        ack_timeout_seconds: float = _DEFAULT_ACK_TIMEOUT_SECONDS,
        close_timeout_seconds: float = _DEFAULT_CLOSE_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._connector = connector
        self._base_url = base_url
        self._connect_timeout_seconds = connect_timeout_seconds
        self._send_timeout_seconds = send_timeout_seconds
        self._ack_timeout_seconds = ack_timeout_seconds
        self._close_timeout_seconds = close_timeout_seconds

    async def _read_matching_ack(
        self, connection: WebSocketConnection, request_id: int
    ) -> tuple[dict[str, Any], list[Any]]:
        # Phase 1 remediation round 4, finding #4: a WebSocket connection
        # can carry messages for *other* pending requests, or stray
        # notifications, interleaved with this subscribe request's own
        # acknowledgement. The previous implementation treated the very
        # next message received as the ack unconditionally -- a
        # mismatched-id message (an ack for someone else's request, or a
        # notification) could be misread as this subscription becoming
        # ready. This loop skips anything that isn't a JSON object whose
        # 'id' matches our own request (round 5, finding #6: matched with
        # an exact type+value check, never plain ``==``, so a message
        # carrying JSON ``"id": true`` can never be misread as matching
        # id ``1``), and the whole loop (not each individual recv) is
        # bounded by one ack timeout so an endless stream of unrelated
        # messages can't stall a caller forever.
        #
        # Round 5, finding #6: every non-matching message encountered
        # while waiting -- including a genuine logsNotification the
        # server happens to deliver before this request's own ack -- is
        # buffered (already parsed, in order) and returned alongside the
        # ack, rather than silently discarded. The caller hands this to
        # HeliusSubscription so nothing is lost.
        buffered: list[Any] = []

        async def _loop() -> dict[str, Any]:
            while True:
                raw = await connection.recv()
                message = json.loads(raw)
                if isinstance(message, dict) and _is_matching_request_id(
                    message.get("id"), request_id
                ):
                    return message
                buffered.append(message)

        try:
            ack = await asyncio.wait_for(_loop(), timeout=self._ack_timeout_seconds)
        except TimeoutError as exc:
            raise HeliusRpcError(
                f"logsSubscribe: no matching acknowledgement (id={request_id}) within "
                f"{self._ack_timeout_seconds}s"
            ) from exc
        return ack, buffered

    async def open_subscription(self, wallet_address: str) -> HeliusSubscription:
        url = f"{self._base_url}?api-key={self._api_key}"
        connector_cm = self._connector.connect(url)
        try:
            connection = await asyncio.wait_for(
                connector_cm.__aenter__(), timeout=self._connect_timeout_seconds
            )
        except TimeoutError as exc:
            # __aenter__ never completed -- there is no entered context to
            # exit, so there is nothing to clean up beyond re-raising.
            raise HeliusRpcError(
                f"connect timed out after {self._connect_timeout_seconds}s for {wallet_address!r}"
            ) from exc

        request_id = 1
        try:
            subscribe_request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "logsSubscribe",
                "params": [{"mentions": [wallet_address]}, {"commitment": "confirmed"}],
            }
            try:
                await asyncio.wait_for(
                    connection.send(json.dumps(subscribe_request)),
                    timeout=self._send_timeout_seconds,
                )
            except TimeoutError as exc:
                raise HeliusRpcError(
                    f"logsSubscribe send timed out after {self._send_timeout_seconds}s "
                    f"for {wallet_address!r}"
                ) from exc

            ack, buffered = await self._read_matching_ack(connection, request_id)
            # Phase 1 remediation round 5, finding #6: every field of a
            # valid acknowledgement is now checked explicitly and
            # exhaustively -- exact jsonrpc version, result/error
            # mutual exclusivity (both a truthy "error" AND a valid
            # "result" would previously both need checking separately;
            # "error" present is always rejected regardless of "result"),
            # and the subscription id itself must be a strict
            # nonnegative integer (never a bool, string, float, or null).
            if (
                ack.get("jsonrpc") != "2.0"
                or "error" in ack
                or not _is_strict_nonneg_int(ack.get("result"))
            ):
                raise HeliusRpcError(f"logsSubscribe failed for {wallet_address!r}: {ack}")
            subscription_id = ack["result"]
        except BaseException:
            # Connect succeeded but subscribe/ack failed (send timeout,
            # ack timeout, a malformed/error ack, or cancellation) --
            # never leave a partially opened connection dangling; the
            # caller gets a clean exception, not a leaked socket. Bounded
            # (round 5, finding #6): a close() that itself hangs must not
            # turn a bounded failure into an unbounded one.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    connector_cm.__aexit__(*sys.exc_info()), timeout=self._close_timeout_seconds
                )
            raise
        return HeliusSubscription(
            connection=connection,
            connector_cm=connector_cm,
            subscription_id=subscription_id,
            wallet_address=wallet_address,
            buffered_messages=buffered,
            close_timeout_seconds=self._close_timeout_seconds,
        )

    async def unsubscribe_wallet(self, wallet_address: str) -> None:
        # This minimal Phase 1 stream keeps one subscription per
        # open_subscription() call/connection; callers call
        # HeliusSubscription.close() (or cancel the task) to unsubscribe,
        # which closes the connection. Explicit per-subscription-id
        # unsubscribe (multiple wallets sharing one connection) is left to
        # a later phase's stream manager.
        return
