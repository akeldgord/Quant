from __future__ import annotations

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from argus.api.main import app

pytestmark = pytest.mark.asyncio


async def test_health_endpoint_reports_expected_shape() -> None:
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    body = response.json()
    assert response.status_code in (200, 503)
    assert "checks" in body
    assert {c["name"] for c in body["checks"]} >= {"Postgres", "Clock"}
    assert body["live_ready_software"] is False
    assert body["live_canary_passed"] is False
    assert body["live_armed"] is False
    assert len(body["config_hash"]) == 64
    assert len(body["master_spec_hash"]) == 64


async def test_ready_endpoint() -> None:
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ready")

    assert response.status_code in (200, 503)
    assert "ready" in response.json()


async def test_metrics_summary_stub() -> None:
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics-summary")

    assert response.status_code == 200
    assert response.json()["phase"] == 0


async def test_webhook_stub_not_implemented() -> None:
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/webhooks/helius", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
