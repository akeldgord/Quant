"""``argus health`` — system health report (MASTER_SPEC.md section 95).

Phase 0 only has a database and config/clock/spec state to report on; the
provider, stream, and reconciliation rows described in section 95 are added
as those subsystems are built in later phases. The live-readiness flags are
always reported and always false until their respective phases/gates are
actually satisfied (sections 82, 110) — Phase 0 hardcodes them false rather
than omitting them, so the shape of `argus health` output does not change
later and nothing ever silently defaults to "ready".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from argus.clock import Clock
from argus.config import ArgusConfig


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class HealthReport:
    checks: list[CheckResult] = field(default_factory=list)
    config_hash: str = ""
    master_spec_hash: str = ""
    live_ready_software: bool = False
    live_canary_passed: bool = False
    live_armed: bool = False

    @property
    def all_ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def as_lines(self) -> list[str]:
        lines = [
            f"{c.name}: {'OK' if c.ok else 'FAIL'}" + (f" ({c.detail})" if c.detail else "")
            for c in self.checks
        ]
        lines.append(f"config_hash: {self.config_hash}")
        lines.append(f"master_spec_hash: {self.master_spec_hash}")
        lines.append(f"LIVE_READY_SOFTWARE: {str(self.live_ready_software).lower()}")
        lines.append(f"LIVE_CANARY_PASSED: {str(self.live_canary_passed).lower()}")
        lines.append(f"LIVE_ARMED: {str(self.live_armed).lower()}")
        return lines


async def check_postgres(engine: AsyncEngine) -> CheckResult:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return CheckResult(name="Postgres", ok=True)
    except Exception as exc:  # pragma: no cover - exercised via integration test
        return CheckResult(name="Postgres", ok=False, detail=str(exc))


def check_clock(clock: Clock) -> CheckResult:
    first = clock.sample()
    second = clock.sample()
    result = clock.check_health(first, second)
    return CheckResult(name="Clock", ok=result.healthy, detail=result.reason or "")


async def build_health_report(
    config: ArgusConfig,
    engine: AsyncEngine | None,
    clock: Clock | None = None,
) -> HealthReport:
    report = HealthReport(
        config_hash=config.config_hash,
        master_spec_hash=config.spec_hash,
    )
    if engine is not None:
        report.checks.append(await check_postgres(engine))
    else:
        report.checks.append(CheckResult(name="Postgres", ok=False, detail="not configured"))
    report.checks.append(check_clock(clock or Clock()))
    return report
