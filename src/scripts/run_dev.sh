#!/usr/bin/env bash
set -euo pipefail

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

docker compose up -d postgres qdrant

echo "Running DB migrations"
alembic upgrade head

echo "Starting API on http://localhost:8000"
uvicorn apps.api.main:app --reload &
API_PID=$!

sleep 2

echo "Starting Streamlit on http://localhost:8501"
streamlit run apps/ui/streamlit_app.py

kill $API_PID
