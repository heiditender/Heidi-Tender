#!/bin/sh
set -eu

mkdir -p /var/www/certbot/.well-known/acme-challenge
chmod 755 /var/www/certbot /var/www/certbot/.well-known /var/www/certbot/.well-known/acme-challenge

/usr/local/bin/render-nginx-config.sh
