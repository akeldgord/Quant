"""Unit tests for `argus.providers.probes`, run against `httpx.MockTransport`
(no real network) and a synthetic in-memory `ArgusConfig` -- never the real
sandbox network, which has no general egress.

These tests exist specifically to regression-guard the config dotted-path
bug found and fixed while building Phase 1: `config/providers.yaml` is
merged *flat* into `ArgusConfig.values` (top-level `helius:`, `dexscreener:`
... keys), not nested under a `providers:` namespace, so `_throttle()` must
query `f"{provider}.conservative_rate_limit_per_sec"`, not
`f"providers.{provider}.conservative_rate_limit_per_sec"`.
"""

from __future__ import annotations

import httpx
import pytest

from argus.config import ArgusConfig
from argus.providers.probes import (
    RESPONSE_CONTRACT_CREDENTIAL_REQUIRED,
    RESPONSE_CONTRACT_OK,
    RESPONSE_CONTRACT_UNREACHABLE,
    _throttle,
    probe_dexscreener,
    probe_geckoterminal,
    probe_helius,
    probe_history_geckoterminal,
    probe_jupiter,
)

FAKE_PROVIDERS_CONFIG: dict = {
    "helius": {"conservative_rate_limit_per_sec": 5},
    "dexscreener": {"conservative_rate_limit_per_sec": 2},
    "geckoterminal": {"conservative_rate_limit_per_sec": 1},
    "jupiter": {"conservative_rate_limit_per_sec": 2},
}


def _config(env: dict[str, str] | None = None) -> ArgusConfig:
    return ArgusConfig(values=FAKE_PROVIDERS_CONFIG, sources=(), env=env or {})


@pytest.mark.parametrize(
    ("provider", "expected"),
    [("helius", 5.0), ("dexscreener", 2.0), ("geckoterminal", 1.0), ("jupiter", 2.0)],
)
def test_throttle_reads_flat_top_level_provider_key_not_nested(
    provider: str, expected: float
) -> None:
    """Regression test: `config/providers.yaml` is merged flat, so
    `_throttle` must NOT look under a `providers.<name>.` prefix."""
    assert _throttle(_config(), provider) == expected


def test_throttle_nested_providers_namespace_is_not_used() -> None:
    """A config that only has the (wrong) nested shape must resolve to
    None, proving `_throttle` really reads the flat top-level key and not
    some nested `providers.*` path that doesn't exist in the real config."""
    nested_only = ArgusConfig(
        values={"providers": {"helius": {"conservative_rate_limit_per_sec": 5}}}, sources=(), env={}
    )
    assert _throttle(nested_only, "helius") is None


def test_throttle_missing_provider_returns_none() -> None:
    assert _throttle(_config(), "unknown_provider") is None


async def test_probe_helius_reports_credential_required_with_throttle_populated() -> None:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    result = await probe_helius(_config(env={}), http_client)
    assert result.response_contract_status == RESPONSE_CONTRACT_CREDENTIAL_REQUIRED
    assert result.reachable is False
    assert result.configured_throttle_per_sec == 5.0
    assert "LOCAL CREDENTIAL REQUIRED" in result.detail
    await http_client.aclose()


async def test_probe_helius_success_via_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": 123456789})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await probe_helius(_config(env={"HELIUS_API_KEY": "fake-key"}), http_client)
    assert result.reachable is True
    assert result.response_contract_status == RESPONSE_CONTRACT_OK
    assert result.configured_throttle_per_sec == 5.0
    assert result.health == "OK"
    assert "getTransaction" in result.supported_functions
    await http_client.aclose()


async def test_probe_dexscreener_unreachable_reports_throttle_and_degraded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await probe_dexscreener(_config(), http_client)
    assert result.reachable is False
    assert result.response_contract_status == RESPONSE_CONTRACT_UNREACHABLE
    assert result.configured_throttle_per_sec == 2.0
    assert result.health == "DEGRADED"
    await http_client.aclose()


async def test_probe_geckoterminal_success_via_mock_transport() -> None:
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {}}))
    )
    result = await probe_geckoterminal(_config(), http_client)
    assert result.reachable is True
    assert result.response_contract_status == RESPONSE_CONTRACT_OK
    assert result.configured_throttle_per_sec == 1.0
    await http_client.aclose()


async def test_probe_jupiter_success_via_mock_transport() -> None:
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"outAmount": "1"}))
    )
    result = await probe_jupiter(_config(), http_client)
    assert result.reachable is True
    assert result.response_contract_status == RESPONSE_CONTRACT_OK
    assert result.configured_throttle_per_sec == 2.0
    await http_client.aclose()


async def test_probe_history_geckoterminal_unreachable_never_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await probe_history_geckoterminal(_config(), http_client)
    assert result.reachable is False
    assert result.earliest_available is None
    assert result.latest_available is None
    await http_client.aclose()


async def test_probe_history_geckoterminal_reachable_reports_range() -> None:
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
    result = await probe_history_geckoterminal(_config(), http_client)
    assert result.reachable is True
    assert result.earliest_available is not None
    assert result.latest_available is not None
    assert result.earliest_available < result.latest_available
    await http_client.aclose()
