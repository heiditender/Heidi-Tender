# Heidi Tender Security Recovery

This runbook is the production recovery path after the 2026-03-18 compromise.

## 1. Preserve evidence before cleanup

```bash
bash scripts/security/collect-runtime-artifacts.sh
```

Store the generated `incident-response/<timestamp>/` directory outside the host if possible.

## 2. Prepare the rebuilt host

```bash
cp .env.prod.example .env.prod
bash scripts/security/prepare-host-security.sh
bash scripts/security/validate-prod-env.sh
```

Before bringing up the stack, rotate every secret that was present on the compromised host:

- `AUTH_SESSION_SECRET`
- PostgreSQL user password
- MySQL root and app passwords
- `OPENAI_API_KEY`
- `AUTH_RESEND_API_KEY`
- Google / Microsoft OAuth client secrets
- SSH keys, deploy keys, registry credentials, DNS/WAF tokens
- TLS private keys and certificates

## 3. Lock the origin behind Cloudflare

Generate the Cloudflare allowlists:

```bash
bash scripts/security/update-cloudflare-nginx-allowlists.sh
```

Recommended production settings in `.env.prod`:

- `NGINX_ORIGIN_LOCKDOWN_ENABLED=true`
- `NGINX_TRUSTED_PROXY_FILE=/etc/nginx/security/trusted-proxies.conf`
- `NGINX_ORIGIN_ALLOWLIST_FILE=/etc/nginx/security/origin-allowlist.conf`
- `NGINX_TLS_CERT_PATH` and `NGINX_TLS_KEY_PATH` pointing to your origin certificate files

If you keep using Let's Encrypt HTTP-01 on the origin, leave `NGINX_ORIGIN_LOCKDOWN_ENABLED=false` until you migrate to an origin certificate or DNS-based validation.

## 4. Rebuild and deploy

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml build --no-cache frontend backend nginx
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
bash scripts/security/apply-docker-egress-policy.sh
```

## 5. Invalidate sessions

```bash
bash scripts/security/revoke-all-sessions.sh
```

Users must sign in again after the new environment is live.

## 6. Post-deploy checks

- `docker compose --env-file .env.prod -f docker-compose.prod.yml ps`
- `docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=200 frontend backend nginx`
- Confirm direct origin IP access is blocked.
- Confirm traffic via Cloudflare works.
- Confirm the frontend container cannot reach arbitrary public `80/443` destinations.
- Confirm logins, job creation, uploads, and SSE job events still work.
