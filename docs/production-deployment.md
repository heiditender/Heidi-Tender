# Heidi Tender Production Deployment

This guide deploys Heidi Tender to a single Ubuntu host with Docker Compose, MySQL, PostgreSQL, Nginx, and Let's Encrypt.

## Prerequisites

- Docker Engine and Docker Compose v2 installed on the host
- DNS A records that point both `heiditender.ch` and `www.heiditender.ch` to `135.181.149.82`
- Ports `80` and `443` reachable from the public internet
- Local copies of `src/prepare/pim.sql` and `src/prepare/upload_corpus_kb/`

`src/prepare/pim.sql` and `src/prepare/upload_corpus_kb/` are ignored by git in this repo, so make sure they exist on the target host before you start the stack.

## 1. Prepare the environment

```bash
cp .env.prod.example .env.prod
mkdir -p data/mysql data/postgres data/jobs data/letsencrypt
install -d -m 755 data/certbot data/certbot/www data/certbot/www/.well-known data/certbot/www/.well-known/acme-challenge
```

Edit `.env.prod` and set:

- `APP_DOMAIN=heiditender.ch`
- `APP_WWW_DOMAIN=www.heiditender.ch`
- `LETSENCRYPT_EMAIL` to the mailbox that should receive certificate notices
- `MYSQL_ROOT_PASSWORD`, `POSTGRES_PASSWORD`, and `DATABASE_URL`
- `OPENAI_API_KEY`
- `NEXT_PUBLIC_API_BASE=/api/v1`
- `AUTH_SESSION_SECRET` to a long random secret
- `AUTH_PUBLIC_BASE_URL=https://heiditender.ch`
- `AUTH_FRONTEND_BASE_URL=https://heiditender.ch`
- `AUTH_GOOGLE_CLIENT_ID`, `AUTH_GOOGLE_CLIENT_SECRET`
- `AUTH_MICROSOFT_CLIENT_ID`, `AUTH_MICROSOFT_CLIENT_SECRET`

Optional only if you want email magic-link login:

- `AUTH_RESEND_API_KEY`, `AUTH_MAGIC_LINK_SENDER_EMAIL`
- `AUTH_MAGIC_LINK_BASE_URL`

If you want to verify DNS before you request the certificate:

```bash
dig +short heiditender.ch
dig +short www.heiditender.ch
```

It should resolve to:

```text
135.181.149.82
```

Keep `CORE_SKIP_KB_BOOTSTRAP=false` unless you intentionally want to skip the knowledge-base upload step.

### OAuth provider setup

Register the following redirect URIs with each provider:

- Google: `https://heiditender.ch/api/v1/auth/callback/google`
- Microsoft: `https://heiditender.ch/api/v1/auth/callback/microsoft`

Keep `AUTH_GOOGLE_REDIRECT_URI` and `AUTH_MICROSOFT_REDIRECT_URI` empty unless you need to override those defaults.

If you enable magic-link emails with Resend, set:

- `AUTH_MAGIC_LINK_SENDER_EMAIL` to a verified sender
- `AUTH_MAGIC_LINK_BASE_URL=https://heiditender.ch`
- `AUTH_MAGIC_LINK_SUBJECT` if you want a custom email subject

## 2. Build and start the production stack

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml build
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

First boot uses an HTTP-only Nginx config so the site can start before a certificate exists.

## 3. Issue the first Let's Encrypt certificate

Run Certbot inside the `certbot` service after the stack is up:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T certbot \
  sh -lc 'certbot certonly --webroot -w /var/www/certbot -d "$APP_DOMAIN" -d "$APP_WWW_DOMAIN" -m "$LETSENCRYPT_EMAIL" --agree-tos --no-eff-email'
```

Then render the HTTPS Nginx config and reload Nginx:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T nginx /usr/local/bin/render-nginx-config.sh
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T nginx nginx -s reload
```

At this point:

- Frontend should be available at `https://heiditender.ch/`
- `https://www.heiditender.ch/` should redirect to `https://heiditender.ch/`
- Backend API should be available at `https://heiditender.ch/api/v1`
- Health check should be available at `https://heiditender.ch/health`
- Login page should be available at `https://heiditender.ch/login`

## 4. Install the renewal timer

Copy the example environment file and systemd units:

```bash
sudo cp deploy/systemd/heidi-tender-prod.env.example /etc/default/heidi-tender-prod
sudo cp deploy/systemd/heidi-tender-certbot-renew.service /etc/systemd/system/
sudo cp deploy/systemd/heidi-tender-certbot-renew.timer /etc/systemd/system/
```

Edit `/etc/default/heidi-tender-prod` and set `PROJECT_DIR` to the checkout path on the host. Leave `COMPOSE_ENV_FILE=.env.prod` and `COMPOSE_FILE=docker-compose.prod.yml` unless you renamed them.

Enable the timer:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now heidi-tender-certbot-renew.timer
```

Manual renewal test:

```bash
sudo systemctl start heidi-tender-certbot-renew.service
sudo systemctl status heidi-tender-certbot-renew.service --no-pager
```

## 5. Smoke test the application

- Open `https://heiditender.ch/`
- Open `https://heiditender.ch/login` and test Google, Microsoft, or magic-link login
- Confirm `https://heiditender.ch/health` returns `{"ok": true}`
- Create a job, upload a file or archive, and start the pipeline
- Confirm the job event stream updates in the UI while the run is executing
- Restart `nginx`, `frontend`, and `backend` containers and confirm existing jobs still appear

## Rollback

To stop the production stack:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml down
```

To remove containers and keep data:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml down --remove-orphans
```

Persistent state is stored under:

- `data/mysql`
- `data/postgres`
- `data/jobs`
- `data/letsencrypt`

## Troubleshooting

- If Nginx serves HTTP only after certificate issuance, rerun `render-nginx-config.sh` inside the `nginx` container and reload Nginx.
- If Certbot validation fails, confirm both `heiditender.ch` and `www.heiditender.ch` resolve to `135.181.149.82`, that port `80` is reachable from the internet, and that `data/certbot/www` is world-readable so Nginx can serve the ACME challenge files.
- If the backend fails on startup, verify both databases are healthy and that `src/prepare/pim.sql` is present on disk.
- If the first pipeline run fails in Step1, confirm `src/prepare/upload_corpus_kb/` exists or temporarily set `CORE_SKIP_KB_BOOTSTRAP=true`.
- If Google or Microsoft login fails, confirm the provider redirect URI matches the canonical host `https://heiditender.ch` exactly and that your provider secrets are present in `.env.prod`.
- If magic link email sending fails, verify `AUTH_RESEND_API_KEY`, the sender domain, and outbound internet access from the backend container.
