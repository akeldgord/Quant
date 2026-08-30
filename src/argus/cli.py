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


if __name__ == "__main__":
    app()
