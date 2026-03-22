#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${PROJECT_ROOT}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
out_dir="${PROJECT_ROOT}/incident-response/${timestamp}"

mkdir -p "${out_dir}"

docker ps -a > "${out_dir}/docker-ps-a.txt"
docker images --digests > "${out_dir}/docker-images-digests.txt"

for container in heidi-tender-frontend-prod heidi-tender-backend-prod heidi-tender-nginx-prod; do
  docker inspect "${container}" > "${out_dir}/${container}-inspect.json" 2>/dev/null || true
  docker logs --timestamps "${container}" > "${out_dir}/${container}.log" 2>&1 || true
done

docker exec heidi-tender-frontend-prod sh -lc '
  ps auxww
  echo
  ss -tupan || netstat -tupan || true
  echo
  ls -lah /app/src/web/frontend
  echo
  sha256sum \
    /app/src/web/frontend/scanner_linux \
    /app/src/web/frontend/xmrig.tar.gz \
    /app/src/web/frontend/xmrig-6.21.0/xmrig 2>/dev/null || true
' > "${out_dir}/frontend-runtime.txt" 2>&1 || true

docker exec heidi-tender-frontend-prod sh -lc '
  tar -C /app/src/web/frontend -cf - \
    scanner_linux \
    xmrig.tar.gz \
    xmrig-6.21.0 \
    exploited.log \
    scanner_deployed.log \
    failed.log \
    monitor.log \
    data.log 2>/dev/null
' > "${out_dir}/frontend-malware-artifacts.tar" || true

printf 'Collected runtime artifacts in %s\n' "${out_dir}"
