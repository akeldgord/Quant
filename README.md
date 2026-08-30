# ARGUS

Solana wallet intelligence, copyability research, Alpha-Ancestry graph,
synthetic trader, and isolated execution engine.

**Start here:** [`MASTER_SPEC.md`](./MASTER_SPEC.md) is the single
authoritative implementation contract for this project. Every implementation
decision either comes from that file or from an explicit orchestrator
decision recorded in [`docs/DECISION_LOG.md`](./docs/DECISION_LOG.md).

Current build progress lives in [`docs/BUILD_STATE.md`](./docs/BUILD_STATE.md).

The implementation agent and the ARGUS orchestrator communicate through this
repository — see [`orchestration/PROTOCOL.md`](./orchestration/PROTOCOL.md)
for the handoff protocol, [`orchestration/ORCHESTRATOR_INSTRUCTIONS.md`](./orchestration/ORCHESTRATOR_INSTRUCTIONS.md)
for the current authorized-work instruction, and
[`orchestration/AGENT_HANDOFF.md`](./orchestration/AGENT_HANDOFF.md) for the
agent's current status.

## Status

**Phase 0 (Foundation).** No provider, ingestion, scoring, or execution code
exists yet — this is the repository/infrastructure scaffold only. Live
trading is disabled by construction: default capital limits are zero
(`config/risk.default.yaml`), there is no executor, no signing key, and no
live-arm mechanism anywhere in this repository.

## Quickstart

```bash
make bootstrap   # installs Python 3.12 via uv, syncs deps, starts Postgres, runs migrations
make up          # start Postgres + apply migrations (subsequent runs)
```

`make bootstrap` creates `.env` from `.env.example` on first run and then
stops: there is no working fallback database password anywhere in this
repository (SEC-005), so fill in `ARGUS_DB_{INGEST,RESEARCH,EXECUTOR,ADMIN}_PASSWORD`
in `.env` (any local dev values) before re-running it. A missing required
password fails immediately and clearly (`MissingCredentialError`) rather than
silently connecting with a guessed default.

```bash
make health      # argus health — Postgres/clock/config/live-readiness report
make test        # pytest with coverage
make lint        # ruff check + format --check
make typecheck   # mypy
```

`argus` is the primary CLI (Typer-based); run `uv run argus --help` for the
full command list as it grows phase by phase.

## Repository layout

See `MASTER_SPEC.md` section 7 for the authoritative repository contract.
Broadly:

- `src/argus/` — application code (modular monolith; TECH-003).
- `config/` — versioned YAML configuration (behavioral, not secrets).
- `migrations/` — Alembic migrations (schema + least-privilege DB roles).
- `docs/` — architecture, build state, decision log, and phase-driven docs.
- `tests/` — unit / integration / golden / replay / fixtures.
- `scripts/`, `Makefile` — operator tooling.
- `data/`, `runtime/` — local datasets and runtime state; gitignored.

## Safety posture

This project follows a strict phase-gated build process (`MASTER_SPEC.md`
section 103): one phase at a time, tested and checkpointed before the next
begins, with hard prohibitions on the implementation agent ever touching a
private key, initiating a mainnet trade, or relaxing a safety threshold. See
`MASTER_SPEC.md` sections 70-84 and 116 for the full execution-security model.
