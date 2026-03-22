FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=60

WORKDIR /app

COPY src/requirements.txt /tmp/core-requirements.txt
COPY src/web/backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir --retries 10 -r /tmp/core-requirements.txt -r /tmp/backend-requirements.txt

RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin app

COPY --chown=app:app . /app

WORKDIR /app/src/web/backend
USER app
CMD ["sh", "-lc", "cd /app && alembic -c src/web/backend/alembic.ini upgrade head && cd /app/src/web/backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=\"${UVICORN_FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
