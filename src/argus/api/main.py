"""ARGUS FastAPI admin/health service (MASTER_SPEC.md TECH-006).

Phase 0 wires up only the endpoints the spec names explicitly:
``/health``, ``/ready``, ``/metrics-summary``, ``/webhooks/*``. Webhook
handlers are stubs until Phase 1+ providers exist to call them.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Response, status

from argus.clock import Clock
from argus.config import ArgusConfig, load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.db.session import RoleEngines
from argus.health import build_health_report

_state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    _state["config"] = config
    try:
        engines = RoleEngines({DbRole.RESEARCH: connection_for_role(config, DbRole.RESEARCH)})
    except Exception:
        engines = None
    _state["engines"] = engines
    _state["clock"] = Clock()
    yield
    if engines is not None:
        await engines.dispose_all()


app = FastAPI(title="ARGUS Admin API", version="0.1.0", lifespan=lifespan)
webhooks = APIRouter(prefix="/webhooks")


def _config() -> ArgusConfig:
    return _state.get("config") or load_config()


@app.get("/health")
async def health(response: Response) -> dict[str, Any]:
    config = _config()
    engines: RoleEngines | None = _state.get("engines")
    engine = engines.engine(DbRole.RESEARCH) if engines is not None else None
    report = await build_health_report(
        config=config, engine=engine, clock=_state.get("clock") or Clock()
    )
    if not report.all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in report.checks],
        "config_hash": report.config_hash,
        "master_spec_hash": report.master_spec_hash,
        "live_ready_software": report.live_ready_software,
        "live_canary_passed": report.live_canary_passed,
        "live_armed": report.live_armed,
    }


@app.get("/ready")
async def ready(response: Response) -> dict[str, Any]:
    """Narrower than /health: is this process ready to accept traffic?"""
    config = _config()
    engines: RoleEngines | None = _state.get("engines")
    engine = engines.engine(DbRole.RESEARCH) if engines is not None else None
    report = await build_health_report(
        config=config, engine=engine, clock=_state.get("clock") or Clock()
    )
    ready_ok = report.all_ok
    if not ready_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"ready": ready_ok}


@app.get("/metrics-summary")
async def metrics_summary() -> dict[str, Any]:
    """Phase 0 stub — populated as ingestion/scoring/execution metrics exist."""
    return {
        "phase": 0,
        "note": "no runtime pipelines exist yet; metrics populate from Phase 1 onward",
    }


@webhooks.post("/{provider}")
async def webhook_stub(provider: str) -> dict[str, Any]:
    """Phase 0 stub — no provider webhook integrations exist yet."""
    return {"accepted": False, "provider": provider, "reason": "not implemented until Phase 1+"}


app.include_router(webhooks)
