#!/usr/bin/env bash
# Back up Postgres + Parquet data + configuration metadata (MASTER_SPEC.md
# section 97). Never touches signing-key material — there is none in this
# repository or in the Postgres container to begin with (section 71).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="runtime/state/backups/${TIMESTAMP}"
mkdir -p "$OUT_DIR"

DB_NAME="${ARGUS_DB_NAME:-argus}"
DB_ADMIN_USER="${ARGUS_DB_ADMIN_USER:-argus_admin}"

echo "==> dumping Postgres (${DB_NAME})"
docker compose exec -T postgres pg_dump -U "$DB_ADMIN_USER" -d "$DB_NAME" --format=custom \
  > "${OUT_DIR}/postgres_${DB_NAME}.dump"

if [ -d data/parquet ] && [ -n "$(ls -A data/parquet 2>/dev/null)" ]; then
  echo "==> archiving Parquet data"
  tar -czf "${OUT_DIR}/parquet.tar.gz" -C data parquet
fi

echo "==> archiving configuration metadata"
tar -czf "${OUT_DIR}/config.tar.gz" config MASTER_SPEC.md docs/BUILD_STATE.md docs/DECISION_LOG.md

echo "==> backup complete: ${OUT_DIR}"
echo "Restore: docker compose exec -T postgres pg_restore -U \$ARGUS_DB_ADMIN_USER -d \$ARGUS_DB_NAME --clean < ${OUT_DIR}/postgres_${DB_NAME}.dump"
