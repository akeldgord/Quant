"""ARGUS primary CLI entrypoint (Typer). Every important pipeline gets a
subcommand here per MASTER_SPEC.md TECH-007. Phase 0 wires up ``health`` and
``checkpoint bundle`` only; later phases add ``providers``, ``report``,
``storage``, etc.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

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
ingest_app = typer.Typer(add_completion=False, help="Live chain data ingestion (Phase 1)")
app.add_typer(ingest_app, name="ingest")
fixtures_app = typer.Typer(add_completion=False, help="Golden fixture import/validation")
app.add_typer(fixtures_app, name="fixtures")

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


@ingest_app.command("run")
def ingest_run(
    wallet: list[str] | None = typer.Option(  # noqa: B008 - required Typer CLI-option idiom
        None, "--wallet", help="Tracked wallet address (repeatable). Required unless --test-mode."
    ),
    test_mode: bool = typer.Option(
        False,
        "--test-mode",
        help="Run entirely against in-memory fakes (NullLiveStream/NullChainProvider) -- "
        "never opens a real network connection, never touches a real database, and cannot "
        "broadcast a transaction. Smoke-tests this command's own wiring and the ingestion "
        "manager's orchestration loop offline (Phase 1 remediation finding #1's required "
        "offline deterministic smoke test). Never claims to validate real provider behavior.",
    ),
    duration_seconds: float = typer.Option(
        5.0, "--duration-seconds", help="How long to run before exiting cleanly (--test-mode only)."
    ),
) -> None:
    """Runs the Phase 1 ingestion manager: opens a live Helius WebSocket
    subscription per tracked wallet, records fast-path notifications,
    triggers truth-path reconciliation on every disconnect/reconnect/
    timeout/malformed-message/clock-anomaly condition plus a periodic
    cadence, and persists commitment progression and parsed swap output.

    No signing, execution, or broadcast path exists anywhere in this
    command or anything it calls (MASTER_SPEC.md section 108 / absolute
    prohibitions)."""
    from argus.clock import Clock
    from argus.config import GitIdentityUnavailableError
    from argus.ingestion.manager import (
        IngestionManager,
        IngestionManagerConfig,
        IngestionManagerFailure,
        StaticWalletSource,
    )
    from argus.ingestion.parse_ledger import capture_parse_identity
    from argus.ingestion.reconciliation import ReconciliationEngine
    from argus.parsing.generic_parser import PARSER_VERSION

    async def _run_test_mode() -> int:
        from argus.ingestion.test_mode import (
            InMemoryReconciliationUnitOfWork,
            NullChainProvider,
            NullLiveStream,
        )

        wallets = tuple(wallet or ()) or ("TestModeWallet1111111111111111111111111111",)
        provider = NullChainProvider()
        # Finding #5: even --test-mode's offline deterministic run stamps
        # a real, non-empty build/config/spec identity onto every parse
        # attempt it records -- this exercises the real production wiring
        # end-to-end, so it must never fall back to a placeholder. Git
        # identity is the one exception (round 4, finding #7):
        # --test-mode is explicitly non-production, so it passes
        # allow_unverified_git=True rather than failing closed on a dirty
        # sandbox checkout, matching production's own honest fallback
        # sentinel rather than aborting a deliberately offline smoke test.
        engine = ReconciliationEngine(
            chain_provider=provider,
            unit_of_work=InMemoryReconciliationUnitOfWork(),
            clock=Clock(),
            provider_name="test-mode",
            parser_version=PARSER_VERSION,
            parse_identity=capture_parse_identity(load_config(), allow_unverified_git=True),
        )
        manager = IngestionManager(
            wallet_source=StaticWalletSource(wallets),
            stream=NullLiveStream(),
            chain_provider=provider,
            reconciliation_engine=engine,
            provider_name="test-mode",
            clock=Clock(),
            config=IngestionManagerConfig(
                periodic_reconciliation_interval_seconds=3600, clock_heartbeat_interval_seconds=3600
            ),
        )
        stop_event = asyncio.Event()
        run_task = asyncio.ensure_future(manager.run(stop_event=stop_event))
        await asyncio.sleep(duration_seconds)
        stop_event.set()
        await run_task
        console.print(
            f"test-mode: ran cleanly for {duration_seconds}s across {len(wallets)} wallet(s) "
            "-- no crash, no network, no signing/execution/broadcast path exists"
        )
        return 0

    async def _run_live() -> int:
        import contextlib
        import signal

        import httpx
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from argus.db.connection import connection_for_role
        from argus.db.roles import DbRole
        from argus.ingestion.unit_of_work import SqlReconciliationUnitOfWork
        from argus.providers.credentials import MissingProviderCredentialError
        from argus.providers.helius.client import (
            HeliusRpcClient,
            HeliusWebSocketStream,
            resolve_helius_api_key,
        )
        from argus.providers.helius.websocket_connector import WebSocketsConnector
        from argus.providers.retry import retry_policy_from_config
        from argus.providers.usage import SqlUsageRecorder

        if not wallet:
            console.print("error: --wallet is required at least once (or use --test-mode)")
            return 1

        config = load_config()
        try:
            api_key = resolve_helius_api_key(config.env)
        except MissingProviderCredentialError as exc:
            console.print(str(exc))
            return 1

        # Finding #7: a validated, exact git identity is required before
        # any real ingestion work begins -- fails closed here (dirty
        # checkout, no git checkout with no build-time override, or an
        # invalid override), never silently falling back to a placeholder.
        try:
            identity = capture_parse_identity(config)
        except GitIdentityUnavailableError as exc:
            console.print(f"error: {exc}")
            return 1

        db_info = connection_for_role(config, DbRole.INGEST)
        db_engine = create_async_engine(db_info.as_asyncpg_url())
        # A session factory, not one shared session (finding #2): every
        # atomic operation -- one wallet's one reconciliation item, one
        # usage write -- opens, commits, and closes its own session, so
        # no AsyncSession is ever touched by more than one concurrent
        # task.
        sessionmaker = async_sessionmaker(db_engine, expire_on_commit=False)
        retry_policy = retry_policy_from_config(config)

        async with httpx.AsyncClient(timeout=30.0) as http_client:
            usage_recorder = SqlUsageRecorder(sessionmaker)
            rpc_client = HeliusRpcClient(
                api_key,
                http_client=http_client,
                retry_policy=retry_policy,
                usage_recorder=usage_recorder,
            )
            ws_stream = HeliusWebSocketStream(api_key, connector=WebSocketsConnector())
            reconciliation_engine = ReconciliationEngine(
                chain_provider=rpc_client,
                unit_of_work=SqlReconciliationUnitOfWork(sessionmaker),
                clock=Clock(),
                provider_name="helius",
                parser_version=PARSER_VERSION,
                parse_identity=identity,
            )
            manager = IngestionManager(
                wallet_source=StaticWalletSource(tuple(wallet or ())),
                stream=ws_stream,
                chain_provider=rpc_client,
                reconciliation_engine=reconciliation_engine,
                provider_name="helius",
                clock=Clock(),
                streaming_usage_recorder=usage_recorder,
            )
            stop_event = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                with contextlib.suppress(NotImplementedError):
                    loop.add_signal_handler(sig, stop_event.set)
            try:
                await manager.run(stop_event=stop_event)
            except IngestionManagerFailure as exc:
                # Finding #3: a supervised background task died
                # unexpectedly -- this is a real process failure, not a
                # clean operator-requested shutdown, and must exit
                # non-zero rather than silently returning 0.
                console.print(f"ingestion manager failed: {exc}")
                await db_engine.dispose()
                return 1
        await db_engine.dispose()
        return 0

    raise typer.Exit(code=asyncio.run(_run_test_mode() if test_mode else _run_live()))


@ingest_app.command("reparse")
def ingest_reparse(
    limit: int = typer.Option(
        500, "--limit", help="Maximum number of events to (re)attempt in this run."
    ),
) -> None:
    """Deterministic reparse sweep (Phase 1 remediation round 2, finding
    #9; round 4, finding #6 removed the ability to target an arbitrary
    historical ``--parser-version`` string). This process only ever has
    one real parser artifact loaded -- its currently running
    ``PARSER_VERSION`` + ``PARSER_BUILD_HASH`` -- and there is no
    artifact registry that can load and execute a *different*, historical
    parser build from a string label. Claiming to "reparse under version
    X" while actually running the current code would be false: it could
    also select the same already-failing events forever if X never
    matches what actually ran. This command is current-artifact-only: it
    finds every ``chain_events`` row lacking a non-failure
    ``parse_attempts`` row under the current artifact -- never-yet-
    attempted events and events whose only attempts under this exact
    artifact were failures -- and re-runs the current parser against
    their already-immutable raw evidence. Never rewrites a prior attempt
    or the raw payload: every run only appends new
    ``parse_attempts``/``swaps`` rows. A bounded sweep makes deterministic
    forward progress and converges to zero pending once every event has a
    non-failure attempt under the current artifact -- repeating the
    command is always safe. Requires a database; performs no network I/O
    and no signing/execution/broadcast (MASTER_SPEC.md section 108)."""
    import uuid

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from argus.db.connection import connection_for_role
    from argus.db.roles import DbRole
    from argus.domain.chain_events import ChainEvent
    from argus.ingestion.parse_attempt_repository import SqlParseAttemptRecorder
    from argus.ingestion.parse_ledger import (
        ParseAttemptDraft,
        capture_parse_identity,
        outcome_for,
        payload_hash,
    )
    from argus.ingestion.swap_repository import SqlSwapRecorder
    from argus.parsing.generic_parser import PARSER_VERSION, parse_transaction

    async def _run() -> int:
        config = load_config()
        # Finding #5: identity is captured once per reparse run, at the
        # current code/config/git state -- never inherited from whatever
        # identity produced the original (now-immutable) failing attempt
        # this sweep is retrying. Finding #7 (round 4): reparse is a
        # production path, so the git identity fails closed here too --
        # never falls back to a placeholder on a dirty/unverifiable
        # checkout.
        from argus.config import GitIdentityUnavailableError

        try:
            identity = capture_parse_identity(config)
        except GitIdentityUnavailableError as identity_exc:
            console.print(f"error: {identity_exc}")
            return 1
        db_info = connection_for_role(config, DbRole.INGEST)
        db_engine = create_async_engine(db_info.as_asyncpg_url())
        sessionmaker = async_sessionmaker(db_engine, expire_on_commit=False)
        now = Clock().utc_now()

        async with sessionmaker() as session:
            ledger = SqlParseAttemptRecorder(session)
            pending = await ledger.events_pending_for_artifact(
                PARSER_VERSION, identity.build_hash, limit=limit
            )

        attempted = 0
        succeeded = 0
        still_failing = 0
        for event_id in pending:
            async with sessionmaker() as session, session.begin():
                row = await session.get(ChainEvent, event_id)
                if row is None:
                    continue  # pragma: no cover - event deleted between the sweep and here
                attempted += 1
                exc: BaseException | None = None
                classification: str | None = None
                try:
                    parsed = parse_transaction(
                        row.raw_payload,
                        wallet_address=row.wallet_address or "",
                        slot=row.slot,
                        block_time=row.block_time,
                    )
                    classification = parsed.classification
                    await SqlSwapRecorder(session).record(
                        event_id=row.event_id,
                        wallet_address=row.wallet_address or "",
                        parsed=parsed,
                        build_hash=identity.build_hash,
                        created_at=now,
                    )
                except Exception as caught:  # noqa: BLE001 - recorded, never fatal to the sweep
                    exc = caught

                outcome, retry_disposition = outcome_for(classification=classification, exc=exc)
                await SqlParseAttemptRecorder(session).record(
                    ParseAttemptDraft(
                        attempt_id=uuid.uuid4(),
                        event_id=row.event_id,
                        parser_version=PARSER_VERSION,
                        attempted_at=now,
                        outcome=outcome,
                        error_class=type(exc).__name__ if exc is not None else None,
                        error_reason=str(exc)[:512] if exc is not None else None,
                        input_payload_hash=payload_hash(row.raw_payload),
                        retry_disposition=retry_disposition,
                        build_hash=identity.build_hash,
                        config_hash=identity.config_hash,
                        master_spec_hash=identity.master_spec_hash,
                        git_commit=identity.git_commit,
                        created_at=now,
                    )
                )
                if exc is None:
                    succeeded += 1
                else:
                    still_failing += 1

        await db_engine.dispose()
        console.print(
            f"reparse @ {PARSER_VERSION} ({identity.build_hash[:12]}): {attempted} attempted, "
            f"{succeeded} succeeded/unknown, {still_failing} still failing "
            f"(of {len(pending)} pending, limit {limit})"
        )
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@fixtures_app.command("import-real-chain")
def fixtures_import_real_chain(
    input_path: str = typer.Option(
        ..., "--input", help="Path to a captured getTransaction JSON payload, exactly as captured."
    ),
    evidence_path: str = typer.Option(
        ...,
        "--evidence-file",
        help="Path to a JSON file bundling the upstream git tree attestation, license "
        "evidence, and the full independent expectation (Phase 1 remediation round 5, "
        "findings #1/#2) -- too rich for individual flags. See "
        "tests/golden/fixtures/real/EVIDENCE_FILE_SCHEMA.md for the exact shape.",
    ),
    license_bytes_path: str = typer.Option(
        ...,
        "--license-file",
        help="Path to the exact preserved upstream license file bytes, matching the "
        "evidence file's upstream_license.bytes_sha256.",
    ),
    fixtures_dir: str = typer.Option(
        "",
        "--fixtures-dir",
        help="Override the fixtures directory (default: tests/golden/fixtures/real). "
        "Mainly for testing this command itself.",
    ),
) -> None:
    """Offline import for one real-chain golden fixture (Phase 1
    remediation round 2, finding #12; round 4, findings #2/#3; round 5,
    findings #1/#2): validates INPUT is a genuine, unmodified raw
    upstream capture, canonicalizes it, preserves the raw bytes and the
    license bytes, runs it through the real parser, and records full
    provenance -- an independently-reviewed typed expectation checked
    against (never defined by) the parser's own observed output, and a
    cryptographically-bound evidence chain covering the upstream git
    tree/license attestations. Makes no network call of its own -- INPUT
    and the evidence file's attestations must already reflect evidence
    captured elsewhere with real network access (this sandbox has GitHub
    read access but no general RPC egress)."""
    from argus.golden_fixtures import (
        DEFAULT_REAL_FIXTURES_DIR,
        RealChainFixtureError,
        import_real_chain_fixture_from_evidence_file,
    )

    try:
        record = import_real_chain_fixture_from_evidence_file(
            input_path=Path(input_path),
            evidence_path=Path(evidence_path),
            license_bytes_path=Path(license_bytes_path),
            fixtures_dir=Path(fixtures_dir) if fixtures_dir else DEFAULT_REAL_FIXTURES_DIR,
        )
    except RealChainFixtureError as exc:
        console.print(f"[red]rejected:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"imported {record.category!r}: signature={record.signature} slot={record.slot} "
        f"expected={record.expectation.classification} ({record.expectation.expected_confidence}) "
        f"observed={record.observed_classification} ({record.observed_confidence}) "
        f"quarantined={record.quarantined} "
        f"sanitized_sha256={record.sanitized_sha256}"
    )


@fixtures_app.command("validate-real-chain")
def fixtures_validate_real_chain(
    fixtures_dir: str = typer.Option(
        "",
        "--fixtures-dir",
        help="Override the fixtures directory (default: tests/golden/fixtures/real). "
        "Mainly for testing this command itself.",
    ),
) -> None:
    """Re-verifies every currently-imported real-chain fixture: bytes
    still hash to their recorded value, and the parser's current output
    still matches the recorded expectation (finding #12). Zero imported
    fixtures is reported honestly, not silently treated as a pass."""
    from argus.golden_fixtures import DEFAULT_REAL_FIXTURES_DIR, validate_real_chain_fixtures

    results = validate_real_chain_fixtures(
        Path(fixtures_dir) if fixtures_dir else DEFAULT_REAL_FIXTURES_DIR
    )
    if not results:
        console.print(
            "no real-chain fixtures imported yet -- see tests/golden/fixtures/real/PROVENANCE.md"
        )
        return
    failed = [r for r in results if not r.ok]
    for result in results:
        if result.ok:
            marker = "[green]ok[/green]"
        elif result.quarantined:
            marker = "[yellow]QUARANTINED[/yellow]"
        else:
            marker = "[red]FAIL[/red]"
        console.print(f"{result.category}: {marker} - {result.detail}")
    if failed:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
