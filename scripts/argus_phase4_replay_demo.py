#!/usr/bin/env python3
"""Phase 4 REPLAY lifecycle demonstration (orchestrator instructions
argus-phase-4-001, "Phase 4 acceptance and evidence", and
argus-phase-4-remediation-001 finding P4-R7).

REPLAY -- NOT PROSPECTIVE ALPHA EVIDENCE.

Demonstrates, through the exact same production service functions the
real `argus prospective run` / `argus shadow run-entry-probes` /
`argus shadow run-reverse-probes` / `argus shadow run-mark-outcomes` /
`argus report daily` CLI commands call internally, the complete Phase 4
lifecycle:

    leader executes -> ARGUS observes -> source tx confirms ->
    shadow signal -> entry quote -> shadow fill -> mark outcome ->
    reverse executable quote

against real Postgres, then a fake-transport Telegram notification and a
real `argus report daily` build.

Two distinct evidence classes are used, and are never conflated:

1. **Real evidence** -- "leader executes" is grounded in a genuine,
   independently-verified mainnet pump.fun buy transaction
   (`tests/golden/fixtures/real/real_mainnet_sol_to_token_swap.json`,
   slot 290506981, signer `EfbbhahGNuhqEraRZXrwETfsaKxScngEttdQixWAW4WE`,
   provenance in `tests/golden/fixtures/real/PROVENANCE.md`), parsed by
   the real, unmodified `argus.parsing.generic_parser.parse_transaction`
   -- never a hand-fabricated Swap row. "ARGUS observes" / "source tx
   confirms" persist that genuine parser output as real
   `chain_events`/`commitment_observations`/`swaps` rows via the same ORM
   models the real reconciliation engine writes.
2. **REPLAY / synthetic evidence** -- this sandbox has no live network
   access to Jupiter/DexScreener and no paid provider credentials, so the
   entry/reverse quote responses and mark-price snapshots below are
   deterministic, injected fakes (never a live network call), exactly as
   the frozen acceptance table requires ("Use controlled clocks and
   deterministic providers; replayed quotes must never be presented as
   actual historical executable opportunity or prospective samples").
   The CLI's real `shadow run-*` commands hardwire the real
   `JupiterClient`/`DexScreenerClient` HTTP adapters with no override
   flag (correct for production use); this script instead calls the same
   underlying `argus.shadow.*` service functions those commands call,
   substituting a deterministic provider at the exact same dependency-
   injection seam the CLI uses -- i.e. normal production wiring, not a
   parallel reimplementation.

P4-R7 remediation (isolation): an earlier version of this script ran
against the shared configured (dev) database and cleaned up afterward by
looking up its own fixture wallet's address and deleting every row it
found -- if the wallet-insert step ever failed because that exact address
already existed for an unrelated reason, the `finally` block would delete
that PRE-EXISTING row and its entire history. Global due-probe/due-mark
scans also had no way to avoid claiming another wallet's queued work. This
version instead follows the SAME disposable-scratch-database pattern
`tests/integration/test_migrations.py` uses: it creates a brand-new,
uniquely-named Postgres database, points `ARGUS_DB_NAME` at it for the
duration (so every connection this process ever makes -- including due-
probe/due-mark scans -- is scoped to that database and structurally
cannot see or touch any other wallet's data), runs migrations against it,
runs the demo, and unconditionally `DROP DATABASE`s it at the end --
never an address-keyed `DELETE` against shared state. A defense-in-depth
guard (`refuse_unless_scratch_database`) additionally refuses to proceed
if the resolved database name doesn't match this script's own scratch-name
prefix, checked before any write and before any network-shaped call.

After capturing full evidence (printed here and saved to
`orchestration/phase_4_remediation_1/evidence/replay_demo_results.json`),
the scratch database is dropped. The JSON snapshot and this script's
captured stdout are the durable evidence -- the original Phase 4
evidence at `orchestration/phase_4/evidence/replay_demo_results.json`
(produced by the pre-remediation, shared-database version of this script)
is left byte-for-byte unmodified as immutable history; it documents the
same lifecycle correctly, just via a script version this remediation
replaces for future runs.

Run with: ``uv run python scripts/argus_phase4_replay_demo.py``
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from argus.clock import Clock  # noqa: E402
from argus.config import load_config  # noqa: E402
from argus.db.connection import connection_for_admin, connection_for_role  # noqa: E402
from argus.db.roles import DbRole  # noqa: E402
from argus.domain.chain_events import ChainEvent  # noqa: E402
from argus.domain.commitment import COMMITMENT_CONFIRMED, CommitmentObservation  # noqa: E402
from argus.domain.shadow_positions import ShadowPosition  # noqa: E402
from argus.domain.swaps import Swap  # noqa: E402
from argus.domain.wallet_score_snapshots import WalletScoreSnapshot  # noqa: E402
from argus.domain.wallet_tier_history import WalletTierTransition  # noqa: E402
from argus.domain.wallets import Wallet  # noqa: E402
from argus.parsing.generic_parser import parse_transaction  # noqa: E402
from argus.providers.models import ExecutableQuote, TokenSnapshot  # noqa: E402
from argus.reports.daily import build_daily_report  # noqa: E402
from argus.shadow.errors import NoRouteError  # noqa: E402
from argus.shadow.intents import entry_probe_label  # noqa: E402
from argus.shadow.mark_jobs import run_due_mark_outcomes  # noqa: E402
from argus.shadow.monitor import run_prospective_monitoring_pass  # noqa: E402
from argus.shadow.quote_jobs import run_due_entry_probes, run_due_reverse_probes  # noqa: E402
from argus.telegram.notifier import FakeTelegramTransport, TelegramNotifier  # noqa: E402

REAL_FIXTURE = (
    REPO_ROOT / "tests" / "golden" / "fixtures" / "real" / "real_mainnet_sol_to_token_swap.json"
)
EVIDENCE_DIR = REPO_ROOT / "orchestration" / "phase_4_remediation_2" / "evidence"
RESULTS_PATH = EVIDENCE_DIR / "replay_demo_results.json"

_LEADER_TIME = datetime(2024, 9, 18, 9, 22, 18, tzinfo=UTC)  # the fixture's real blockTime
_TEST_GIT_COMMIT = "REPLAY4DEMO_DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF"

SCRATCH_DATABASE_PREFIX = "argus_phase4_replay_demo_"


class UnsafeReplayDatabaseTargetError(RuntimeError):
    """Raised if this script ever resolves a database name that is not its
    own disposable scratch database -- a fail-closed guard against ever
    running the demo's writes/scans against the shared configured
    database, per P4-R7's explicit isolation requirement."""


def refuse_unless_scratch_database(database_name: str) -> None:
    if not database_name.startswith(SCRATCH_DATABASE_PREFIX):
        raise UnsafeReplayDatabaseTargetError(
            f"refusing to run the Phase 4 REPLAY demo against database "
            f"{database_name!r} -- it does not match this script's own "
            f"scratch-database prefix {SCRATCH_DATABASE_PREFIX!r}. This "
            f"demo must only ever run against a disposable database it "
            f"created itself, never the shared configured database."
        )


def _new_scratch_database_name() -> str:
    return f"{SCRATCH_DATABASE_PREFIX}{uuid.uuid4().hex[:16]}"


def _alembic_config() -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return cfg


async def _maintenance_execute(sql: str) -> None:
    """Runs one autocommit DDL statement (CREATE/DROP DATABASE, which
    Postgres refuses inside a transaction block) against the maintenance
    ``postgres`` database, using the same admin credentials every other
    migration/DDL operation in this repo uses -- same pattern as
    ``tests/integration/test_migrations.py``'s ``scratch_database``
    fixture."""
    admin = connection_for_admin(load_config())
    maintenance = dataclasses.replace(admin, database="postgres")
    engine = create_async_engine(maintenance.as_asyncpg_url(), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


@dataclass
class QueuedExecutionProvider:
    queue: list[ExecutableQuote | Exception] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def get_quote(
        self, *, input_mint: str, output_mint: str, amount_raw: int, slippage_bps: int = 50
    ) -> ExecutableQuote:
        self.calls.append(
            {"input_mint": input_mint, "output_mint": output_mint, "amount_raw": amount_raw}
        )
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def build_unsigned_order(self, *, quote, wallet_address):
        raise NotImplementedError("REPLAY demonstration: no order-build/sign path exists")


@dataclass
class QueuedMarketDataProvider:
    queue: list[TokenSnapshot | Exception] = field(default_factory=list)

    async def token_snapshot(self, mint: str) -> TokenSnapshot:
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def historical_ohlcv(self, mint: str, *, start, end):
        raise NotImplementedError


class _ScriptedClock(Clock):
    """Returns pre-scripted wall-clock values -- used only to prove the
    'quote actual latency recorded, never a false target value' gate with
    a controlled +2.7s response to a nominal +1s target probe."""

    def __init__(self, times: list[datetime]) -> None:
        super().__init__()
        self._times = iter(times)

    def utc_now(self) -> datetime:
        return next(self._times)


def _quote(
    *, input_mint: str, output_mint: str, in_amount: int, out_amount: int
) -> ExecutableQuote:
    return ExecutableQuote(
        provider="jupiter-fake-replay",
        input_mint=input_mint,
        output_mint=output_mint,
        in_amount_raw=in_amount,
        out_amount_raw=out_amount,
        raw={
            "inputMint": input_mint,
            "outputMint": output_mint,
            "priceImpactPct": "0.01",
            "inAmount": str(in_amount),
            "outAmount": str(out_amount),
            "routePlan": [{"swapInfo": {"label": "fake-amm-replay"}, "percent": 100}],
        },
    )


async def _run_replay_lifecycle(sessionmaker, config) -> dict[str, Any]:
    """The full leader-executes -> ... -> daily-report lifecycle, against
    whatever database ``sessionmaker`` is already bound to. Callers are
    responsible for ensuring that database is a disposable scratch
    database (see ``main()``)."""
    events: dict[str, Any] = {}
    events["replay_label"] = "REPLAY -- NOT PROSPECTIVE ALPHA EVIDENCE"
    events["real_fixture"] = str(REAL_FIXTURE.relative_to(REPO_ROOT))

    # -----------------------------------------------------------
    # Step 1-3: leader executes -> ARGUS observes -> source tx
    # confirms. Grounded in a real, independently-verified mainnet
    # transaction and the real, unmodified production parser.
    # -----------------------------------------------------------
    raw = json.loads(REAL_FIXTURE.read_text())
    leader_wallet = raw["transaction"]["message"]["accountKeys"][0]
    parsed = parse_transaction(
        raw, wallet_address=leader_wallet, slot=raw["slot"], block_time=_LEADER_TIME
    )
    assert parsed.classification == "SWAP_SIMPLE"
    assert parsed.is_copy_eligible is True
    events["leader_executes"] = {
        "wallet_address": leader_wallet,
        "slot": parsed.slot,
        "classification": parsed.classification,
        "confidence": str(parsed.confidence),
        "input_mint": parsed.input_mint,
        "input_amount_raw": parsed.input_amount_raw,
        "output_mint": parsed.output_mint,
        "output_amount_raw": parsed.output_amount_raw,
        "parser_version": parsed.parser_version,
    }

    wallet_id = uuid.uuid4()
    async with sessionmaker() as session, session.begin():
        session.add(
            Wallet(
                wallet_id=wallet_id,
                wallet_address=leader_wallet,
                first_discovered_at=_LEADER_TIME,
                current_tier="A",
                created_at=_LEADER_TIME,
            )
        )
        await session.flush()
        score_id = uuid.uuid4()
        session.add(
            WalletScoreSnapshot(
                score_id=score_id,
                wallet_id=wallet_id,
                as_of=_LEADER_TIME,
                score_version="replay-demo-v1",
                descriptive_score=Decimal("90.000"),
                qualification_score=Decimal("90.000"),
                component_values={},
                penalties={},
                confidence="HIGH",
                excluded_discovery_token_ids=[],
                eligible_for_qualification=True,
                sample_gate_reason="phase_4_replay_demo",
                build_hash="replay-demo-build",
                config_hash="replay-demo-config",
                master_spec_hash="replay-demo-spec",
                git_commit=_TEST_GIT_COMMIT,
                created_at=_LEADER_TIME,
            )
        )
        # P4-R1: wallet_tier_snapshot is resolved from real
        # WalletTierTransition history as-of first_seen_at.
        session.add(
            WalletTierTransition(
                transition_id=uuid.uuid4(),
                wallet_id=wallet_id,
                source_score_id=score_id,
                from_tier=None,
                to_tier="A",
                reason="replay-demo",
                transitioned_at=_LEADER_TIME,
                created_at=_LEADER_TIME,
            )
        )
        event_id = uuid.uuid4()
        observed_at = _LEADER_TIME + timedelta(seconds=1)  # ARGUS observes
        session.add(
            ChainEvent(
                event_id=event_id,
                chain="solana",
                slot=parsed.slot,
                block_time=_LEADER_TIME,
                first_seen_at=observed_at,
                provider="replay-demo",
                provider_received_at=observed_at,
                transaction_signature=(
                    "4U8kypMuCUCkR6teu2Vn8ujaEJUR3dcUU5QExZxSMMeJ5fRTvYfWs5M5AB9yNjjHKAQ4w433QVyUivc3Pp8gvG1R"
                ),
                event_type="TRANSACTION_OBSERVED",
                wallet_address=leader_wallet,
                raw_payload={},
                payload_hash="replay-demo-hash",
                parser_version=parsed.parser_version,
                created_at=observed_at,
            )
        )
        await session.flush()
        confirmed_at = observed_at + timedelta(seconds=2)  # source tx confirms
        session.add(
            CommitmentObservation(
                observation_id=uuid.uuid4(),
                event_id=event_id,
                commitment_level=COMMITMENT_CONFIRMED,
                transaction_succeeded=True,
                observed_at=confirmed_at,
                provider="replay-demo",
                provider_received_at=confirmed_at,
                created_at=confirmed_at,
            )
        )
        session.add(
            Swap(
                swap_id=uuid.uuid4(),
                event_id=event_id,
                wallet_address=leader_wallet,
                classification=parsed.classification,
                input_mint=parsed.input_mint,
                input_amount_raw=parsed.input_amount_raw,
                input_amount_ui=parsed.input_amount_ui,
                output_mint=parsed.output_mint,
                output_amount_raw=parsed.output_amount_raw,
                output_amount_ui=parsed.output_amount_ui,
                network_fee_raw=parsed.network_fee_raw,
                slot=parsed.slot,
                block_time=_LEADER_TIME,
                first_seen_at=observed_at,
                confidence=parsed.confidence,
                parser_version=parsed.parser_version,
                build_hash="replay-demo-build",
                created_at=observed_at,
            )
        )
    events["argus_observes"] = {"first_seen_at": observed_at.isoformat()}
    events["source_tx_confirms"] = {
        "commitment_level": COMMITMENT_CONFIRMED,
        "observed_at": confirmed_at.isoformat(),
    }

    # -----------------------------------------------------------
    # Step 4: shadow signal (prospective event + shadow intent with
    # its 6 scheduled entry-delay probes).
    # -----------------------------------------------------------
    signal_now = confirmed_at + timedelta(seconds=1)
    pass_result = await run_prospective_monitoring_pass(sessionmaker, config=config, now=signal_now)
    assert len(pass_result.prospective_events) == 1
    assert len(pass_result.shadow_intents) == 1
    prospective_event = pass_result.prospective_events[0]
    intent = pass_result.shadow_intents[0]
    events["shadow_signal"] = {
        "prospective_event_id": str(prospective_event.prospective_event_id),
        "first_seen_at": prospective_event.first_seen_at.isoformat(),
        "shadow_intent_id": str(intent.shadow_intent_id),
        "notional_input_amount_raw": intent.notional_input_amount_raw,
        "entry_probe_labels": [entry_probe_label(s) for s in (1, 5, 15, 30, 60, 300)],
    }

    # -----------------------------------------------------------
    # Step 5-6: entry quote -> shadow fill. Deterministic clock
    # proves actual latency relative to the probe's fixed due time
    # (event.first_seen_at + target delay, per P4-R2) is recorded,
    # never fabricated as the nominal target.
    # -----------------------------------------------------------
    entry_due_at = observed_at + timedelta(seconds=1)  # event.first_seen_at + "1s"
    actual_requested_at = entry_due_at + timedelta(seconds=2, milliseconds=700)
    actual_responded_at = actual_requested_at + timedelta(milliseconds=100)
    entry_clock = _ScriptedClock(
        [actual_requested_at, actual_responded_at, actual_responded_at + timedelta(milliseconds=5)]
    )
    entry_provider = QueuedExecutionProvider(
        queue=[
            _quote(
                input_mint=intent.input_mint,
                output_mint=intent.output_mint,
                in_amount=intent.notional_input_amount_raw,
                out_amount=500_000,
            )
        ]
    )
    entry_market = QueuedMarketDataProvider(
        queue=[
            TokenSnapshot(
                provider="dexscreener-fake-replay",
                mint=intent.output_mint,
                price_usd=Decimal("1.00"),
                pairs_found=1,
                raw={},
            )
        ]
    )
    entry_results = await run_due_entry_probes(
        sessionmaker,
        entry_provider,
        config=config,
        clock=entry_clock,
        now=actual_requested_at + timedelta(seconds=10),
        market_provider=entry_market,
        limit=1,
    )
    assert len(entry_results) == 1
    entry_probe = entry_results[0]
    events["entry_quote_and_fill"] = {
        "probe_id": str(entry_probe.probe_id),
        "target_label": entry_probe.target_label,
        "target_due_at": entry_probe.target_due_at.isoformat(),
        "requested_at": entry_probe.requested_at.isoformat() if entry_probe.requested_at else None,
        "responded_at": entry_probe.responded_at.isoformat() if entry_probe.responded_at else None,
        "scheduling_delay_seconds": str(entry_probe.scheduling_delay_seconds),
        "latency_ms": entry_probe.latency_ms,
        "outcome": entry_probe.outcome,
    }

    async with sessionmaker() as session:
        position = (
            await session.execute(
                select(ShadowPosition).where(
                    ShadowPosition.shadow_intent_id == intent.shadow_intent_id
                )
            )
        ).scalar_one()
    events["entry_quote_and_fill"]["shadow_position_id"] = str(position.shadow_position_id)
    events["entry_quote_and_fill"]["entry_price_usd"] = str(position.entry_price_usd)

    # -----------------------------------------------------------
    # Step 7-8: mark outcome (positive) and reverse-executable quote
    # (NO_ROUTE) for the SAME position -- proves "executable return
    # distinct from mark" and "unsellable state preserved".
    # -----------------------------------------------------------
    maturity = position.opened_at + timedelta(minutes=5, seconds=1)
    mark_market = QueuedMarketDataProvider(
        queue=[
            TokenSnapshot(
                provider="dexscreener-fake-replay",
                mint=intent.output_mint,
                price_usd=Decimal("1.50"),  # +50% mark move
                pairs_found=1,
                raw={},
            )
        ]
    )
    mark_clock = _ScriptedClock([maturity])
    mark_results = await run_due_mark_outcomes(
        sessionmaker, mark_market, clock=mark_clock, now=maturity, limit=10
    )
    mark_outcome = next(
        r for r in mark_results if r.shadow_position_id == position.shadow_position_id
    )
    mark_return_pct = None
    if mark_outcome.mark_price_usd is not None and position.entry_price_usd:
        mark_return_pct = (
            (mark_outcome.mark_price_usd - position.entry_price_usd) / position.entry_price_usd
        ) * 100
    events["mark_outcome"] = {
        "shadow_mark_outcome_id": str(mark_outcome.shadow_mark_outcome_id),
        "horizon_label": mark_outcome.horizon_label,
        "outcome": mark_outcome.outcome,
        "mark_price_usd": str(mark_outcome.mark_price_usd),
        "mark_return_pct_approx": str(mark_return_pct) if mark_return_pct is not None else None,
    }

    reverse_provider = QueuedExecutionProvider(queue=[NoRouteError("no route out (replay)")])
    reverse_clock = _ScriptedClock(
        [maturity, maturity + timedelta(milliseconds=50), maturity + timedelta(milliseconds=55)]
    )
    reverse_results = await run_due_reverse_probes(
        sessionmaker, reverse_provider, config=config, clock=reverse_clock, now=maturity, limit=10
    )
    reverse_probe = next(
        r for r in reverse_results if r.shadow_position_id == position.shadow_position_id
    )
    events["reverse_executable_quote"] = {
        "shadow_quote_probe_id": str(reverse_probe.probe_id),
        "target_label": reverse_probe.target_label,
        "outcome": reverse_probe.outcome,
    }
    assert mark_outcome.outcome == "RECORDED"
    assert reverse_probe.outcome == "NO_ROUTE"
    assert events["mark_outcome"]["mark_return_pct_approx"] not in (None, "0")

    # -----------------------------------------------------------
    # Fake-transport Telegram notification.
    # -----------------------------------------------------------
    transport = FakeTelegramTransport()
    notifier = TelegramNotifier(transport, chat_id="replay-demo-chat")
    await notifier.notify(
        event_type="SHADOW_EVENT",
        text=(
            f"REPLAY demo: shadow position {position.shadow_position_id} opened, "
            f"mark +{events['mark_outcome']['mark_return_pct_approx']}%, "
            f"reverse-executable {reverse_probe.outcome}"
        ),
    )
    events["telegram_notification"] = {
        "transport": "FakeTelegramTransport",
        "sent": [{"chat_id": c, "text": t} for c, t in transport.sent],
    }

    # -----------------------------------------------------------
    # Daily report -- real, queried counts over the seeded window.
    # -----------------------------------------------------------
    report_now = maturity + timedelta(minutes=1)
    report = await build_daily_report(
        sessionmaker, now=report_now, tier_allowed=config.get("thresholds.wallet_tier_allowed")
    )
    events["daily_report"] = {
        "window_start": report.window_start.isoformat(),
        "window_end": report.window_end.isoformat(),
        "tracking": report.tracking,
        "signals": report.signals,
        "shadow": report.shadow,
        "data_quality": report.data_quality,
    }

    events["status"] = "COMPLETE"
    return events


async def main() -> int:
    scratch_name = _new_scratch_database_name()
    refuse_unless_scratch_database(scratch_name)

    fault = os.environ.get("_ARGUS_REPLAY_DEMO_FAULT_INJECT")
    if fault == "before_create_database":
        raise RuntimeError("fault injection: before_create_database")

    try:
        await _maintenance_execute(f'CREATE DATABASE "{scratch_name}"')
    except Exception as exc:  # pragma: no cover - environment-dependent
        print(f"Could not create scratch database: {exc}", file=sys.stderr)
        return 1

    previous_db_name = os.environ.get("ARGUS_DB_NAME")
    os.environ["ARGUS_DB_NAME"] = scratch_name
    engine = None
    events: dict[str, Any] = {"replay_label": "REPLAY -- NOT PROSPECTIVE ALPHA EVIDENCE"}
    exit_code = 0
    try:
        config = load_config()
        actual_db_name = config.env.get("ARGUS_DB_NAME", "argus")
        refuse_unless_scratch_database(actual_db_name)

        if fault == "before_migration":
            raise RuntimeError("fault injection: before_migration")

        # alembic's own migrations/env.py calls asyncio.run() internally,
        # which raises if invoked while this coroutine's own event loop is
        # already running -- run it on a separate thread with its own loop.
        alembic_cfg = _alembic_config()
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

        if fault == "after_migration":
            raise RuntimeError("fault injection: after_migration")

        info = connection_for_role(config, DbRole.INGEST)
        refuse_unless_scratch_database(info.database)
        engine = create_async_engine(info.as_asyncpg_url())
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

        if fault == "before_lifecycle":
            raise RuntimeError("fault injection: before_lifecycle")

        events = await _run_replay_lifecycle(sessionmaker, config)
        events["scratch_database"] = scratch_name
        return 0
    except Exception as exc:
        events["status"] = "FAILED"
        events["error"] = f"{type(exc).__name__}: {exc}"
        exit_code = 1
        raise
    finally:
        if engine is not None:
            await engine.dispose()
        if previous_db_name is None:
            os.environ.pop("ARGUS_DB_NAME", None)
        else:
            os.environ["ARGUS_DB_NAME"] = previous_db_name
        if fault != "before_create_database":
            await _maintenance_execute(f'DROP DATABASE IF EXISTS "{scratch_name}" WITH (FORCE)')
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(json.dumps(events, indent=2, default=str) + "\n")
        print(json.dumps(events, indent=2, default=str))
        print(f"\nEvidence written to {RESULTS_PATH.relative_to(REPO_ROOT)}")
        print(
            f"Scratch database {scratch_name!r} dropped -- this demo never wrote to or "
            "deleted from the shared configured database (see this script's module docstring)."
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
