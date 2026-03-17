FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY src/requirements.txt /tmp/core-requirements.txt
COPY src/web/backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir -r /tmp/core-requirements.txt -r /tmp/backend-requirements.txt

COPY . /app

WORKDIR /app/src/web/backend
CMD ["sh", "-lc", "cd /app && alembic -c src/web/backend/alembic.ini upgrade head && cd /app/src/web/backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
