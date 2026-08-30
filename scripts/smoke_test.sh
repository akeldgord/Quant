#!/usr/bin/env bash
# Minimal end-to-end smoke test: bring up Postgres, migrate, run `argus health`,
# confirm it exits 0. Intended for a fresh clone / CI sanity check.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose up -d postgres
uv run alembic upgrade head
uv run argus health
echo "==> smoke test passed"
