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
            f"shadow_intents_created={len(result.shadow_intents)}"
        )
        return 0

    raise typer.Exit(code=asyncio.run(_run()))


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
    from argus.providers.usage import SqlUsageRecorder
    from argus.shadow.quote_jobs import run_due_entry_probes

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            retry_policy = retry_policy_from_config(config)
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                usage_recorder = SqlUsageRecorder(sessionmaker)
                jupiter = JupiterClient(
                    http_client=http_client,
                    retry_policy=retry_policy,
                    usage_recorder=usage_recorder,
                )
                market = DexScreenerClient(http_client=http_client, retry_policy=retry_policy)
                results = await run_due_entry_probes(
                    sessionmaker,
                    jupiter,
                    config=config,
                    clock=Clock(),
                    now=datetime.now(UTC),
                    market_provider=market,
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
    from argus.providers.usage import SqlUsageRecorder
    from argus.shadow.quote_jobs import run_due_reverse_probes

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            retry_policy = retry_policy_from_config(config)
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
    from argus.shadow.mark_jobs import run_due_mark_outcomes

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            retry_policy = retry_policy_from_config(config)
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                market = DexScreenerClient(http_client=http_client, retry_policy=retry_policy)
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

    from argus.reports.daily import build_daily_report

    async def _run() -> int:
        config, engine, sessionmaker = _phase2_engine_and_sessionmaker()
        try:
            tier_allowed = config.get("thresholds.wallet_tier_allowed") or []
            report = await build_daily_report(
                sessionmaker, now=datetime.now(UTC), tier_allowed=tier_allowed
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


if __name__ == "__main__":
    app()
