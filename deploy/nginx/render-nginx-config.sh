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
export APP_DOMAIN APP_SERVER_NAMES APP_WWW_DOMAIN
TEMPLATE_ROOT="/etc/nginx/templates/managed"
OUTPUT_PATH="/etc/nginx/conf.d/default.conf"
CERT_DIR="/etc/letsencrypt/live/${APP_DOMAIN}"
FULLCHAIN_PATH="${CERT_DIR}/fullchain.pem"
PRIVKEY_PATH="${CERT_DIR}/privkey.pem"

TEMPLATE_PATH="${TEMPLATE_ROOT}/app-http.conf.template"
if [ -f "${FULLCHAIN_PATH}" ] && [ -f "${PRIVKEY_PATH}" ]; then
  TEMPLATE_PATH="${TEMPLATE_ROOT}/app-https.conf.template"
fi

envsubst '${APP_DOMAIN} ${APP_SERVER_NAMES} ${APP_WWW_DOMAIN}' < "${TEMPLATE_PATH}" > "${OUTPUT_PATH}"
