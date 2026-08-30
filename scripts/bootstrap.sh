#!/usr/bin/env bash
# Fresh-clone bootstrap: install the pinned Python, sync dependencies, bring
# up Postgres, and run migrations to head. Idempotent — safe to re-run.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

echo "==> installing pinned Python toolchain"
uv python install 3.12

echo "==> syncing dependencies (uv sync)"
uv sync

if [ ! -f .env ]; then
  echo "==> creating .env from .env.example (fill in real values before Phase 1)"
  cp .env.example .env
fi

echo "==> starting Postgres"
docker compose up -d postgres

echo "==> waiting for Postgres to be healthy"
for _ in $(seq 1 30); do
  status="$(docker inspect --format='{{.State.Health.Status}}' argus_postgres 2>/dev/null || echo starting)"
  if [ "$status" = "healthy" ]; then
    break
  fi
  sleep 1
done

echo "==> running migrations"
uv run alembic upgrade head

echo "==> bootstrap complete. Try: make health"
