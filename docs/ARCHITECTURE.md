# ARGUS Architecture (Phase 0 baseline)

This document describes the structural architecture actually implemented so
far. It is descriptive, not aspirational — see `MASTER_SPEC.md` for the full
target design across all phases. Where this file and `MASTER_SPEC.md`
disagree, `MASTER_SPEC.md` is authoritative.

## Shape

ARGUS is a **modular monolith**: one Python codebase (`src/argus/`), one
canonical Postgres database, deployed as a small number of Docker Compose
services that each run a different entrypoint against the same codebase.
No Kubernetes, no message broker, no microservices (MASTER_SPEC.md TECH-003).

```
compose.yaml
  └── postgres        (canonical operational database, Postgres 17)
  └── api (Phase 0+)   FastAPI admin/health service
  (later phases add: ingestion worker, shadow worker, executor process —
   each a separate container running a different `argus` CLI subcommand
   against the same image)
```

## Layers

- `src/argus/config.py` — loads YAML config (`config/*.yaml`) + `.env`,
  produces a stable `config_hash` for reproducibility (CORE-004).
- `src/argus/clock.py` — UTC wall-clock + monotonic clock abstraction;
  the single source of truth for "now" everywhere else in the codebase, so
  clock-anomaly detection (section 17) has one place to live.
- `src/argus/logging.py` — structured (JSON) logging setup.
- `src/argus/db/` — SQLAlchemy 2.x async engine/session management, one
  engine per least-privilege Postgres role (`argus_ingest`, `argus_research`,
  `argus_executor`; section 72).
- `src/argus/domain/` — ORM models / dataclasses for canonical entities
  (`provider_usage` lands here in Phase 0; the full entity list in section 27
  is built out phase by phase).
- `src/argus/providers/` — one subpackage per external data source, each
  implementing the `Protocol` interfaces described in section 10. Phase 0
  contains only package placeholders; adapters are built in Phase 1.
- `src/argus/api/` — FastAPI app exposing `/health`, `/ready`,
  `/metrics-summary`, `/webhooks/*` (section TECH-006).
- `src/argus/cli.py` — Typer entrypoint (`argus ...`), the primary way a
  human/operator drives the system (section TECH-007).
- Domain packages (`ingestion/`, `parsing/`, `tokens/`, `wallets/`,
  `clustering/`, `scoring/`, `copyability/`, `graph/`, `signals/`, `shadow/`,
  `execution/`, `risk/`, `outcomes/`, `research/`, `notifications/`) are
  currently empty package stubs reserved for their respective phases.

## Data

- **Postgres 17** is the canonical operational store: entities, point-in-time
  state, signals, scores, positions, execution history, audit records
  (TECH-004).
- **Parquet + DuckDB/Polars** (TECH-005) is reserved for large analytical
  datasets from Phase 1.5 onward; Postgres is never used as a full-chain data
  warehouse.

## Security boundary (relevant from Phase 0 onward)

- Three Postgres roles exist from the first migration: `argus_ingest`,
  `argus_research`, `argus_executor`, each with least-privilege grants
  (section 72). No table grants "ALL" to more roles than necessary.
- No signing-key material, seed phrases, or live-arm files exist anywhere in
  this repository or in Phase 0 code. `LIVE_MAX_SINGLE_TRADE_SOL`,
  `LIVE_MAX_TOTAL_EXPOSURE_SOL`, and `LIVE_MAX_DAILY_LOSS_SOL` all default to
  `0` (section 74). Nothing in Phase 0 can place a trade — there is no
  executor, no provider capable of executing, and no key.

## Why this layout

The repository contract in `MASTER_SPEC.md` section 7 is authoritative; this
file exists only to explain *why* it's shaped this way for a reader who
hasn't read the whole spec: one deployable codebase keeps phase-to-phase
changes reviewable as ordinary diffs, per-role DB grants make the "research
never touches the signing key / custody" boundary (CORE-009) enforceable at
the database layer rather than by convention alone, and the provider
`Protocol` interfaces keep domain logic from hard-coupling to any one paid or
free data vendor (section 10) — consistent with the free-first policy
(section 11).
