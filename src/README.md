# Suisse Bid Match (SIMAP-only, Stable-first)

Bidder-side copilot MVP for:
- SIMAP tender ingest/search
- Retrieval-grounded Q&A with citations
- Eligibility/checklist extraction
- Notice change impact monitoring

## Stack (current MVP)
- Backend: FastAPI
- DB: PostgreSQL (only)
- Migrations: Alembic
- Vector DB: Qdrant
- UI: Streamlit

## Scope notes
- Implemented: SIMAP connector + ingest + reindex + chat + checklist + changes
- Placeholder only: TED / Apify endpoints (`501`)
- Not in this stage: Celery / Redis / MinIO

## Quickstart (Docker Compose)

### 1) Prepare env
```bash
cp .env.example .env
```

### 2) Start all services
```bash
docker compose up -d --build
```

### 3) Verify
```bash
docker compose ps
curl http://localhost:8000/health
curl http://localhost:6333/collections
```

### 4) Seed and reindex
```bash
docker compose exec api python3 scripts/seed_demo.py
docker compose exec api python3 scripts/reindex.py
```

### 5) Open
- API docs: `http://localhost:8000/docs`
- UI: `http://localhost:8501`

## Local run (without dockerized API/UI)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# infra only
docker compose up -d postgres qdrant

# apply schema migrations
alembic upgrade head

# start app
uvicorn apps.api.main:app --reload
```

## Database and migrations
- Runtime is Postgres-only (`DB_REQUIRE_POSTGRES=true` by default).
- Schema is managed via Alembic.
- `api` container runs `alembic upgrade head` before starting uvicorn.

## Key env vars
- `DB_URL=postgresql+psycopg://...`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `QDRANT_URL`
- `SIMAP_PUBLICATIONS_PATH=/api/publications/v2/project/project-search`
- `SIMAP_PUBLICATION_DETAIL_PATH=/api/publications/v1/project/{projectId}/publication-details/{publicationId}`

## Useful commands
```bash
# run migrations manually
alembic upgrade head

# inspect qdrant collection
curl http://localhost:6333/collections/tender_chunks

# count points
curl -X POST http://localhost:6333/collections/tender_chunks/points/count \
  -H "Content-Type: application/json" \
  -d '{"exact": true}'
```
