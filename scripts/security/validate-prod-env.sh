#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-${PROJECT_ROOT}/.env.prod}"

if [ ! -f "${ENV_FILE}" ]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi

set -a
. "${ENV_FILE}"
set +a

required_vars=(
  APP_DOMAIN
  LETSENCRYPT_EMAIL
  AUTH_SESSION_SECRET
  MYSQL_ROOT_PASSWORD
  PIM_MYSQL_PASSWORD
  POSTGRES_PASSWORD
  DATABASE_URL
  OPENAI_API_KEY
)

bad_patterns='^(change-me|replace-me|replace-with-a-long-random-secret)?$'

for key in "${required_vars[@]}"; do
  value="${!key:-}"
  if [ -z "${value}" ] || printf '%s' "${value}" | grep -Eq "${bad_patterns}"; then
    echo "Invalid production secret/config for ${key}" >&2
    exit 1
  fi
done

printf 'Validated required production secrets in %s\n' "${ENV_FILE}"
