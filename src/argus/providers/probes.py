"""Provider capability + history probes (MASTER_SPEC.md section 13).

``probe()`` reports reachability, supported functions, configured
throttle, response-contract status, latency, and health -- never inferred
from marketing text, always from an actual (attempted) call. ``probe()``
never raises for an expected failure mode (missing credential, network
unreachable): it reports that honestly in the result instead, since a CLI
probe command must never crash just because a provider isn't configured
yet in this environment.
"""

from __future__ import annotations

import dataclasses
import time
from datetime import UTC, datetime
from typing import Final

import httpx

from argus.config import ArgusConfig
from argus.providers.credentials import MissingProviderCredentialError
from argus.providers.dexscreener.client import DexScreenerClient
from argus.providers.geckoterminal.client import GeckoTerminalClient
from argus.providers.helius.client import HeliusRpcClient, resolve_helius_api_key
from argus.providers.jupiter.client import JupiterClient
from argus.providers.retry import retry_policy_from_config

RESPONSE_CONTRACT_OK: Final[str] = "OK"
RESPONSE_CONTRACT_UNREACHABLE: Final[str] = "UNREACHABLE"
RESPONSE_CONTRACT_CREDENTIAL_REQUIRED: Final[str] = "CREDENTIAL_REQUIRED"
RESPONSE_CONTRACT_UNEXPECTED_SHAPE: Final[str] = "UNEXPECTED_SHAPE"

# A well-known, always-existing mint used only to exercise the
# request/response shape during a probe -- never asserted to be a
# particular wallet's holding.
WSOL_MINT: Final[str] = "So11111111111111111111111111111111111111112"


@dataclasses.dataclass(frozen=True, slots=True)
class ProbeResult:
    provider: str
    reachable: bool
    supported_functions: tuple[str, ...]
    configured_throttle_per_sec: float | None
    response_contract_status: str
    latency_ms: float | None
    health: str  # "OK" | "DEGRADED" | "UNKNOWN"
    detail: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class HistoryProbeResult:
    provider: str
    reachable: bool
    earliest_available: datetime | None
    latest_available: datetime | None
    partitions: tuple[str, ...]
    estimated_query_size: str
    limitations: tuple[str, ...]
    detail: str = ""


def _throttle(config: ArgusConfig, provider: str) -> float | None:
    # config/providers.yaml is merged flat (top-level `helius:`, `dexscreener:`,
    # ... keys), not nested under a `providers:` namespace -- see
    # argus.config.load_config / DEFAULT_CONFIG_FILES.
    value = config.get(f"{provider}.conservative_rate_limit_per_sec")
    return float(value) if value is not None else None


async def probe_helius(config: ArgusConfig, http_client: httpx.AsyncClient) -> ProbeResult:
    throttle = _throttle(config, "helius")
    try:
        api_key = resolve_helius_api_key(config.env)
    except MissingProviderCredentialError as exc:
        return ProbeResult(
            provider="helius",
            reachable=False,
            supported_functions=(),
            configured_throttle_per_sec=throttle,
            response_contract_status=RESPONSE_CONTRACT_CREDENTIAL_REQUIRED,
            latency_ms=None,
            health="UNKNOWN",
            detail=str(exc),
        )

    client = HeliusRpcClient(
        api_key, http_client=http_client, retry_policy=retry_policy_from_config(config)
    )
    start = time.monotonic()
    try:
        slot = await client.get_slot()
    except Exception as exc:  # noqa: BLE001 - probes report failure, never crash
        latency_ms = (time.monotonic() - start) * 1000
        return ProbeResult(
            provider="helius",
            reachable=False,
            supported_functions=(),
            configured_throttle_per_sec=throttle,
            response_contract_status=RESPONSE_CONTRACT_UNREACHABLE,
            latency_ms=latency_ms,
            health="DEGRADED",
            detail=f"{type(exc).__name__}: {exc}",
        )
    latency_ms = (time.monotonic() - start) * 1000
    return ProbeResult(
        provider="helius",
        reachable=True,
        supported_functions=(
            "getTransaction",
            "getSignaturesForAddress",
            "getBalance",
            "getTokenAccountsByOwner",
            "getSlot",
        ),
        configured_throttle_per_sec=throttle,
        response_contract_status=RESPONSE_CONTRACT_OK,
        latency_ms=latency_ms,
        health="OK",
        detail=f"slot={slot}",
    )


async def probe_dexscreener(config: ArgusConfig, http_client: httpx.AsyncClient) -> ProbeResult:
    throttle = _throttle(config, "dexscreener")
    client = DexScreenerClient(
        http_client=http_client, retry_policy=retry_policy_from_config(config)
    )
    start = time.monotonic()
    try:
        result = await client.token_snapshot(WSOL_MINT)
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.monotonic() - start) * 1000
        return ProbeResult(
            provider="dexscreener",
            reachable=False,
            supported_functions=(),
            configured_throttle_per_sec=throttle,
            response_contract_status=RESPONSE_CONTRACT_UNREACHABLE,
            latency_ms=latency_ms,
            health="DEGRADED",
            detail=f"{type(exc).__name__}: {exc}",
        )
    latency_ms = (time.monotonic() - start) * 1000
    contract_ok = isinstance(result, dict)
    return ProbeResult(
        provider="dexscreener",
        reachable=True,
        supported_functions=("token_snapshot",),
        configured_throttle_per_sec=throttle,
        response_contract_status=RESPONSE_CONTRACT_OK
        if contract_ok
        else RESPONSE_CONTRACT_UNEXPECTED_SHAPE,
        latency_ms=latency_ms,
        health="OK" if contract_ok else "DEGRADED",
    )


async def probe_geckoterminal(config: ArgusConfig, http_client: httpx.AsyncClient) -> ProbeResult:
    throttle = _throttle(config, "geckoterminal")
    client = GeckoTerminalClient(
        http_client=http_client, retry_policy=retry_policy_from_config(config)
    )
    start = time.monotonic()
    try:
        result = await client.token_snapshot(WSOL_MINT)
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.monotonic() - start) * 1000
        return ProbeResult(
            provider="geckoterminal",
            reachable=False,
            supported_functions=(),
            configured_throttle_per_sec=throttle,
            response_contract_status=RESPONSE_CONTRACT_UNREACHABLE,
            latency_ms=latency_ms,
            health="DEGRADED",
            detail=f"{type(exc).__name__}: {exc}",
        )
    latency_ms = (time.monotonic() - start) * 1000
    contract_ok = isinstance(result, dict)
    return ProbeResult(
        provider="geckoterminal",
        reachable=True,
        supported_functions=("token_snapshot", "historical_ohlcv"),
        configured_throttle_per_sec=throttle,
        response_contract_status=RESPONSE_CONTRACT_OK
        if contract_ok
        else RESPONSE_CONTRACT_UNEXPECTED_SHAPE,
        latency_ms=latency_ms,
        health="OK" if contract_ok else "DEGRADED",
    )


async def probe_jupiter(config: ArgusConfig, http_client: httpx.AsyncClient) -> ProbeResult:
    throttle = _throttle(config, "jupiter")
    client = JupiterClient(http_client=http_client, retry_policy=retry_policy_from_config(config))
    usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    start = time.monotonic()
    try:
        result = await client.get_quote(
            input_mint=WSOL_MINT, output_mint=usdc_mint, amount_raw=1_000_000
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.monotonic() - start) * 1000
        return ProbeResult(
            provider="jupiter",
            reachable=False,
            supported_functions=(),
            configured_throttle_per_sec=throttle,
            response_contract_status=RESPONSE_CONTRACT_UNREACHABLE,
            latency_ms=latency_ms,
            health="DEGRADED",
            detail=f"{type(exc).__name__}: {exc}",
        )
    latency_ms = (time.monotonic() - start) * 1000
    contract_ok = isinstance(result, dict)
    return ProbeResult(
        provider="jupiter",
        reachable=True,
        supported_functions=("get_quote", "build_unsigned_order"),
        configured_throttle_per_sec=throttle,
        response_contract_status=RESPONSE_CONTRACT_OK
        if contract_ok
        else RESPONSE_CONTRACT_UNEXPECTED_SHAPE,
        latency_ms=latency_ms,
        health="OK" if contract_ok else "DEGRADED",
    )


async def probe_history_geckoterminal(
    config: ArgusConfig, http_client: httpx.AsyncClient
) -> HistoryProbeResult:
    """GeckoTerminal is the only Phase 1 provider with a meaningful
    "history probe" -- Helius standard RPC has no long-range archival
    history endpoint (PROV-001), and DexScreener has no historical OHLCV
    at all (see DexScreenerClient.historical_ohlcv)."""
    client = GeckoTerminalClient(
        http_client=http_client, retry_policy=retry_policy_from_config(config)
    )
    try:
        candles = await client.historical_ohlcv(
            WSOL_MINT, start=datetime(2020, 1, 1, tzinfo=UTC), end=datetime.now(UTC)
        )
    except Exception as exc:  # noqa: BLE001
        return HistoryProbeResult(
            provider="geckoterminal",
            reachable=False,
            earliest_available=None,
            latest_available=None,
            partitions=(),
            estimated_query_size="unknown (provider unreachable)",
            limitations=("provider unreachable in this environment",),
            detail=f"{type(exc).__name__}: {exc}",
        )
    timestamps = [c["timestamp"] for c in candles]
    return HistoryProbeResult(
        provider="geckoterminal",
        reachable=True,
        earliest_available=(
            datetime.fromtimestamp(min(timestamps), tz=UTC) if timestamps else None
        ),
        latest_available=(datetime.fromtimestamp(max(timestamps), tz=UTC) if timestamps else None),
        partitions=("hourly",),
        estimated_query_size=f"{len(candles)} candles for this window",
        limitations=(
            "free-tier rate limits apply; not a substitute for high-frequency live data (PROV-003)",
        ),
    )
