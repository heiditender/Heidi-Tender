#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${PROJECT_ROOT}"

install -d -m 0750 data/jobs
install -d -m 0755 data/nginx/security
install -d -m 0700 data/nginx/origin-certs
install -d -m 0750 incident-response

chown 10001:10001 data/jobs

printf 'Prepared writable/runtime directories under %s\n' "${PROJECT_ROOT}/data"
