#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${PROJECT_ROOT}/data/nginx/security"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${OUT_DIR}"

curl -fsSL https://www.cloudflare.com/ips-v4 -o "${TMP_DIR}/ips-v4.txt"
curl -fsSL https://www.cloudflare.com/ips-v6 -o "${TMP_DIR}/ips-v6.txt"

{
  echo "# Generated from Cloudflare IP feeds on $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "real_ip_header CF-Connecting-IP;"
  echo "real_ip_recursive on;"
  while IFS= read -r cidr; do
    [ -n "${cidr}" ] && printf 'set_real_ip_from %s;\n' "${cidr}"
  done < "${TMP_DIR}/ips-v4.txt"
  while IFS= read -r cidr; do
    [ -n "${cidr}" ] && printf 'set_real_ip_from %s;\n' "${cidr}"
  done < "${TMP_DIR}/ips-v6.txt"
} > "${OUT_DIR}/trusted-proxies.conf"

{
  echo "# Generated from Cloudflare IP feeds on $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  while IFS= read -r cidr; do
    [ -n "${cidr}" ] && printf 'allow %s;\n' "${cidr}"
  done < "${TMP_DIR}/ips-v4.txt"
  while IFS= read -r cidr; do
    [ -n "${cidr}" ] && printf 'allow %s;\n' "${cidr}"
  done < "${TMP_DIR}/ips-v6.txt"
  echo "deny all;"
} > "${OUT_DIR}/origin-allowlist.conf"

printf 'Updated Cloudflare allowlists in %s\n' "${OUT_DIR}"
