#!/usr/bin/env bash
set -euo pipefail

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-heidi-tender-postgres-prod}"
POSTGRES_DB="${POSTGRES_DB:-suisse_bid_match}"
POSTGRES_USER="${POSTGRES_USER:-suisse}"

docker exec -i "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  -c "UPDATE user_sessions SET revoked_at = NOW() WHERE revoked_at IS NULL;"

echo "Revoked all active application sessions."
