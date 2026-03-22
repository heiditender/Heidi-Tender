#!/bin/sh
set -eu

APP_DOMAIN="${APP_DOMAIN:?APP_DOMAIN is required}"
APP_WWW_DOMAIN="${APP_WWW_DOMAIN:-}"
APP_SERVER_NAMES="${APP_DOMAIN}"
if [ -n "${APP_WWW_DOMAIN}" ]; then
  APP_SERVER_NAMES="${APP_SERVER_NAMES} ${APP_WWW_DOMAIN}"
else
  APP_WWW_DOMAIN="__unused__"
fi
NGINX_TLS_CERT_PATH="${NGINX_TLS_CERT_PATH:-}"
NGINX_TLS_KEY_PATH="${NGINX_TLS_KEY_PATH:-}"
NGINX_TRUSTED_PROXY_FILE="${NGINX_TRUSTED_PROXY_FILE:-/etc/nginx/security/trusted-proxies.conf}"
NGINX_ORIGIN_ALLOWLIST_FILE="${NGINX_ORIGIN_ALLOWLIST_FILE:-/etc/nginx/security/origin-allowlist.conf}"
NGINX_ORIGIN_LOCKDOWN_ENABLED="${NGINX_ORIGIN_LOCKDOWN_ENABLED:-false}"
export APP_DOMAIN APP_SERVER_NAMES APP_WWW_DOMAIN
TEMPLATE_ROOT="/etc/nginx/templates/managed"
OUTPUT_PATH="/etc/nginx/conf.d/default.conf"
GENERATED_DIR="/etc/nginx/conf.d/generated"
mkdir -p "${GENERATED_DIR}"

CERT_DIR="/etc/letsencrypt/live/${APP_DOMAIN}"
FULLCHAIN_PATH="${NGINX_TLS_CERT_PATH:-${CERT_DIR}/fullchain.pem}"
PRIVKEY_PATH="${NGINX_TLS_KEY_PATH:-${CERT_DIR}/privkey.pem}"

REAL_IP_OUTPUT="${GENERATED_DIR}/real-ip.conf"
ALLOWLIST_OUTPUT="${GENERATED_DIR}/origin-allowlist.conf"

if [ -f "${NGINX_TRUSTED_PROXY_FILE}" ]; then
  cp "${NGINX_TRUSTED_PROXY_FILE}" "${REAL_IP_OUTPUT}"
else
  cat > "${REAL_IP_OUTPUT}" <<'EOF'
# No trusted reverse-proxy file provided.
EOF
fi

if [ "${NGINX_ORIGIN_LOCKDOWN_ENABLED}" = "true" ]; then
  if [ ! -f "${NGINX_ORIGIN_ALLOWLIST_FILE}" ]; then
    echo "NGINX_ORIGIN_LOCKDOWN_ENABLED=true but ${NGINX_ORIGIN_ALLOWLIST_FILE} does not exist" >&2
    exit 1
  fi
  cp "${NGINX_ORIGIN_ALLOWLIST_FILE}" "${ALLOWLIST_OUTPUT}"
else
  cat > "${ALLOWLIST_OUTPUT}" <<'EOF'
# Origin allowlist disabled.
EOF
fi

TEMPLATE_PATH="${TEMPLATE_ROOT}/app-http.conf.template"
if [ -f "${FULLCHAIN_PATH}" ] && [ -f "${PRIVKEY_PATH}" ]; then
  TEMPLATE_PATH="${TEMPLATE_ROOT}/app-https.conf.template"
fi

export NGINX_TLS_CERT_PATH="${FULLCHAIN_PATH}"
export NGINX_TLS_KEY_PATH="${PRIVKEY_PATH}"
envsubst '${APP_DOMAIN} ${APP_SERVER_NAMES} ${APP_WWW_DOMAIN} ${NGINX_TLS_CERT_PATH} ${NGINX_TLS_KEY_PATH}' < "${TEMPLATE_PATH}" > "${OUTPUT_PATH}"
