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
tokens_app = typer.Typer(
    add_completion=False, help="Token bootstrap import + mint validation (Phase 2)"
)
app.add_typer(tokens_app, name="tokens")
discover_app = typer.Typer(
    add_completion=False, help="Historical/prospective wallet discovery archaeology (Phase 2)"
)
app.add_typer(discover_app, name="discover")
wallets_app = typer.Typer(
    add_completion=False, help="Wallet reconstruction + unbiased qualification (Phase 3)"
)
app.add_typer(wallets_app, name="wallets")
prospective_app = typer.Typer(
    add_completion=False, help="Prospective tracked-wallet monitoring (Phase 4)"
)
app.add_typer(prospective_app, name="prospective")
shadow_app = typer.Typer(
    add_completion=False, help="Shadow copy quote/mark probe execution (Phase 4)"
)
app.add_typer(shadow_app, name="shadow")
report_app = typer.Typer(add_completion=False, help="Operator reports")
app.add_typer(report_app, name="report")
copyability_app = typer.Typer(
    add_completion=False, help="Copyability + forward information value research reports (Phase 5)"
)
app.add_typer(copyability_app, name="copyability")
executor_app = typer.Typer(
    add_completion=False, help="Hardened isolated executor software-readiness reporting (Phase 6)"
)
app.add_typer(executor_app, name="executor")
graph_app = typer.Typer(
    add_completion=False, help="Alpha-ancestry lead/follow graph reports (Phase 7)"
)
app.add_typer(graph_app, name="graph")
convergence_app = typer.Typer(
    add_completion=False,
    help="Convergence surprise + dog-that-didn't-bark negative evidence reports (Phase 8)",
)
app.add_typer(convergence_app, name="convergence")
synthetic_app = typer.Typer(
    add_completion=False,
    help="Synthetic super-wallet prospective strategy backtest reports (Phase 10, shadow-only)",
)
app.add_typer(synthetic_app, name="synthetic")
counterfactual_app = typer.Typer(
    add_completion=False,
    help="Counterfactual alpha + entry/discovery/validation/exit specialist reports (Phase 9)",
)
app.add_typer(counterfactual_app, name="counterfactual")
predict_app = typer.Typer(
    add_completion=False,
    help="Predict-informed-order-flow model evaluation reports (Phase 11)",
)
app.add_typer(predict_app, name="predict")

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


def _phase2_engine_and_sessionmaker():
    """Shared Phase 2 CLI wiring: one engine + one sessionmaker per
    invocation, disposed at the end -- same convention as
    ``ingest_run``/``ingest_reparse`` (never a shared long-lived session)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    config = load_config()
    info = connection_for_role(config, DbRole.INGEST)
    engine = create_async_engine(info.as_asyncpg_url())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    return config, engine, sessionmaker


@tokens_app.command("import-bootstrap")
def tokens_import_bootstrap(
    mint: str = typer.Option(..., "--mint", help="Candidate Solana token mint address."),
    evidence_file: str = typer.Option(
        ...,
        "--evidence-file",
        help="Path to a JSON file: a genuine Solana getAccountInfo response "
        "({'value': {...}}, --evidence-kind account_info) or a genuine getTransaction "
        "response whose own token-balance evidence covers this mint "
        "(--evidence-kind token_balance).",
    ),
    evidence_kind: str = typer.Option(
        "token_balance",
        "--evidence-kind",
        help="'account_info' (live getAccountInfo response, the real production path) or "
        "'token_balance' (a committed getTransaction response -- this sandbox's free-first "
        "evidence path; see argus.tokens.mint_validation).",
    ),
    commitment: str = typer.Option(
        "",
        "--commitment",
        help="Only meaningful for --evidence-kind account_info: the commitment level "
        "('processed'/'confirmed'/'finalized') the live getAccountInfo call was itself "
        "made at, persisted as this validation attempt's provenance (P2-R8).",
    ),
) -> None:
    """Deterministic bootstrap-token importer (MASTER_SPEC.md Phase 2 build
    item 5): creates or reuses a ``tokens`` row for ``mint`` and runs
    on-chain mint validation against genuine committed evidence, recording
    every attempt as an immutable ``token_mint_validations`` row. Never
    reports ``mint_validated=true`` from address shape alone."""
    import json
    from datetime import UTC, datetime
    from typing import cast

    from argus.config import resolve_production_git_commit
    from argus.tokens.importer import EvidenceKind, import_bootstrap_token

    if evidence_kind not in ("account_info", "token_balance"):
        console.print(
            f"[red]--evidence-kind must be 'account_info' or 'token_balance', "
            f"got {evidence_kind!r}[/red]"
        )
        raise typer.Exit(code=1)

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            evidence = json.loads(Path(evidence_file).read_text())
            if isinstance(evidence, list):
                evidence = evidence[0]
            # Phase 2 CLI commands are offline, evidence-file-driven research
            # tools -- never a live signer/execution path -- so, like
            # `ingest run --test-mode`, they use the honest
            # GIT_COMMIT_UNAVAILABLE fallback on a dirty/unverifiable
            # checkout rather than failing closed like production ingestion.
            git_commit = resolve_production_git_commit(allow_unverified=True)
            async with sessionmaker() as session, session.begin():
                result = await import_bootstrap_token(
                    session,
                    mint=mint,
                    evidence=evidence,
                    evidence_kind=cast(EvidenceKind, evidence_kind),
                    evidence_reference=evidence_file,
                    now=datetime.now(UTC),
                    config=config,
                    git_commit=git_commit,
                    commitment=commitment or None,
                )
        finally:
            await engine.dispose()
        console.print(
            f"token_id={result.token_id} mint={result.mint} "
            f"status={result.validation.status} source={result.validation.validation_source} "
            f"decimals={result.validation.decimals} mint_validated={result.mint_validated} "
            f"chain_time={result.validation.chain_time} commitment={result.validation.commitment} "
            f"reason={result.validation.reason}"
        )
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@discover_app.command("archaeology-run")
def discover_archaeology_run(
    mint: str = typer.Option(
        ..., "--mint", help="Must already be imported via 'tokens import-bootstrap'."
    ),
    run_type: str = typer.Option(
        "HISTORICAL_WINNER", "--run-type", help="'HISTORICAL_WINNER' or 'PROSPECTIVE_WINNER'."
    ),
    evidence_file: list[str] = typer.Option(  # noqa: B008 - required Typer CLI-option idiom
        ...,
        "--evidence-file",
        help="Path to a genuine getTransaction-shaped JSON file (repeatable) -- every "
        "transaction to search for early buyers of this mint.",
    ),
    deployer_wallet: str = typer.Option(
        "", "--deployer-wallet", help="Optional: tag this wallet possible_deployer if recovered."
    ),
    known_gaps: str = typer.Option(
        "", "--known-gaps", help="Free-text disclosure of what this evidence set does NOT cover."
    ),
    completeness_statement: str = typer.Option(
        ..., "--completeness-statement", help="Required honest statement of evidence completeness."
    ),
    source_provider_set: str = typer.Option(
        "committed_evidence_replay",
        "--source-provider-set",
        help="Free-text description of where --evidence-file came from.",
    ),
    trigger_id: str = typer.Option(
        "", "--trigger-id", help="Optional: consume a specific pending archaeology_triggers row."
    ),
    partial: bool = typer.Option(
        False, "--partial", help="Mark this run PARTIAL (evidence set is known incomplete)."
    ),
) -> None:
    """Runs one archaeology job for a token already imported via
    'tokens import-bootstrap': recovers early buyers deterministically
    from the given evidence files (MASTER_SPEC.md section 33), creates
    wallet/wallet_discovery_events/early_buyers rows, and always leaves
    exactly one archaeology_runs row in a terminal COMPLETED/PARTIAL/
    FAILED state. Reusing the same evidence files on a retry is safe --
    no duplicate wallet, discovery event, or early-buyer row is ever
    created."""
    import json
    import uuid as uuid_module
    from datetime import UTC, datetime

    from sqlalchemy import select

    from argus.config import resolve_production_git_commit
    from argus.domain.tokens import Token
    from argus.wallets.archaeology import run_archaeology
    from argus.wallets.early_buyer_extraction import RawTransactionEvidence

    if run_type not in ("HISTORICAL_WINNER", "PROSPECTIVE_WINNER"):
        console.print("[red]--run-type must be HISTORICAL_WINNER or PROSPECTIVE_WINNER[/red]")
        raise typer.Exit(code=1)

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            git_commit = resolve_production_git_commit(allow_unverified=True)
            now = datetime.now(UTC)
            transactions: list[RawTransactionEvidence] = []
            for path in evidence_file:
                raw = json.loads(Path(path).read_text())
                if isinstance(raw, list):
                    raw = raw[0]
                sig = raw["transaction"]["signatures"][0]
                block_time = raw.get("blockTime")
                transactions.append(
                    RawTransactionEvidence(
                        raw=raw,
                        signature=sig,
                        slot=raw["slot"],
                        block_time=(
                            datetime.fromtimestamp(block_time, tz=UTC) if block_time else None
                        ),
                        evidence_reference=path,
                    )
                )

            async with sessionmaker() as session:
                token = (
                    await session.execute(select(Token).where(Token.mint == mint))
                ).scalar_one_or_none()
            if token is None:
                console.print(
                    f"[red]no tokens row for mint {mint!r} -- run "
                    f"'argus tokens import-bootstrap --mint {mint}' first[/red]"
                )
                return 1

            from argus.domain.wallet_discovery_events import (
                DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
                DISCOVERY_CHANNEL_PROSPECTIVE_WINNER_ARCHAEOLOGY,
            )

            discovery_channel = (
                DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY
                if run_type == "HISTORICAL_WINNER"
                else DISCOVERY_CHANNEL_PROSPECTIVE_WINNER_ARCHAEOLOGY
            )
            # P2-R6: run_archaeology manages its own durable, independently
            # -committing transaction phases (claim / extract+persist
            # outputs / terminalize) -- it takes the sessionmaker itself,
            # never one already-open caller transaction, so a crash mid-run
            # leaves genuine, queryable evidence rather than everything
            # rolling back together.
            result = await run_archaeology(
                sessionmaker,
                token_id=token.token_id,
                mint=mint,
                run_type=run_type,
                transactions=transactions,
                discovery_channel=discovery_channel,
                source_provider_set=source_provider_set,
                input_evidence_reference=", ".join(evidence_file),
                time_range_start=None,
                time_range_end=None,
                known_gaps=known_gaps or None,
                completeness_statement=completeness_statement,
                config=config,
                git_commit=git_commit,
                now=now,
                trigger_id=uuid_module.UUID(trigger_id) if trigger_id else None,
                deployer_wallet=deployer_wallet or None,
                is_partial=partial,
            )
        finally:
            await engine.dispose()
        console.print(
            f"run_id={result.run_id} status={result.status} "
            f"early_buyers_recovered={result.early_buyers_recovered} "
            f"wallets_discovered={result.wallets_discovered} "
            f"unresolved_ownership_count={result.unresolved_ownership_count}"
        )
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@discover_app.command("watch-replay")
def discover_watch_replay(
    mint: str = typer.Option(
        ..., "--mint", help="Must already be imported via 'tokens import-bootstrap'."
    ),
    snapshots_file: str = typer.Option(
        ...,
        "--snapshots-file",
        help="Path to a JSON file: a list of market-snapshot observation objects "
        "(observed_at, lifecycle_stage, source, price_usd, liquidity_usd, ...). "
        "REPLAY data -- see argus.wallets.watcher_service module docstring; this is "
        "never a claim of live market-data provider access.",
    ),
) -> None:
    """Runs the deterministic prospective winner watcher
    (MASTER_SPEC.md Phase 2 build items 9-11) against a REPLAY market-
    snapshot history for a token already imported via
    'tokens import-bootstrap': records each snapshot idempotently, then
    detects and persists any new winner-milestone crossing plus its
    linked archaeology_triggers row. Labeled REPLAY throughout -- never
    claims live Helius/market-data validation."""
    import json
    from datetime import UTC, datetime
    from decimal import Decimal

    from sqlalchemy import select

    from argus.domain.tokens import Token
    from argus.tokens.market_snapshots import MarketSnapshotDraft, record_snapshot
    from argus.wallets.watcher_service import evaluate_token

    async def _run() -> int:
        _config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            now = datetime.now(UTC)
            raw_snapshots = json.loads(Path(snapshots_file).read_text())
            async with sessionmaker() as session, session.begin():
                token = (
                    await session.execute(select(Token).where(Token.mint == mint))
                ).scalar_one_or_none()
                if token is None:
                    console.print(
                        f"[red]no tokens row for mint {mint!r} -- run "
                        f"'argus tokens import-bootstrap --mint {mint}' first[/red]"
                    )
                    return 1

                for entry in raw_snapshots:
                    draft = MarketSnapshotDraft(
                        token_id=token.token_id,
                        observed_at=datetime.fromisoformat(entry["observed_at"]),
                        lifecycle_stage=entry["lifecycle_stage"],
                        source=entry.get("source", "replay_fixture"),
                        venue=entry.get("venue"),
                        venue_program=entry.get("venue_program"),
                        pool_or_curve_address=entry.get("pool_or_curve_address"),
                        price_usd=(
                            Decimal(str(entry["price_usd"])) if entry.get("price_usd") else None
                        ),
                        liquidity_usd=(
                            Decimal(str(entry["liquidity_usd"]))
                            if entry.get("liquidity_usd")
                            else None
                        ),
                        market_state_confidence=entry.get("market_state_confidence"),
                        evidence_reference=entry.get("evidence_reference", snapshots_file),
                    )
                    await record_snapshot(session, draft, now=now)

                evaluations = await evaluate_token(session, token_id=token.token_id, now=now)
        finally:
            await engine.dispose()

        if not evaluations:
            console.print("no new winner-milestone crossings detected")
        for evaluation in evaluations:
            console.print(
                f"REPLAY milestone crossed: category={evaluation.crossing.category} "
                f"multiple_x={evaluation.crossing.multiple_x} "
                f"milestone_id={evaluation.milestone_id} trigger_id={evaluation.trigger_id} "
                f"(newly_recorded={evaluation.milestone_newly_recorded})"
            )
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@discover_app.command("run-pending-trigger")
def discover_run_pending_trigger(
    mint: str = typer.Option(
        ..., "--mint", help="Must already be imported via 'tokens import-bootstrap'."
    ),
    evidence_file: list[str] = typer.Option(  # noqa: B008 - required Typer CLI-option idiom
        ...,
        "--evidence-file",
        help="Path to a genuine getTransaction-shaped JSON file (repeatable) -- evidence "
        "for whichever pending trigger(s) are consumed.",
    ),
    known_gaps: str = typer.Option(
        "", "--known-gaps", help="Free-text disclosure of what this evidence set does NOT cover."
    ),
    completeness_statement: str = typer.Option(
        ..., "--completeness-statement", help="Required honest statement of evidence completeness."
    ),
    source_provider_set: str = typer.Option(
        "committed_evidence_replay",
        "--source-provider-set",
        help="Free-text description of where --evidence-file came from.",
    ),
    trigger_type: str = typer.Option(
        "", "--trigger-type", help="Restrict to 'HISTORICAL_WINNER' or 'PROSPECTIVE_WINNER' only."
    ),
    max_triggers: int = typer.Option(
        10, "--max-triggers", help="Bounded sweep ceiling -- never an unbounded loop (P2-R5)."
    ),
    partial: bool = typer.Option(
        False,
        "--partial",
        help="Mark each consumed run PARTIAL (evidence set is known incomplete).",
    ),
) -> None:
    """P2-R5 automatic trigger execution: finds and runs whichever
    archaeology_triggers are pending for this token itself -- never a
    human copying a trigger ID from one command's output into another's
    input. Reports 'no pending triggers' honestly when there is nothing
    to do, which is a normal outcome, not an error."""
    import json
    from datetime import UTC, datetime

    from sqlalchemy import select

    from argus.config import resolve_production_git_commit
    from argus.domain.tokens import Token
    from argus.wallets.archaeology import run_all_pending_triggers_for_token
    from argus.wallets.early_buyer_extraction import RawTransactionEvidence

    if trigger_type and trigger_type not in ("HISTORICAL_WINNER", "PROSPECTIVE_WINNER"):
        console.print("[red]--trigger-type must be HISTORICAL_WINNER or PROSPECTIVE_WINNER[/red]")
        raise typer.Exit(code=1)

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            git_commit = resolve_production_git_commit(allow_unverified=True)
            now = datetime.now(UTC)
            transactions: list[RawTransactionEvidence] = []
            for path in evidence_file:
                raw = json.loads(Path(path).read_text())
                if isinstance(raw, list):
                    raw = raw[0]
                sig = raw["transaction"]["signatures"][0]
                block_time = raw.get("blockTime")
                transactions.append(
                    RawTransactionEvidence(
                        raw=raw,
                        signature=sig,
                        slot=raw["slot"],
                        block_time=(
                            datetime.fromtimestamp(block_time, tz=UTC) if block_time else None
                        ),
                        evidence_reference=path,
                    )
                )

            async with sessionmaker() as session:
                token = (
                    await session.execute(select(Token).where(Token.mint == mint))
                ).scalar_one_or_none()
            if token is None:
                console.print(
                    f"[red]no tokens row for mint {mint!r} -- run "
                    f"'argus tokens import-bootstrap --mint {mint}' first[/red]"
                )
                return 1

            results = await run_all_pending_triggers_for_token(
                sessionmaker,
                token_id=token.token_id,
                mint=mint,
                transactions=transactions,
                source_provider_set=source_provider_set,
                known_gaps=known_gaps or None,
                completeness_statement=completeness_statement,
                config=config,
                git_commit=git_commit,
                now=now,
                max_triggers=max_triggers,
                trigger_type=trigger_type or None,
                is_partial=partial,
            )
        finally:
            await engine.dispose()

        if not results:
            console.print("no pending triggers for this token")
            return 0
        for result in results:
            console.print(
                f"run_id={result.run_id} status={result.status} "
                f"early_buyers_recovered={result.early_buyers_recovered} "
                f"wallets_discovered={result.wallets_discovered} "
                f"unresolved_ownership_count={result.unresolved_ownership_count}"
            )
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@discover_app.command("acquire-and-run-archaeology")
def discover_acquire_and_run_archaeology(
    mint: str = typer.Option(
        ..., "--mint", help="Must already be imported via 'tokens import-bootstrap'."
    ),
    address: str = typer.Option(
        ...,
        "--address",
        help="Address whose signature history to walk live via Helius "
        "getSignaturesForAddress -- typically the mint account itself or its "
        "bonding-curve/pool address. This is the P2-R2 live acquisition path; the "
        "offline --evidence-file path ('argus discover archaeology-run') remains "
        "available for deterministic replay demonstrations.",
    ),
    run_type: str = typer.Option(
        "HISTORICAL_WINNER", "--run-type", help="'HISTORICAL_WINNER' or 'PROSPECTIVE_WINNER'."
    ),
    max_pages: int = typer.Option(
        50,
        "--max-pages",
        help="Safety ceiling on paginated getSignaturesForAddress calls (P2-R2) -- never "
        "an unbounded walk. Default matches historical_acquisition.DEFAULT_MAX_PAGES.",
    ),
    page_size: int = typer.Option(
        1000,
        "--page-size",
        help="Signatures requested per page. Default matches "
        "historical_acquisition.DEFAULT_PAGE_SIZE.",
    ),
    expected_oldest_slot: int | None = typer.Option(
        None,
        "--expected-oldest-slot",
        help="P2-R2 remediation round 2: an independently known expected historical "
        "boundary for ADDRESS (e.g. a token's own known creation slot). When given, an "
        "empty/short page is trusted as a genuine COMPLETE walk only once this slot has "
        "actually been observed -- a provider truncating early before then is reported "
        "PARTIAL, never silently COMPLETE. Omit when no independent boundary is known; "
        "the walk then keeps the exact prior (round-1) short/empty-page-is-complete "
        "behavior unchanged.",
    ),
    deployer_wallet: str = typer.Option(
        "", "--deployer-wallet", help="Optional: tag this wallet possible_deployer if recovered."
    ),
    known_gaps: str = typer.Option(
        "",
        "--known-gaps",
        help="Additional free-text disclosure, appended to whatever gaps the live "
        "acquisition walk itself detected (pagination faults, fetch failures, ...).",
    ),
    completeness_statement: str = typer.Option(
        "",
        "--completeness-statement",
        help="Optional override of the acquisition service's own honest completeness "
        "statement; leave empty to use the one it derives from the actual walk outcome.",
    ),
    trigger_id: str = typer.Option(
        "", "--trigger-id", help="Optional: consume a specific pending archaeology_triggers row."
    ),
) -> None:
    """P2-R2: the real, live acquisition path -- opens a Helius RPC client
    (same credential/usage-recorder wiring as 'argus ingest run'), walks
    ADDRESS's signature history back to genesis (bounded, cursor-based,
    fault-detecting -- MASTER_SPEC.md section 27-33), fetches every
    transaction, and feeds the result directly into the same
    run_archaeology() path 'argus discover archaeology-run' uses. Never
    reports the archaeology run COMPLETE when the acquisition walk itself
    was PARTIAL/FAILED -- that status flows straight into is_partial."""
    import uuid
    from datetime import UTC, datetime

    import httpx
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from argus.config import resolve_production_git_commit
    from argus.db.connection import connection_for_role
    from argus.db.roles import DbRole
    from argus.domain.tokens import Token
    from argus.domain.wallet_discovery_events import (
        DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY,
        DISCOVERY_CHANNEL_PROSPECTIVE_WINNER_ARCHAEOLOGY,
    )
    from argus.providers.credentials import MissingProviderCredentialError
    from argus.providers.helius.client import HeliusRpcClient, resolve_helius_api_key
    from argus.providers.retry import retry_policy_from_config
    from argus.providers.usage import SqlUsageRecorder
    from argus.tokens.historical_acquisition import (
        STATUS_COMPLETE,
        acquire_historical_transactions,
    )
    from argus.wallets.archaeology import run_archaeology

    if run_type not in ("HISTORICAL_WINNER", "PROSPECTIVE_WINNER"):
        console.print("[red]--run-type must be HISTORICAL_WINNER or PROSPECTIVE_WINNER[/red]")
        raise typer.Exit(code=1)

    async def _run() -> int:
        config = load_config()
        try:
            api_key = resolve_helius_api_key(config.env)
        except MissingProviderCredentialError as exc:
            console.print(str(exc))
            return 1

        db_info = connection_for_role(config, DbRole.INGEST)
        db_engine = create_async_engine(db_info.as_asyncpg_url())
        sessionmaker = async_sessionmaker(db_engine, expire_on_commit=False)
        try:
            git_commit = resolve_production_git_commit(allow_unverified=True)
            now = datetime.now(UTC)

            async with sessionmaker() as session:
                token = (
                    await session.execute(select(Token).where(Token.mint == mint))
                ).scalar_one_or_none()
            if token is None:
                console.print(
                    f"[red]no tokens row for mint {mint!r} -- run "
                    f"'argus tokens import-bootstrap --mint {mint}' first[/red]"
                )
                return 1

            retry_policy = retry_policy_from_config(config)
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                usage_recorder = SqlUsageRecorder(sessionmaker)
                rpc_client = HeliusRpcClient(
                    api_key,
                    http_client=http_client,
                    retry_policy=retry_policy,
                    usage_recorder=usage_recorder,
                )
                acquisition = await acquire_historical_transactions(
                    rpc_client,
                    address=address,
                    max_pages=max_pages,
                    page_size=page_size,
                    expected_oldest_slot=expected_oldest_slot,
                )

            console.print(
                f"acquisition: status={acquisition.status} "
                f"pages_fetched={acquisition.pages_fetched} "
                f"signatures_seen={acquisition.signatures_seen} "
                f"transactions_recovered={len(acquisition.transactions)} "
                f"transaction_fetch_failures={acquisition.transaction_fetch_failures}"
            )
            if acquisition.known_gaps:
                console.print(f"acquisition known_gaps: {acquisition.known_gaps}")

            combined_known_gaps = "; ".join(
                part for part in (known_gaps or None, acquisition.known_gaps) if part
            )
            discovery_channel = (
                DISCOVERY_CHANNEL_HISTORICAL_WINNER_ARCHAEOLOGY
                if run_type == "HISTORICAL_WINNER"
                else DISCOVERY_CHANNEL_PROSPECTIVE_WINNER_ARCHAEOLOGY
            )
            result = await run_archaeology(
                sessionmaker,
                token_id=token.token_id,
                mint=mint,
                run_type=run_type,
                transactions=acquisition.transactions,
                discovery_channel=discovery_channel,
                source_provider_set="helius_live_acquisition",
                input_evidence_reference=f"live_acquisition:{address}",
                time_range_start=None,
                time_range_end=None,
                known_gaps=combined_known_gaps or None,
                completeness_statement=completeness_statement or acquisition.completeness_statement,
                config=config,
                git_commit=git_commit,
                now=now,
                trigger_id=uuid.UUID(trigger_id) if trigger_id else None,
                deployer_wallet=deployer_wallet or None,
                is_partial=acquisition.status != STATUS_COMPLETE,
            )
        finally:
            await db_engine.dispose()
        console.print(
            f"run_id={result.run_id} status={result.status} "
            f"early_buyers_recovered={result.early_buyers_recovered} "
            f"wallets_discovered={result.wallets_discovered} "
            f"unresolved_ownership_count={result.unresolved_ownership_count}"
        )
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@wallets_app.command("acquire-history")
def wallets_acquire_history(
    wallet: str = typer.Option(
        ..., "--wallet", help="Must already be a discovered wallet (Phase 2 'wallets' row)."
    ),
    max_pages: int = typer.Option(
        50, "--max-pages", help="Safety ceiling per address walked (wallet + each token account)."
    ),
    page_size: int = typer.Option(1000, "--page-size", help="Signatures requested per page."),
    expected_oldest_slot: int | None = typer.Option(
        None,
        "--expected-oldest-slot",
        help="Optional independently known boundary (e.g. this wallet's first-observed slot "
        "from other evidence) for the wallet-address walk only -- a premature short/empty "
        "page before this slot is reported PARTIAL with the boundary named, rather than "
        "trusted as genuine completion. Omit for the exact unbounded no-boundary behavior.",
    ),
) -> None:
    """P3-R1/P3-R2 remediation rounds 2-3: the real, live acquisition
    path for a wallet -- opens a Helius RPC client (same credential/
    usage-recorder wiring as 'argus ingest run'), walks the wallet
    address's own signature history, enumerates its associated SPL token
    accounts, walks each of those too, feeds every uniquely-signed
    transaction through the real chain_events/swaps parser/persistence
    path, and persists one immutable wallet_acquisition_runs manifest row
    naming the run's own exact acquired-evidence set (not merely a
    summary claim). Prints the resulting run_id -- pass it to 'wallets
    reconstruct-and-score --acquisition-run-id' as LIVE_ACQUISITION_WALK
    evidence. There is no remaining path from a caller-supplied file to a
    completeness claim."""
    from datetime import UTC, datetime

    import httpx
    from sqlalchemy import select

    from argus.config import resolve_production_git_commit
    from argus.domain.wallets import Wallet
    from argus.providers.credentials import MissingProviderCredentialError
    from argus.providers.helius.client import HeliusRpcClient, resolve_helius_api_key
    from argus.providers.retry import retry_policy_from_config
    from argus.providers.usage import SqlUsageRecorder
    from argus.wallets.acquisition import run_wallet_acquisition

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            try:
                api_key = resolve_helius_api_key(config.env)
            except MissingProviderCredentialError as exc:
                console.print(str(exc))
                return 1

            resolve_production_git_commit(allow_unverified=True)
            now = datetime.now(UTC)

            async with sessionmaker() as session, session.begin():
                wallet_row = (
                    await session.execute(select(Wallet).where(Wallet.wallet_address == wallet))
                ).scalar_one_or_none()
                if wallet_row is None:
                    console.print(
                        f"[red]no wallets row for address {wallet!r} -- Phase 3 acquires "
                        "history for already-discovered wallets only[/red]"
                    )
                    return 1
                wallet_id = wallet_row.wallet_id

                retry_policy = retry_policy_from_config(config)
                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    usage_recorder = SqlUsageRecorder(sessionmaker)
                    rpc_client = HeliusRpcClient(
                        api_key,
                        http_client=http_client,
                        retry_policy=retry_policy,
                        usage_recorder=usage_recorder,
                    )
                    outcome = await run_wallet_acquisition(
                        rpc_client,
                        session,
                        wallet_id=wallet_id,
                        wallet_address=wallet,
                        provider_name="helius_live_acquisition",
                        max_pages=max_pages,
                        page_size=page_size,
                        expected_oldest_slot=expected_oldest_slot,
                        now=now,
                    )
        finally:
            await engine.dispose()
        console.print(
            f"run_id={outcome.run_id} wallet_walk_status={outcome.manifest.wallet_walk_status} "
            f"token_accounts_enumerated={outcome.manifest.token_accounts_enumerated} "
            f"associated_token_accounts={len(outcome.manifest.associated_token_accounts)} "
            f"transactions_persisted={outcome.transactions_persisted} "
            f"transactions_already_known={outcome.transactions_already_known}"
        )
        if outcome.manifest.known_gaps:
            console.print(f"known_gaps: {outcome.manifest.known_gaps}")
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@wallets_app.command("reconstruct-and-score")
def wallets_reconstruct_and_score(
    wallet: str = typer.Option(
        ..., "--wallet", help="Must already be a discovered wallet (Phase 2 'wallets' row)."
    ),
    evidence_source: str = typer.Option(
        "STREAM_FORWARD_ONLY",
        "--evidence-source",
        help="'LIVE_ACQUISITION_WALK' (this wallet's own history was actually walked via "
        "'argus wallets acquire-history' -- requires --acquisition-run-id) or "
        "'STREAM_FORWARD_ONLY' (evidence is only from Phase 1 live ingestion, forward-only "
        "from whenever tracking began).",
    ),
    acquisition_run_id: str = typer.Option(
        "",
        "--acquisition-run-id",
        help="Required when --evidence-source=LIVE_ACQUISITION_WALK: the run_id printed by "
        "'argus wallets acquire-history' -- loaded and verified (wallet binding, observation "
        "cutoff <= this score's as_of) from the persisted wallet_acquisition_runs row, never "
        "accepted as an arbitrary caller-supplied file (Phase 3 remediation round 2, P3-R2: a "
        "caller can no longer manufacture HIGH completeness with no real acquisition having "
        "occurred).",
    ),
) -> None:
    """Phase 3 (MASTER_SPEC.md sections 34-43): reconstructs this
    wallet's weighted-average-cost positions from the existing ``swaps``
    ledger, derives an honest history-completeness judgment, computes
    the discovery-contamination-firewalled qualification score and the
    (potentially contaminated) descriptive score separately, and applies
    a deterministic tier-lifecycle transition. Never live-arms, signs, or
    executes anything -- research/scoring only (MASTER_SPEC.md section
    108). Idempotent: re-running against identical evidence writes no
    duplicate position/score/tier row."""
    import uuid
    from datetime import UTC, datetime

    from argus.config import resolve_production_git_commit
    from argus.wallets.history_reconstruction import (
        EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
        EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
    )
    from argus.wallets.qualification_service import reconstruct_and_score_wallet

    if evidence_source not in (
        EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK,
        EVIDENCE_SOURCE_STREAM_FORWARD_ONLY,
    ):
        console.print(
            "[red]--evidence-source must be LIVE_ACQUISITION_WALK or STREAM_FORWARD_ONLY[/red]"
        )
        raise typer.Exit(code=1)

    run_id: uuid.UUID | None = None
    if evidence_source == EVIDENCE_SOURCE_LIVE_ACQUISITION_WALK:
        if not acquisition_run_id:
            console.print(
                "[red]--acquisition-run-id is required when "
                "--evidence-source=LIVE_ACQUISITION_WALK[/red]"
            )
            raise typer.Exit(code=1)
        try:
            run_id = uuid.UUID(acquisition_run_id)
        except ValueError as exc:
            console.print(f"[red]malformed --acquisition-run-id: {exc}[/red]")
            raise typer.Exit(code=1) from exc

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            git_commit = resolve_production_git_commit(allow_unverified=True)
            try:
                result = await reconstruct_and_score_wallet(
                    sessionmaker,
                    wallet_address=wallet,
                    evidence_source=evidence_source,  # type: ignore[arg-type]
                    acquisition_run_id=run_id,
                    config=config,
                    git_commit=git_commit,
                    now=datetime.now(UTC),
                )
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                return 1
        finally:
            await engine.dispose()
        console.print(
            f"wallet_id={result.wallet_id} history_completeness={result.history_completeness} "
            f"positions_reconstructed={result.positions_reconstructed} "
            f"positions_written={result.positions_written} "
            f"positions_unchanged={result.positions_unchanged} "
            f"positions_skipped_untracked_token={result.positions_skipped_untracked_token}"
        )
        console.print(
            f"qualification_score={result.qualification_score} "
            f"descriptive_score={result.descriptive_score} "
            f"eligible_for_qualification={result.eligible_for_qualification} "
            f"score_written={result.score_written}"
        )
        if result.tier_transition is not None:
            new_tier, reason = result.tier_transition
            console.print(f"tier_transition: -> {new_tier} ({reason})")
        else:
            console.print(f"tier_transition: none (current_tier={result.current_tier} unchanged)")
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@prospective_app.command("run")
def prospective_run(
    limit: int = typer.Option(
        100, "--limit", help="Max new prospective events created in this one pass."
    ),
) -> None:
    """Phase 4 (MASTER_SPEC.md sections 44-46): scans the real, already-
    ingested ``swaps`` ledger for new trades from tracked (tier-allowed)
    wallets, creates a point-in-time-frozen prospective event for each,
    and creates a shadow intent (with its scheduled entry-delay probes)
    for every one that passes the honest research-eligibility gate. Call
    repeatedly -- a bounded loop, a cron tick, or alongside ``argus
    ingest run``'s own cadence. Never live-arms, signs, or executes
    anything."""
    from datetime import UTC, datetime

    from argus.shadow.monitor import run_prospective_monitoring_pass

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            result = await run_prospective_monitoring_pass(
                sessionmaker, config=config, now=datetime.now(UTC), limit=limit
            )
        finally:
            await engine.dispose()
        console.print(
            f"prospective_events_created={len(result.prospective_events)} "
            f"shadow_intents_created={len(result.shadow_intents)} "
            f"confirmations_revisited={len(result.confirmed_event_ids)}"
        )
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


def _optional_telegram_notifier(config, http_client):
    """Real, production-capable Telegram wiring -- returns ``None``
    (no-op, per section 94's "disabled/no-op default") unless BOTH
    ``TELEGRAM_BOT_TOKEN``/``TELEGRAM_CHAT_ID`` are explicitly configured.
    Neither is ever set in this sandbox, so every CLI invocation here
    stays inert; a real deployment supplying both gets real notifications
    through the same closed, secret-guarded event-type set every test
    exercises via ``FakeTelegramTransport``."""
    from argus.telegram.notifier import HttpTelegramTransport, TelegramNotifier

    bot_token = config.env.get("TELEGRAM_BOT_TOKEN")
    chat_id = config.env.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return None
    transport = HttpTelegramTransport(http_client=http_client, bot_token=bot_token)
    return TelegramNotifier(transport, chat_id=chat_id)


@shadow_app.command("run-entry-probes")
def shadow_run_entry_probes(
    limit: int = typer.Option(50, "--limit", help="Max due probes claimed in this one pass."),
) -> None:
    """Phase 4 (MASTER_SPEC.md section 46): claims and executes every
    currently-due entry-delay quote probe via the public, credential-free
    Jupiter quote endpoint, recording actual request/response timing and
    creating a shadow position on the first successful entry. Call
    repeatedly. Never signs or submits anything -- quote/inspection only
    (``argus.providers.jupiter.JupiterClient``, the same Phase 1
    prohibition-preserving adapter)."""
    from datetime import UTC, datetime

    import httpx

    from argus.clock import Clock
    from argus.providers.dexscreener.client import DexScreenerClient
    from argus.providers.jupiter.client import JupiterClient
    from argus.providers.retry import retry_policy_from_config
    from argus.providers.scheduler import PriorityScheduler
    from argus.providers.usage import SqlUsageRecorder
    from argus.shadow.quote_jobs import run_due_entry_probes

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            retry_policy = retry_policy_from_config(config)
            scheduler = PriorityScheduler()
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                usage_recorder = SqlUsageRecorder(sessionmaker)
                jupiter = JupiterClient(
                    http_client=http_client,
                    retry_policy=retry_policy,
                    usage_recorder=usage_recorder,
                )
                market = DexScreenerClient(
                    http_client=http_client,
                    retry_policy=retry_policy,
                    usage_recorder=usage_recorder,
                )
                notifier = _optional_telegram_notifier(config, http_client)
                results = await run_due_entry_probes(
                    sessionmaker,
                    jupiter,
                    config=config,
                    clock=Clock(),
                    now=datetime.now(UTC),
                    market_provider=market,
                    scheduler=scheduler,
                    notifier=notifier,
                    limit=limit,
                )
        finally:
            await engine.dispose()
        console.print(f"entry_probes_processed={len(results)}")
        for probe in results:
            console.print(f"  probe_id={probe.probe_id} outcome={probe.outcome}")
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@shadow_app.command("run-reverse-probes")
def shadow_run_reverse_probes(
    limit: int = typer.Option(50, "--limit", help="Max due probes claimed in this one pass."),
) -> None:
    """Phase 4 (MASTER_SPEC.md section 47): claims and executes every
    currently-due reverse-executable quote probe for an open shadow
    position. Quote/inspection only, same Jupiter adapter as
    'shadow run-entry-probes'."""
    from datetime import UTC, datetime

    import httpx

    from argus.clock import Clock
    from argus.providers.jupiter.client import JupiterClient
    from argus.providers.retry import retry_policy_from_config
    from argus.providers.scheduler import PriorityScheduler
    from argus.providers.usage import SqlUsageRecorder
    from argus.shadow.quote_jobs import run_due_reverse_probes

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            retry_policy = retry_policy_from_config(config)
            scheduler = PriorityScheduler()
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                usage_recorder = SqlUsageRecorder(sessionmaker)
                jupiter = JupiterClient(
                    http_client=http_client,
                    retry_policy=retry_policy,
                    usage_recorder=usage_recorder,
                )
                results = await run_due_reverse_probes(
                    sessionmaker,
                    jupiter,
                    config=config,
                    clock=Clock(),
                    now=datetime.now(UTC),
                    scheduler=scheduler,
                    limit=limit,
                )
        finally:
            await engine.dispose()
        console.print(f"reverse_probes_processed={len(results)}")
        for probe in results:
            console.print(f"  probe_id={probe.probe_id} outcome={probe.outcome}")
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@shadow_app.command("run-mark-outcomes")
def shadow_run_mark_outcomes(
    limit: int = typer.Option(50, "--limit", help="Max due mark outcomes claimed in this pass."),
) -> None:
    """Phase 4 (MASTER_SPEC.md section 47): claims and executes every
    currently-due mark-price outcome for an open shadow position via the
    public, credential-free DexScreener token-snapshot endpoint.
    Descriptive-only -- never the primary copyability outcome (see
    'shadow run-reverse-probes')."""
    from datetime import UTC, datetime

    import httpx

    from argus.clock import Clock
    from argus.providers.dexscreener.client import DexScreenerClient
    from argus.providers.retry import retry_policy_from_config
    from argus.providers.usage import SqlUsageRecorder
    from argus.shadow.mark_jobs import run_due_mark_outcomes

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            retry_policy = retry_policy_from_config(config)
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                usage_recorder = SqlUsageRecorder(sessionmaker)
                market = DexScreenerClient(
                    http_client=http_client,
                    retry_policy=retry_policy,
                    usage_recorder=usage_recorder,
                )
                results = await run_due_mark_outcomes(
                    sessionmaker, market, clock=Clock(), now=datetime.now(UTC), limit=limit
                )
        finally:
            await engine.dispose()
        console.print(f"mark_outcomes_processed={len(results)}")
        for row in results:
            console.print(
                f"  shadow_mark_outcome_id={row.shadow_mark_outcome_id} outcome={row.outcome}"
            )
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@report_app.command("daily")
def report_daily() -> None:
    """MASTER_SPEC.md section 93: prints the daily operator report --
    every figure a real queried count over the trailing 24 hours, never a
    fabricated value; sections this offline single-process report cannot
    measure, or whose feature does not exist yet, are explicitly marked
    UNAVAILABLE/NOT_IMPLEMENTED rather than invented."""
    import json
    from datetime import UTC, datetime

    import httpx

    from argus.reports.daily import build_daily_report

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            tier_allowed = config.get("thresholds.wallet_tier_allowed") or []
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                notifier = _optional_telegram_notifier(config, http_client)
                report = await build_daily_report(
                    sessionmaker,
                    now=datetime.now(UTC),
                    tier_allowed=tier_allowed,
                    notifier=notifier,
                )
        finally:
            await engine.dispose()
        console.print(
            json.dumps(
                {
                    "generated_at": report.generated_at.isoformat(),
                    "window_start": report.window_start.isoformat(),
                    "window_end": report.window_end.isoformat(),
                    "system": report.system,
                    "discovery": report.discovery,
                    "tracking": report.tracking,
                    "signals": report.signals,
                    "shadow": report.shadow,
                    "live": report.live,
                    "research": report.research,
                    "data_quality": report.data_quality,
                },
                indent=2,
                default=str,
            )
        )
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@copyability_app.command("report")
def copyability_report(
    wallet: str = typer.Option(
        "", "--wallet", help="Restrict to one tracked wallet address. Omit to report every wallet."
    ),
    as_of: str = typer.Option(
        "", "--as-of", help="ISO-8601 point-in-time cutoff. Defaults to now."
    ),
) -> None:
    """P5-10 (F5-06 remediation): the one 'argus copyability' report
    command. Read-only over already-persisted Phase 1/3/4 evidence (no
    quote-provider dispatch, no evidence mutation) -- computes and
    idempotently persists each wallet's Phase 5 wallet-copyability snapshot
    (MASTER_SPEC.md sections 46-52, M1-M5/M7) AND, when a prospective event
    is known by the cutoff, its most recent per-opportunity trade-readiness
    snapshot (section 53, M6) -- then prints the required report fields. A
    wallet with no shadow-copy sample yet, or no prospective event yet, is
    reported honestly with null/unavailable fields and a stated reason,
    never a fabricated score."""
    import json
    from datetime import UTC, datetime

    from sqlalchemy import select

    from argus.config import resolve_production_git_commit
    from argus.copyability.service import (
        BUILD_HASH,
        compute_and_persist_opportunity_readiness,
        compute_and_persist_wallet_copyability,
    )
    from argus.domain.prospective_events import ProspectiveEvent
    from argus.domain.wallet_score_snapshots import WalletScoreSnapshot
    from argus.domain.wallets import Wallet
    from argus.scoring.config_weights import (
        load_copyability_weights,
        load_trade_readiness_weights,
    )

    as_of_dt = datetime.fromisoformat(as_of) if as_of else datetime.now(UTC)

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            git_commit = resolve_production_git_commit(allow_unverified=True)
            copyability_weights = load_copyability_weights(config)
            readiness_weights = load_trade_readiness_weights(config)
            async with sessionmaker() as session, session.begin():
                query = select(Wallet)
                if wallet:
                    query = query.where(Wallet.wallet_address == wallet)
                wallets = (await session.execute(query)).scalars().all()

                reports = []
                for wallet_row in wallets:
                    computed_at = datetime.now(UTC)
                    snapshot, created = await compute_and_persist_wallet_copyability(
                        session,
                        wallet=wallet_row,
                        as_of=as_of_dt,
                        weights=copyability_weights,
                        build_hash=BUILD_HASH,
                        config_hash=config.config_hash,
                        master_spec_hash=config.spec_hash,
                        git_commit=git_commit,
                        computed_at=computed_at,
                    )

                    qualification_row = (
                        await session.execute(
                            select(WalletScoreSnapshot)
                            .where(
                                WalletScoreSnapshot.wallet_id == wallet_row.wallet_id,
                                WalletScoreSnapshot.created_at <= as_of_dt,
                            )
                            .order_by(WalletScoreSnapshot.created_at.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    qualification_score = (
                        qualification_row.qualification_score
                        if qualification_row is not None
                        else None
                    )

                    # The most recent decision-time opportunity for this
                    # wallet known by the cutoff -- M6's own point-in-time
                    # rule (never a still-future or not-yet-known event).
                    latest_event = (
                        await session.execute(
                            select(ProspectiveEvent)
                            .where(
                                ProspectiveEvent.wallet_id == wallet_row.wallet_id,
                                ProspectiveEvent.created_at <= as_of_dt,
                                ProspectiveEvent.first_seen_at <= as_of_dt,
                            )
                            .order_by(ProspectiveEvent.first_seen_at.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()

                    readiness_report: dict | None = None
                    readiness_unavailable_reason: str | None = None
                    if latest_event is None:
                        readiness_unavailable_reason = (
                            "no prospective event known by this cutoff for this wallet"
                        )
                    else:
                        (
                            readiness_snapshot,
                            readiness_created,
                        ) = await compute_and_persist_opportunity_readiness(
                            session,
                            prospective_event=latest_event,
                            as_of=as_of_dt,
                            copyability_weights=copyability_weights,
                            readiness_weights=readiness_weights,
                            build_hash=BUILD_HASH,
                            config_hash=config.config_hash,
                            master_spec_hash=config.spec_hash,
                            git_commit=git_commit,
                            computed_at=computed_at,
                        )
                        readiness_report = {
                            "prospective_event_id": str(latest_event.prospective_event_id),
                            "as_of": readiness_snapshot.as_of.isoformat(),
                            "snapshot_reused": not readiness_created,
                            "eligible": readiness_snapshot.eligible,
                            "actionable_score": (
                                str(readiness_snapshot.actionable_score)
                                if readiness_snapshot.actionable_score is not None
                                else None
                            ),
                            "diagnostic_score": (
                                str(readiness_snapshot.diagnostic_score)
                                if readiness_snapshot.diagnostic_score is not None
                                else None
                            ),
                            "gates": readiness_snapshot.gates,
                            "components": readiness_snapshot.components,
                            "evidence_manifest_digest": readiness_snapshot.evidence_manifest_digest,
                            "excluded_source_ids": readiness_snapshot.excluded_source_ids,
                        }

                    reports.append(
                        {
                            "wallet": wallet_row.wallet_address,
                            "as_of": snapshot.as_of.isoformat(),
                            "algorithm_version": snapshot.algorithm_version,
                            "snapshot_reused": not created,
                            "qualification_score": (
                                str(qualification_score)
                                if qualification_score is not None
                                else None
                            ),
                            "qualification_unavailable_reason": (
                                None
                                if qualification_score is not None
                                else "no wallet score snapshot known by this cutoff"
                            ),
                            "copyability_score": (
                                str(snapshot.copyability_score)
                                if snapshot.copyability_score is not None
                                else None
                            ),
                            "copyability_components": snapshot.copyability_components,
                            "sample_n": snapshot.sample_n,
                            "sample_k": snapshot.sample_k,
                            "sample_coverage": str(snapshot.sample_coverage),
                            "confidence": snapshot.confidence,
                            "delay_curve": snapshot.delay_curve,
                            "half_life_result": snapshot.half_life_result,
                            "forward_information_grid": snapshot.forward_information_grid,
                            "size_surprise": snapshot.size_surprise,
                            "readiness": readiness_report,
                            "readiness_unavailable_reason": readiness_unavailable_reason,
                            "contributing_source_ids": snapshot.contributing_source_ids,
                            "excluded_source_ids": snapshot.excluded_source_ids,
                            "evidence_manifest_digest": snapshot.evidence_manifest_digest,
                            "config_hash": snapshot.config_hash,
                            "master_spec_hash": snapshot.master_spec_hash,
                            "build_hash": snapshot.build_hash,
                            "git_commit": snapshot.git_commit,
                            "limitations": [
                                "risk_caps gate is always UNKNOWN in this phase -- no live "
                                "risk-allowance/authority system exists yet (Phase 6 territory)",
                                "real live trade authorization is unconditionally false in this "
                                "phase regardless of any score here (P5-14)",
                                "wallet-level copyability size surprise has no current-"
                                "opportunity size at this report scope -- z/component stay "
                                "unavailable; see the per-opportunity readiness size_surprise "
                                "component for an evidenced current size when available",
                            ],
                        }
                    )
        finally:
            await engine.dispose()

        if not reports:
            console.print("no tracked wallets found -- nothing to report")
            return 0
        console.print(json.dumps(reports, indent=2, default=str))
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@executor_app.command("readiness")
def executor_readiness() -> None:
    """Print the honest Phase 6 (hardened isolated executor) software-
    readiness disposition (P6-17). This command never touches a signer,
    a live provider, or a real arm file -- ``LIVE_CANARY_PASSED`` and
    ``LIVE_ARMED`` are unconditionally ``false`` in its output regardless
    of every ``software_criteria`` entry being met (MASTER_SPEC section
    82: software readiness is never the same thing as live readiness)."""
    import json

    from argus.config import resolve_production_git_commit
    from argus.executor.service import BUILD_HASH, build_phase6_disposition

    config = load_config()
    git_commit = resolve_production_git_commit(allow_unverified=True)
    disposition = build_phase6_disposition()
    payload = disposition.as_dict()
    payload["build_hash"] = BUILD_HASH
    payload["config_hash"] = config.config_hash
    payload["master_spec_hash"] = config.spec_hash
    payload["git_commit"] = git_commit
    console.print(json.dumps(payload, indent=2, default=str))


@graph_app.command("report")
def graph_report(
    as_of: str | None = typer.Option(
        None, "--as-of", help="ISO-8601 cutoff (default: now). Point-in-time honest."
    ),
    max_lag_minutes: int = typer.Option(
        60, "--max-lag-minutes", help="Maximum leader-to-follower lag considered (section 7)."
    ),
    min_observations: int = typer.Option(
        3, "--min-observations", help="Minimum observation count for an upstream candidate."
    ),
    q_value_threshold: str = typer.Option(
        "0.05", "--q-value-threshold", help="Benjamini-Hochberg FDR threshold for candidates."
    ),
    wallet: str | None = typer.Option(
        None, "--wallet", help="If set, also list upstream candidates for this wallet address."
    ),
    top_n: int = typer.Option(20, "--top-n", help="Number of top directional edges to print."),
) -> None:
    """Print top directional lead/follow edges (MASTER_SPEC.md Phase 7,
    ALPHA ANCESTRY) -- purely observational statistics, never a causal
    claim (see argus.graph.lead_follow's own docstring)."""
    import json
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from sqlalchemy import select

    from argus.config import resolve_production_git_commit
    from argus.domain.wallets import Wallet
    from argus.graph.lead_follow import generate_upstream_candidates
    from argus.graph.service import (
        BUILD_HASH,
        GraphRunConfig,
        compute_and_persist_directional_edges,
    )

    as_of_dt = datetime.fromisoformat(as_of) if as_of else datetime.now(UTC)
    config = GraphRunConfig(
        max_lag=timedelta(minutes=max_lag_minutes),
        min_observations=min_observations,
        q_value_threshold=Decimal(q_value_threshold),
    )

    async def _run() -> int:
        _config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            git_commit = resolve_production_git_commit(allow_unverified=True)
            async with sessionmaker() as session, session.begin():
                result = await compute_and_persist_directional_edges(
                    session, cutoff=as_of_dt, config=config, computed_at=datetime.now(UTC)
                )

                wallet_addresses: dict[str, str] = {}
                wallet_ids = {e.edge.leader_wallet_id for e in result.edges} | {
                    e.edge.follower_wallet_id for e in result.edges
                }
                if wallet_ids:
                    rows = (
                        (
                            await session.execute(
                                select(Wallet).where(Wallet.wallet_id.in_(wallet_ids))
                            )
                        )
                        .scalars()
                        .all()
                    )
                    wallet_addresses = {str(r.wallet_id): r.wallet_address for r in rows}

                sorted_edges = sorted(
                    result.edges,
                    key=lambda e: (e.q_value, -(e.edge.effect_size or Decimal("-Infinity"))),
                )[:top_n]

                report = {
                    "as_of": result.as_of.isoformat(),
                    "algorithm_version": "alpha_ancestry_v1",
                    "config_hash": config.config_hash(),
                    "build_hash": BUILD_HASH,
                    "git_commit": git_commit,
                    "wallets_observed": result.wallet_count,
                    "total_observations": result.observation_count,
                    "top_directional_edges": [
                        {
                            "leader_wallet": wallet_addresses.get(
                                str(e.edge.leader_wallet_id), str(e.edge.leader_wallet_id)
                            ),
                            "follower_wallet": wallet_addresses.get(
                                str(e.edge.follower_wallet_id), str(e.edge.follower_wallet_id)
                            ),
                            "observation_count": e.edge.observation_count,
                            "lift": str(e.edge.lift) if e.edge.lift is not None else None,
                            "median_lag_seconds": str(e.edge.median_lag_seconds),
                            "effect_size": (
                                str(e.edge.effect_size) if e.edge.effect_size is not None else None
                            ),
                            "p_value": str(e.edge.p_value),
                            "q_value": str(e.q_value),
                            "forward_information_after_leader_pct": None,
                        }
                        for e in sorted_edges
                    ],
                    "limitations": [
                        "purely observational/correlational -- never a causal claim "
                        "(MASTER_SPEC section 7's own explicit rule)",
                        "forward_information_after_leader_pct is always null in this build -- "
                        "computing it honestly requires reusing Phase 5's cohort-matched "
                        "executable-return evidence per observation, deferred (see "
                        "docs/DECISION_LOG.md)",
                    ],
                }

                if wallet:
                    target = (
                        await session.execute(select(Wallet).where(Wallet.wallet_address == wallet))
                    ).scalar_one_or_none()
                    if target is None:
                        report["upstream_candidates_for_wallet"] = None
                        report["upstream_candidates_unavailable_reason"] = (
                            f"no wallet found with address {wallet!r}"
                        )
                    else:
                        candidates = generate_upstream_candidates(
                            result.edges,
                            follower_wallet_id=target.wallet_id,
                            q_value_threshold=config.q_value_threshold,
                            min_observations=config.min_observations,
                        )
                        report["upstream_candidates_for_wallet"] = wallet
                        report["upstream_candidates"] = [
                            {
                                "leader_wallet": wallet_addresses.get(
                                    str(c.edge.leader_wallet_id), str(c.edge.leader_wallet_id)
                                ),
                                "observation_count": c.edge.observation_count,
                                "lift": str(c.edge.lift) if c.edge.lift is not None else None,
                                "effect_size": (
                                    str(c.edge.effect_size)
                                    if c.edge.effect_size is not None
                                    else None
                                ),
                                "q_value": str(c.q_value),
                            }
                            for c in candidates
                        ]
        finally:
            await engine.dispose()

        console.print(json.dumps(report, indent=2, default=str))
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@convergence_app.command("report")
def convergence_report(
    as_of: str | None = typer.Option(
        None, "--as-of", help="ISO-8601 cutoff (default: now). Point-in-time honest."
    ),
    convergence_window_minutes: int = typer.Option(
        30,
        "--convergence-window-minutes",
        help="Episode window anchored at a token's first entrant.",
    ),
    max_lag_minutes: int = typer.Option(
        60, "--max-lag-minutes", help="Same Phase 7 leader-to-follower lag window (section 7)."
    ),
    min_observations: int = typer.Option(
        3,
        "--min-observations",
        help="Minimum observation count for a significant directional edge.",
    ),
    q_value_threshold: str = typer.Option(
        "0.05",
        "--q-value-threshold",
        help="Benjamini-Hochberg FDR threshold for significant edges.",
    ),
    strong_surprisal_threshold: str = typer.Option(
        "3.0",
        "--strong-surprisal-threshold",
        help="Convergence surprisal above which STRONG applies.",
    ),
    top_n: int = typer.Option(20, "--top-n", help="Number of top convergence episodes to print."),
) -> None:
    """Print top convergence episodes by surprisal (MASTER_SPEC.md Phase
    8, CONVERGENCE SURPRISE) and dog-that-didn't-bark confirmation outcome
    counts (section 60) -- purely observational statistics, never a
    causal claim; no 0-100 score is ever produced (section 59's own
    explicit prohibition until calibration is defined)."""
    import json
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from sqlalchemy import select

    from argus.config import resolve_production_git_commit
    from argus.convergence.service import (
        BUILD_HASH,
        ConvergenceRunConfig,
        compute_and_persist_phase8,
    )
    from argus.domain.tokens import Token
    from argus.graph.service import GraphRunConfig

    as_of_dt = datetime.fromisoformat(as_of) if as_of else datetime.now(UTC)
    graph_config = GraphRunConfig(
        max_lag=timedelta(minutes=max_lag_minutes),
        min_observations=min_observations,
        q_value_threshold=Decimal(q_value_threshold),
    )
    config = ConvergenceRunConfig(
        window=timedelta(minutes=convergence_window_minutes),
        unknown_independence_weight=Decimal("0.75"),
        q_value_threshold=Decimal(q_value_threshold),
        min_observations=min_observations,
        strong_surprisal_threshold=Decimal(strong_surprisal_threshold),
    )

    async def _run() -> int:
        _config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            git_commit = resolve_production_git_commit(allow_unverified=True)
            async with sessionmaker() as session, session.begin():
                result = await compute_and_persist_phase8(
                    session,
                    cutoff=as_of_dt,
                    graph_config=graph_config,
                    config=config,
                    computed_at=datetime.now(UTC),
                )

                token_mints: dict[str, str] = {}
                token_ids = {c.episode.token_id for c in result.convergence_events}
                if token_ids:
                    rows = (
                        (await session.execute(select(Token).where(Token.token_id.in_(token_ids))))
                        .scalars()
                        .all()
                    )
                    token_mints = {str(r.token_id): r.mint for r in rows}

                sorted_events = sorted(
                    result.convergence_events, key=lambda c: c.surprisal, reverse=True
                )[:top_n]

                report = {
                    "as_of": result.as_of.isoformat(),
                    "algorithm_version": "convergence_negative_evidence_v1",
                    "config_hash": config.config_hash(),
                    "graph_config_hash": graph_config.config_hash(),
                    "build_hash": BUILD_HASH,
                    "git_commit": git_commit,
                    "convergence_episode_count": len(result.convergence_events),
                    "top_convergence_events": [
                        {
                            "token_mint": token_mints.get(
                                str(c.episode.token_id), str(c.episode.token_id)
                            ),
                            "window_start": c.episode.window_start.isoformat(),
                            "window_end": c.episode.window_end.isoformat(),
                            "raw_wallet_count": c.episode.raw_wallet_count,
                            "estimated_independent_actors": str(c.estimated_independent_actors),
                            "expected_overlap": str(c.row.expected_overlap),
                            "empirical_probability": str(c.row.empirical_probability),
                            "surprisal": str(c.surprisal),
                            "sample_size": c.row.sample_size,
                            "calibration_confidence": c.calibration_confidence,
                        }
                        for c in sorted_events
                    ],
                    "expected_confirmation_total": result.expected_confirmation_total,
                    "expected_confirmation_outcome_counts": (
                        result.expected_confirmation_outcome_counts
                    ),
                    "limitations": [
                        "purely observational/correlational -- never a causal claim "
                        "(MASTER_SPEC section 7's own explicit rule)",
                        "no 0-100 convergence score is ever produced -- section 59's own "
                        "explicit prohibition until calibration is defined; "
                        "calibration_confidence is a disclosed sample-size bucket instead",
                        "effective independent-actor count uses only each wallet's single "
                        "strongest pairwise cluster link (Phase 3's own scope limit), not a "
                        "transitive clique closure -- can undercount a group of 3+ mutually "
                        "linked wallets with no one dominant pairwise link",
                        "whether ABSENT/EARLY/LATE/STRONG confirmation outcomes predict "
                        "worse or better forward outcomes is not tested in this build "
                        "(section 60's own 'do not assume it does') -- see "
                        "docs/DECISION_LOG.md",
                    ],
                }
        finally:
            await engine.dispose()

        console.print(json.dumps(report, indent=2, default=str))
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@counterfactual_app.command("report")
def counterfactual_report(
    as_of: str | None = typer.Option(
        None, "--as-of", help="ISO-8601 cutoff (default: now). Point-in-time honest."
    ),
    horizon_minutes: list[int] | None = typer.Option(  # noqa: B008 - required Typer CLI-option idiom
        None,
        "--horizon-minutes",
        help="Forward-return horizons in minutes (default: 5/15/30/60/360/1440).",
    ),
    max_lag_minutes: int = typer.Option(
        60, "--max-lag-minutes", help="Same Phase 7/8 leader-to-follower lag window."
    ),
    top_n: int = typer.Option(
        20, "--top-n", help="Number of top residual_selection_alpha estimates to print."
    ),
) -> None:
    """Print top counterfactual-alpha estimates and specialist/predation/
    exit-convergence summaries (MASTER_SPEC.md Phase 9) -- purely
    observational statistics, never a causal claim; matching uses only
    market-cap bucket, liquidity bucket, token-age bucket, and launch
    venue in this build (see the ``limitations`` field)."""
    import json
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from sqlalchemy import select

    from argus.config import resolve_production_git_commit
    from argus.convergence.service import ConvergenceRunConfig as Phase8RunConfig
    from argus.counterfactual.service import (
        BUILD_HASH,
        Phase9RunConfig,
        compute_and_persist_phase9,
    )
    from argus.domain.tokens import Token
    from argus.domain.wallet_predation_scores import WalletPredationScore
    from argus.domain.wallet_specialist_scores import WalletSpecialistScore
    from argus.domain.wallets import Wallet
    from argus.graph.service import GraphRunConfig

    resolved_horizon_minutes = horizon_minutes or [5, 15, 30, 60, 360, 1440]
    as_of_dt = datetime.fromisoformat(as_of) if as_of else datetime.now(UTC)
    graph_config = GraphRunConfig(
        max_lag=timedelta(minutes=max_lag_minutes),
        min_observations=3,
        q_value_threshold=Decimal("0.05"),
    )
    phase8_config = Phase8RunConfig(
        window=timedelta(minutes=30),
        unknown_independence_weight=Decimal("0.75"),
        q_value_threshold=Decimal("0.05"),
        min_observations=3,
        strong_surprisal_threshold=Decimal("3.0"),
    )
    config = Phase9RunConfig(
        horizons=tuple(timedelta(minutes=m) for m in resolved_horizon_minutes),
        max_price_staleness=timedelta(minutes=30),
        max_control_tokens=50,
        entry_specialist_horizon=timedelta(minutes=resolved_horizon_minutes[0]),
        discovery_min_observations=3,
        discovery_q_value_threshold=Decimal("0.05"),
        follower_influx_window=timedelta(minutes=max_lag_minutes),
        exit_after_influx_window=timedelta(minutes=max_lag_minutes),
        predation_influx_normalization_cap=Decimal(10),
        exit_convergence_window=timedelta(minutes=30),
        exit_convergence_unknown_independence_weight=Decimal("0.75"),
        min_exit_specialist_score=Decimal(70),
    )

    async def _run() -> int:
        _config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            git_commit = resolve_production_git_commit(allow_unverified=True)
            async with sessionmaker() as session, session.begin():
                result = await compute_and_persist_phase9(
                    session,
                    cutoff=as_of_dt,
                    graph_config=graph_config,
                    phase8_config=phase8_config,
                    config=config,
                    computed_at=datetime.now(UTC),
                )

                from argus.domain.counterfactual_alpha_estimates import (
                    CounterfactualAlphaEstimate,
                )

                top_estimates = (
                    (
                        await session.execute(
                            select(CounterfactualAlphaEstimate)
                            .where(
                                CounterfactualAlphaEstimate.as_of == as_of_dt,
                                CounterfactualAlphaEstimate.algorithm_version
                                == "counterfactual_alpha_specialists_v1",
                                CounterfactualAlphaEstimate.config_hash == config.config_hash(),
                                CounterfactualAlphaEstimate.residual_selection_alpha.is_not(None),
                            )
                            .order_by(CounterfactualAlphaEstimate.residual_selection_alpha.desc())
                            .limit(top_n)
                        )
                    )
                    .scalars()
                    .all()
                )

                specialist_rows = (
                    (
                        await session.execute(
                            select(WalletSpecialistScore).where(
                                WalletSpecialistScore.as_of == as_of_dt,
                                WalletSpecialistScore.algorithm_version
                                == "counterfactual_alpha_specialists_v1",
                                WalletSpecialistScore.config_hash == config.config_hash(),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                predation_rows = (
                    (
                        await session.execute(
                            select(WalletPredationScore).where(
                                WalletPredationScore.as_of == as_of_dt,
                                WalletPredationScore.algorithm_version
                                == "counterfactual_alpha_specialists_v1",
                                WalletPredationScore.config_hash == config.config_hash(),
                                WalletPredationScore.predation_score.is_not(None),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

                wallet_ids = (
                    {e.wallet_id for e in top_estimates}
                    | {r.wallet_id for r in specialist_rows}
                    | {r.wallet_id for r in predation_rows}
                )
                token_ids = {e.token_id for e in top_estimates}
                wallet_addresses: dict[str, str] = {}
                token_mints: dict[str, str] = {}
                if wallet_ids:
                    rows = (
                        (
                            await session.execute(
                                select(Wallet).where(Wallet.wallet_id.in_(wallet_ids))
                            )
                        )
                        .scalars()
                        .all()
                    )
                    wallet_addresses = {str(r.wallet_id): r.wallet_address for r in rows}
                if token_ids:
                    rows = (
                        (await session.execute(select(Token).where(Token.token_id.in_(token_ids))))
                        .scalars()
                        .all()
                    )
                    token_mints = {str(r.token_id): r.mint for r in rows}

                report = {
                    "as_of": result.as_of.isoformat(),
                    "algorithm_version": "counterfactual_alpha_specialists_v1",
                    "config_hash": config.config_hash(),
                    "build_hash": BUILD_HASH,
                    "git_commit": git_commit,
                    "alpha_estimate_count": result.alpha_estimate_count,
                    "specialist_score_count": result.specialist_score_count,
                    "predation_score_count": result.predation_score_count,
                    "exit_convergence_event_count": result.exit_convergence_event_count,
                    "top_residual_selection_alpha": [
                        {
                            "wallet": wallet_addresses.get(str(e.wallet_id), str(e.wallet_id)),
                            "token_mint": token_mints.get(str(e.token_id), str(e.token_id)),
                            "horizon_seconds": e.horizon_seconds,
                            "wallet_token_forward_return": str(e.wallet_token_forward_return),
                            "matched_universe_forward_return": str(
                                e.matched_universe_forward_return
                            ),
                            "residual_selection_alpha": str(e.residual_selection_alpha),
                            "matched_control_count": e.matched_control_count,
                        }
                        for e in top_estimates
                    ],
                    "specialists": [
                        {
                            "wallet": wallet_addresses.get(str(r.wallet_id), str(r.wallet_id)),
                            "entry_specialist_score": (
                                str(r.entry_specialist_score)
                                if r.entry_specialist_score is not None
                                else None
                            ),
                            "discovery_specialist_score": (
                                str(r.discovery_specialist_score)
                                if r.discovery_specialist_score is not None
                                else None
                            ),
                            "validation_specialist_score": (
                                str(r.validation_specialist_score)
                                if r.validation_specialist_score is not None
                                else None
                            ),
                            "exit_specialist_score": (
                                str(r.exit_specialist_score)
                                if r.exit_specialist_score is not None
                                else None
                            ),
                            "dominant_specialty": r.dominant_specialty,
                        }
                        for r in specialist_rows
                    ],
                    "predation_scores": [
                        {
                            "wallet": wallet_addresses.get(str(r.wallet_id), str(r.wallet_id)),
                            "follower_influx_mean": (
                                str(r.follower_influx_mean)
                                if r.follower_influx_mean is not None
                                else None
                            ),
                            "exit_after_influx_rate": (
                                str(r.exit_after_influx_rate)
                                if r.exit_after_influx_rate is not None
                                else None
                            ),
                            "price_impact_mean": (
                                str(r.price_impact_mean)
                                if r.price_impact_mean is not None
                                else None
                            ),
                            "price_impact_incorporated": r.price_impact_incorporated,
                            "predation_score": str(r.predation_score),
                        }
                        for r in sorted(
                            predation_rows,
                            key=lambda r: r.predation_score or Decimal(0),
                            reverse=True,
                        )[:top_n]
                    ],
                    "limitations": [
                        "purely observational/correlational -- never a causal claim "
                        "(MASTER_SPEC section 7's own explicit rule)",
                        "matched-token controls use only market-cap bucket, liquidity "
                        "bucket, token-age bucket, and launch venue in this build -- "
                        "'recent momentum', 'volume', 'transaction rate', and 'broad "
                        "market regime' are not used as matching dimensions (no cheap, "
                        "non-fragile infrastructure exists yet for computing them across "
                        "a full candidate-token universe); see docs/DECISION_LOG.md",
                        "price_impact_mean in predation scoring is the followers' own "
                        "real Phase 5 executable-entry price impact where available "
                        "(FSR-07); when unavailable, price_impact_incorporated is False "
                        "and predation_score reflects influx/exit-timing/repetition only "
                        "-- never silently treated as complete",
                        "predation_score and dominant_specialty are disclosed V1 "
                        "heuristics, not calibrated probabilities (section 38's own "
                        "'V1 priors to be evaluated prospectively' precedent)",
                    ],
                }
        finally:
            await engine.dispose()

        console.print(json.dumps(report, indent=2, default=str))
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@synthetic_app.command("report")
def synthetic_report(
    as_of: str | None = typer.Option(
        None, "--as-of", help="ISO-8601 cutoff (default: now). Point-in-time honest."
    ),
    max_lag_minutes: int = typer.Option(
        60, "--max-lag-minutes", help="Same Phase 7/8/9 leader-to-follower lag window."
    ),
    max_hold_hours: int = typer.Option(
        24, "--max-hold-hours", help="Max simulated holding period before FAILURE_NO_EXIT_TRIGGER."
    ),
    cost_bps: str = typer.Option(
        "100", "--cost-bps", help="Disclosed round-trip realistic-cost haircut in basis points."
    ),
) -> None:
    """Print the five MASTER_SPEC.md Phase 10 (SYNTHETIC SUPER-WALLET)
    prospective strategy backtests -- SHADOW ONLY, no live-execution
    bearing whatsoever; never enables anything automatically (MASTER_SPEC's
    own explicit instruction)."""
    import json
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from argus.config import resolve_production_git_commit
    from argus.convergence.service import ConvergenceRunConfig as Phase8RunConfig
    from argus.counterfactual.service import Phase9RunConfig
    from argus.graph.service import GraphRunConfig
    from argus.synthetic.service import (
        BUILD_HASH,
        STRATEGY_CODES,
        STRATEGY_DESCRIPTIONS,
        Phase10RunConfig,
        compute_and_persist_phase10,
    )

    as_of_dt = datetime.fromisoformat(as_of) if as_of else datetime.now(UTC)
    graph_config = GraphRunConfig(
        max_lag=timedelta(minutes=max_lag_minutes),
        min_observations=3,
        q_value_threshold=Decimal("0.05"),
    )
    phase8_config = Phase8RunConfig(
        window=timedelta(minutes=30),
        unknown_independence_weight=Decimal("0.75"),
        q_value_threshold=Decimal("0.05"),
        min_observations=3,
        strong_surprisal_threshold=Decimal("3.0"),
    )
    phase9_config = Phase9RunConfig(
        horizons=(timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=30)),
        max_price_staleness=timedelta(minutes=30),
        max_control_tokens=50,
        entry_specialist_horizon=timedelta(minutes=5),
        discovery_min_observations=3,
        discovery_q_value_threshold=Decimal("0.05"),
        follower_influx_window=timedelta(minutes=max_lag_minutes),
        exit_after_influx_window=timedelta(minutes=max_lag_minutes),
        predation_influx_normalization_cap=Decimal(10),
        exit_convergence_window=timedelta(minutes=30),
        exit_convergence_unknown_independence_weight=Decimal("0.75"),
        min_exit_specialist_score=Decimal(70),
    )
    config = Phase10RunConfig(
        entry_exit_price_max_staleness=timedelta(minutes=30),
        cost_bps=Decimal(cost_bps),
        max_concurrent_positions=10,
        high_convergence_surprisal_threshold=Decimal("3.0"),
        min_exit_specialist_score=Decimal(70),
        max_hold_duration=timedelta(hours=max_hold_hours),
    )

    async def _run() -> int:
        _config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            git_commit = resolve_production_git_commit(allow_unverified=True)
            async with sessionmaker() as session, session.begin():
                result = await compute_and_persist_phase10(
                    session,
                    cutoff=as_of_dt,
                    graph_config=graph_config,
                    phase8_config=phase8_config,
                    phase9_config=phase9_config,
                    config=config,
                    computed_at=datetime.now(UTC),
                )

                report = {
                    "as_of": result.as_of.isoformat(),
                    "algorithm_version": "synthetic_super_wallet_v1",
                    "config_hash": config.config_hash(),
                    "build_hash": BUILD_HASH,
                    "git_commit": git_commit,
                    "shadow_only": True,
                    "strategies": {
                        code: {
                            "description": STRATEGY_DESCRIPTIONS[code],
                            "trade_count": result.summaries[code].trade_count,
                            "resolved_count": result.summaries[code].resolved_count,
                            "failure_count": result.summaries[code].failure_count,
                            "failure_rate": (
                                str(result.summaries[code].failure_rate)
                                if result.summaries[code].failure_rate is not None
                                else None
                            ),
                            "win_rate": (
                                str(result.summaries[code].win_rate)
                                if result.summaries[code].win_rate is not None
                                else None
                            ),
                            "profit_factor": (
                                str(result.summaries[code].profit_factor)
                                if result.summaries[code].profit_factor is not None
                                else None
                            ),
                            "max_drawdown": (
                                str(result.summaries[code].max_drawdown)
                                if result.summaries[code].max_drawdown is not None
                                else None
                            ),
                            "capital_utilization": (
                                str(result.summaries[code].capital_utilization)
                                if result.summaries[code].capital_utilization is not None
                                else None
                            ),
                            "mean_net_return": (
                                str(result.summaries[code].mean_net_return)
                                if result.summaries[code].mean_net_return is not None
                                else None
                            ),
                            "median_net_return": (
                                str(result.summaries[code].median_net_return)
                                if result.summaries[code].median_net_return is not None
                                else None
                            ),
                        }
                        for code in STRATEGY_CODES
                    },
                    "limitations": [
                        "SHADOW ONLY -- purely a backtest over already-persisted historical "
                        "evidence; no live-execution bearing whatsoever, and no strategy is "
                        "ever enabled live automatically (MASTER_SPEC section 64's own explicit "
                        "instruction)",
                        "cost_bps is a disclosed V1 placeholder haircut, not a modeled estimate "
                        "of any specific token's real liquidity/slippage",
                        "max_drawdown is computed on a simple additive, unit-normalized equity "
                        "curve (non-compounding) -- a disclosed simplification versus true "
                        "dollar-weighted portfolio compounding",
                        "capital_utilization is the mean concurrent-position count sampled at "
                        "each entry, divided by this run's own concurrency cap -- a disclosed "
                        "proxy, not an exact continuous-time integral",
                        "entry/exit prices use a nearest-snapshot-within-tolerance lookup over "
                        "token_market_snapshots -- a trade with no sufficiently fresh snapshot "
                        "is recorded as a failure, never fabricated",
                    ],
                }
        finally:
            await engine.dispose()

        console.print(json.dumps(report, indent=2, default=str))
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


@predict_app.command("report")
def predict_report(
    as_of: str | None = typer.Option(
        None, "--as-of", help="ISO-8601 cutoff (default: now). Point-in-time honest."
    ),
    max_lag_minutes: int = typer.Option(
        60, "--max-lag-minutes", help="Same Phase 7/8/9 leader-to-follower lag window."
    ),
    train_fraction: str = typer.Option(
        "0.7", "--train-fraction", help="Chronological train-split fraction (strictly (0, 1))."
    ),
    min_class_count: int = typer.Option(
        20,
        "--min-class-count",
        help="Minimum positives AND negatives required in BOTH the train and test split.",
    ),
) -> None:
    """Print the MASTER_SPEC.md Phase 11 (PREDICT INFORMED ORDER FLOW)
    per-(horizon, model family) evaluation report -- P(elite wallet enters
    within 5m/15m/30m/1h), 4 baselines + 3 models, strict temporal (never
    random) validation. A combination without adequate clean prospective
    sample is reported honestly as INSUFFICIENT_SAMPLE with every metric
    null, never a number trained on too little data."""
    import json
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from argus.config import resolve_production_git_commit
    from argus.convergence.service import ConvergenceRunConfig as Phase8RunConfig
    from argus.counterfactual.service import Phase9RunConfig
    from argus.domain.order_flow_prediction_runs import MODEL_FAMILIES
    from argus.graph.service import GraphRunConfig
    from argus.prediction.service import (
        ALGORITHM_VERSION,
        BUILD_HASH,
        Phase11RunConfig,
        compute_and_persist_phase11,
    )

    as_of_dt = datetime.fromisoformat(as_of) if as_of else datetime.now(UTC)
    graph_config = GraphRunConfig(
        max_lag=timedelta(minutes=max_lag_minutes),
        min_observations=3,
        q_value_threshold=Decimal("0.05"),
    )
    phase8_config = Phase8RunConfig(
        window=timedelta(minutes=30),
        unknown_independence_weight=Decimal("0.75"),
        q_value_threshold=Decimal("0.05"),
        min_observations=3,
        strong_surprisal_threshold=Decimal("3.0"),
    )
    phase9_config = Phase9RunConfig(
        horizons=(timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=30)),
        max_price_staleness=timedelta(minutes=30),
        max_control_tokens=50,
        entry_specialist_horizon=timedelta(minutes=5),
        discovery_min_observations=3,
        discovery_q_value_threshold=Decimal("0.05"),
        follower_influx_window=timedelta(minutes=max_lag_minutes),
        exit_after_influx_window=timedelta(minutes=max_lag_minutes),
        predation_influx_normalization_cap=Decimal(10),
        exit_convergence_window=timedelta(minutes=30),
        exit_convergence_unknown_independence_weight=Decimal("0.75"),
        min_exit_specialist_score=Decimal(70),
    )
    config = Phase11RunConfig(
        horizons=(
            timedelta(minutes=5),
            timedelta(minutes=15),
            timedelta(minutes=30),
            timedelta(hours=1),
        ),
        train_fraction=Decimal(train_fraction),
        min_class_count=min_class_count,
        max_price_staleness=timedelta(minutes=30),
        token_momentum_window=timedelta(hours=1),
        classification_threshold=Decimal("0.5"),
    )

    async def _run() -> int:
        _config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            git_commit = resolve_production_git_commit(allow_unverified=True)
            async with sessionmaker() as session, session.begin():
                result = await compute_and_persist_phase11(
                    session,
                    cutoff=as_of_dt,
                    graph_config=graph_config,
                    phase8_config=phase8_config,
                    phase9_config=phase9_config,
                    config=config,
                    computed_at=datetime.now(UTC),
                )

                from sqlalchemy import select

                from argus.domain.order_flow_prediction_runs import OrderFlowPredictionRun

                rows = (
                    (
                        await session.execute(
                            select(OrderFlowPredictionRun).where(
                                OrderFlowPredictionRun.as_of == as_of_dt,
                                OrderFlowPredictionRun.algorithm_version == ALGORITHM_VERSION,
                                OrderFlowPredictionRun.config_hash == config.config_hash(),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                rows_by_key = {(r.horizon_seconds, r.model_family): r for r in rows}

                report = {
                    "as_of": result.as_of.isoformat(),
                    "algorithm_version": ALGORITHM_VERSION,
                    "config_hash": config.config_hash(),
                    "build_hash": BUILD_HASH,
                    "git_commit": git_commit,
                    "run_count": result.run_count,
                    "evaluated_count": result.evaluated_count,
                    "insufficient_sample_count": result.insufficient_sample_count,
                    "horizons": {
                        str(int(horizon.total_seconds())): {
                            model_family: (
                                {
                                    "status": row.status,
                                    "train_sample_size": row.train_sample_size,
                                    "test_sample_size": row.test_sample_size,
                                    "positive_rate_train": (
                                        str(row.positive_rate_train)
                                        if row.positive_rate_train is not None
                                        else None
                                    ),
                                    "positive_rate_test": (
                                        str(row.positive_rate_test)
                                        if row.positive_rate_test is not None
                                        else None
                                    ),
                                    "auc_roc": str(row.auc_roc)
                                    if row.auc_roc is not None
                                    else None,
                                    "log_loss": (
                                        str(row.log_loss) if row.log_loss is not None else None
                                    ),
                                    "brier_score": (
                                        str(row.brier_score)
                                        if row.brier_score is not None
                                        else None
                                    ),
                                    "accuracy_at_threshold": (
                                        str(row.accuracy_at_threshold)
                                        if row.accuracy_at_threshold is not None
                                        else None
                                    ),
                                    "feature_set": row.feature_set,
                                }
                                if (
                                    row := rows_by_key.get(
                                        (int(horizon.total_seconds()), model_family)
                                    )
                                )
                                is not None
                                else None
                            )
                            for model_family in MODEL_FAMILIES
                        }
                        for horizon in config.horizons
                    },
                    "limitations": [
                        "a horizon x model-family combination without adequate clean prospective "
                        "sample (fewer than --min-class-count positives OR negatives in either "
                        "split) is reported as INSUFFICIENT_SAMPLE with every metric null, never "
                        "a number trained on too little or single-class data",
                        "the discovery-specialist graph feature is Phase 9's own "
                        "discovery_specialist_score computed ONCE at this run's overall cutoff, "
                        "reused for every observation regardless of its individual entered_at -- "
                        "a disclosed scope simplification, consistent with how Phase 10 reused "
                        "Phase 9's own output",
                        "token momentum is a single backward-looking window (--token-momentum "
                        "fixed at 1 hour before entry) over token_market_snapshots, not a richer "
                        "multi-window momentum feature",
                        "'random/base rate' is the deterministic training-split positive rate "
                        "predicted for every test row, not a literal random coin flip -- CORE-004 "
                        "replay of an identical run must always reproduce an identical score",
                        "never a neural network at this stage (MASTER_SPEC's own explicit "
                        "instruction: 'Do not build a neural network until simpler models are "
                        "convincingly beaten out of sample')",
                    ],
                }
        finally:
            await engine.dispose()

        console.print(json.dumps(report, indent=2, default=str))
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


if __name__ == "__main__":
    app()
