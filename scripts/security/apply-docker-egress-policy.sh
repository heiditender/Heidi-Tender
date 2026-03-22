#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${PROJECT_ROOT}"

NETWORK_NAME="${NETWORK_NAME:-heidi-tender-prod}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-heidi-tender-backend-prod}"
FRONTEND_CONTAINER="${FRONTEND_CONTAINER:-heidi-tender-frontend-prod}"
CHAIN_NAME="${CHAIN_NAME:-HEIDI_TENDER_EGRESS}"

internal_subnet="$(docker network inspect "${NETWORK_NAME}" --format '{{(index .IPAM.Config 0).Subnet}}')"
frontend_ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "${FRONTEND_CONTAINER}" 2>/dev/null || true)"
backend_ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "${BACKEND_CONTAINER}" 2>/dev/null || true)"

if [ -z "${internal_subnet}" ]; then
  echo "Could not resolve subnet for Docker network ${NETWORK_NAME}" >&2
  exit 1
fi

iptables -N "${CHAIN_NAME}" 2>/dev/null || true
iptables -C DOCKER-USER -j "${CHAIN_NAME}" 2>/dev/null || iptables -I DOCKER-USER 1 -j "${CHAIN_NAME}"
iptables -F "${CHAIN_NAME}"

iptables -A "${CHAIN_NAME}" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -A "${CHAIN_NAME}" -d "${internal_subnet}" -j RETURN

if [ -n "${backend_ip}" ]; then
  iptables -A "${CHAIN_NAME}" -s "${backend_ip}" -p udp --dport 53 -j RETURN
  iptables -A "${CHAIN_NAME}" -s "${backend_ip}" -p tcp --dport 53 -j RETURN
  iptables -A "${CHAIN_NAME}" -s "${backend_ip}" -p tcp --dport 443 -j RETURN
  iptables -A "${CHAIN_NAME}" -s "${backend_ip}" -j REJECT --reject-with icmp-port-unreachable
fi

if [ -n "${frontend_ip}" ]; then
  iptables -A "${CHAIN_NAME}" -s "${frontend_ip}" -j REJECT --reject-with icmp-port-unreachable
fi

iptables -A "${CHAIN_NAME}" -j RETURN

printf 'Applied egress restrictions on network %s (subnet %s)\n' "${NETWORK_NAME}" "${internal_subnet}"
