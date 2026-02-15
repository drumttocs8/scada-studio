# Deployment Guide

## Local Development (Docker Compose)

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env — at minimum set POSTGRES_PASSWORD

# Start all services
docker compose up -d

# View logs
docker compose logs -f sidecar
docker compose logs -f gitea

# Access
# Gitea:   http://localhost:3000
# Sidecar: http://localhost:8000/docs  (Swagger UI)
```

### First Run

1. Open Gitea at http://localhost:3000
2. Complete the install wizard (DB settings are pre-configured via env vars)
3. Create an admin account
4. Create an API token and add to `.env` as `GITEA_TOKEN`
5. Restart sidecar: `docker compose restart sidecar`
6. On your RTAC config repo, add a webhook:
   - URL: `http://sidecar:8000/api/webhook/push`
   - Content type: `application/json`
   - Trigger: Push events

## Railway Deployment

SCADA Studio consists of three services. On Railway, deploy them as separate services in the same project:

### 1. PostgreSQL (pgvector)

- Use Railway's PostgreSQL plugin **or** a custom Docker service with `pgvector/pgvector:pg16`
- Run `db/init.sql` against the database after creation
- Note the connection string for other services

### 2. Gitea

- Deploy from Docker image `gitea/gitea:1.22`
- Set database env vars to point to the shared PostgreSQL
- Mount or configure custom templates (or accept defaults)
- Set `GITEA__server__ROOT_URL` to the public Railway URL

### 3. Sidecar (this repo)

- Deploy from this repo (builds `plugins/Dockerfile`)
- Set `DATABASE_URL` to the PostgreSQL connection string
- Set `GITEA_URL` to the internal Railway URL for Gitea
- Set `GITEA_TOKEN` to an API token from Gitea

### Railway Environment Variables

```
DATABASE_URL=postgresql+asyncpg://user:password@postgres.railway.internal:5432/scada_studio
GITEA_URL=http://gitea.railway.internal:3000
GITEA_TOKEN=<your-gitea-token>
EMBEDDING_MODEL=all-MiniLM-L6-v2
N8N_WEBHOOK_URL=https://n8n-g8qm-production.up.railway.app
CIMGRAPH_API_URL=http://cimgraph-api.railway.internal
BLAZEGRAPH_URL=http://blazegraph.railway.internal:8080/bigdata
```

## Updating Gitea

Since Gitea is a vanilla Docker image, updating is straightforward:

```bash
# Update the version in .env
GITEA_VERSION=1.23

# Pull and restart
docker compose pull gitea
docker compose up -d gitea
```

Custom templates are mounted read-only and survive Gitea upgrades.

## Sidecar-only Development

To develop the sidecar without Docker:

```bash
cd plugins
python -m venv .venv
.venv/Scripts/activate  # Windows
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Requires a running PostgreSQL with pgvector. Set `DATABASE_URL` env var accordingly.
