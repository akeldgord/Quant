"""ARGUS primary CLI entrypoint (Typer). Every important pipeline gets a
subcommand here per MASTER_SPEC.md TECH-007. Phase 0 wires up ``health`` and
``checkpoint bundle`` only; later phases add ``providers``, ``report``,
``storage``, etc.
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console

from argus.checkpoint import write_bundle
from argus.clock import Clock
from argus.config import load_config
from argus.db.connection import connection_for_role
from argus.db.roles import DbRole
from argus.db.session import RoleEngines
from argus.health import build_health_report
from argus.logging import configure_logging

app = typer.Typer(add_completion=False, no_args_is_help=True, help="ARGUS operator CLI")
checkpoint_app = typer.Typer(add_completion=False, help="Orchestrator checkpoint tooling")
app.add_typer(checkpoint_app, name="checkpoint")
providers_app = typer.Typer(
    add_completion=False, help="Provider capability/history probes and usage"
)
app.add_typer(providers_app, name="providers")

console = Console()


@app.callback()
def _main(
    log_level: str = typer.Option("INFO", "--log-level", envvar="ARGUS_LOG_LEVEL"),
    json_logs: bool = typer.Option(True, "--json-logs/--console-logs"),
) -> None:
    configure_logging(level=log_level, json_output=json_logs)


@app.command()
def health() -> None:
    """Print the ARGUS system health report (MASTER_SPEC.md section 95)."""

    async def _run() -> int:
        config = load_config()
        engines: RoleEngines | None = None
        engine = None
        try:
            engines = RoleEngines({DbRole.RESEARCH: connection_for_role(config, DbRole.RESEARCH)})
            engine = engines.engine(DbRole.RESEARCH)
        except Exception:
            engine = None
        report = await build_health_report(config=config, engine=engine, clock=Clock())
        for line in report.as_lines():
            console.print(line)
        if engines is not None:
            await engines.dispose_all()
        return 0 if report.all_ok else 1

    raise typer.Exit(code=asyncio.run(_run()))


@app.command()
def config_show() -> None:
    """Print the effective config hash and MASTER_SPEC hash (no secrets)."""
    config = load_config()
    console.print(f"config_hash: {config.config_hash}")
    console.print(f"master_spec_hash: {config.spec_hash}")
    console.print(f"sources: {[str(p) for p in config.sources]}")


@checkpoint_app.command("bundle")
def checkpoint_bundle(
    phase: int = typer.Option(..., "--phase", help="Phase number this bundle documents"),
    checkpoint_file: str | None = typer.Option(
        None,
        "--checkpoint-file",
        help="Path to a text file containing the STANDARD ORCHESTRATOR CHECKPOINT report "
        "to embed at the top of the bundle.",
    ),
) -> None:
    """Write runtime/reports/orchestrator_bundle_phase_<N>.txt (section 105)."""
    checkpoint_text = None
    if checkpoint_file:
        from pathlib import Path

        checkpoint_text = Path(checkpoint_file).read_text()
    out_path = write_bundle(phase=phase, checkpoint_text=checkpoint_text)
    console.print(f"wrote {out_path}")


@providers_app.command("probe")
def providers_probe() -> None:
    """Report reachability/supported functions/throttle/latency/health for
    each Phase 1 provider (MASTER_SPEC.md section 13). Never fabricates: a
    missing credential or unreachable network is reported honestly, not
    silently skipped or mocked."""
    import httpx

    from argus.providers.probes import (
        probe_dexscreener,
        probe_geckoterminal,
        probe_helius,
        probe_jupiter,
    )

    async def _run() -> int:
        config = load_config()
        any_unreachable = False
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            for probe in (probe_helius, probe_dexscreener, probe_geckoterminal, probe_jupiter):
                result = await probe(config, http_client)
                console.print(f"[bold]{result.provider}[/bold]")
                console.print(f"  reachable: {result.reachable}")
                console.print(f"  response_contract_status: {result.response_contract_status}")
                console.print(
                    f"  supported_functions: {', '.join(result.supported_functions) or '(none)'}"
                )
                console.print(
                    f"  configured_throttle_per_sec: {result.configured_throttle_per_sec}"
                )
                console.print(f"  latency_ms: {result.latency_ms}")
                console.print(f"  health: {result.health}")
                if result.detail:
                    console.print(f"  detail: {result.detail}")
                if not result.reachable:
                    any_unreachable = True
        return 1 if any_unreachable else 0

    raise typer.Exit(code=asyncio.run(_run()))


@providers_app.command("probe-history")
def providers_probe_history() -> None:
    """Report earliest/latest available data, partitions, estimated query
    size, and known limitations for providers with meaningful historical
    coverage (MASTER_SPEC.md section 13)."""
    import httpx

    from argus.providers.probes import probe_history_geckoterminal

    async def _run() -> int:
        config = load_config()
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            result = await probe_history_geckoterminal(config, http_client)
        console.print(f"[bold]{result.provider}[/bold]")
        console.print(f"  reachable: {result.reachable}")
        console.print(f"  earliest_available: {result.earliest_available}")
        console.print(f"  latest_available: {result.latest_available}")
        console.print(f"  partitions: {', '.join(result.partitions) or '(none)'}")
        console.print(f"  estimated_query_size: {result.estimated_query_size}")
        console.print(f"  limitations: {'; '.join(result.limitations) or '(none)'}")
        if result.detail:
            console.print(f"  detail: {result.detail}")
        return 0 if result.reachable else 1

    raise typer.Exit(code=asyncio.run(_run()))


@providers_app.command("usage")
def providers_usage(
    provider: str = typer.Option(..., "--provider", help="Provider name to report usage for"),
    monthly_allowance: float | None = typer.Option(
        None, "--monthly-allowance", help="Configured monthly credit allowance, if known"
    ),
) -> None:
    """Report today/month-to-date/30-day-projected usage against an
    optional configured allowance, with 70/85/95% warnings
    (MASTER_SPEC.md section 14). Never auto-upgrades a provider tier."""
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import create_async_engine

    from argus.providers.usage import UsageReporter

    async def _run() -> int:
        config = load_config()
        info = connection_for_role(config, DbRole.RESEARCH)
        engine = create_async_engine(info.as_asyncpg_url())
        from sqlalchemy.ext.asyncio import async_sessionmaker

        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        async with sessionmaker() as session:
            reporter = UsageReporter(session)
            allowance = Decimal(str(monthly_allowance)) if monthly_allowance is not None else None
            summary = await reporter.summarize(provider, monthly_allowance=allowance)
        await engine.dispose()

        console.print(f"[bold]{summary.provider}[/bold]")
        console.print(f"  today_credits: {summary.today_credits}")
        console.print(f"  month_to_date_credits: {summary.month_to_date_credits}")
        console.print(f"  projected_30_day_credits: {summary.projected_30_day_credits}")
        console.print(f"  monthly_allowance: {summary.monthly_allowance}")
        console.print(f"  projected_pct_of_allowance: {summary.projected_pct_of_allowance}")
        console.print(f"  warning_thresholds_triggered: {summary.warning_thresholds_triggered}")
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


if __name__ == "__main__":
    app()
