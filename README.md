# SCADA Studio

Gitea-based RTAC configuration management platform with RAG-powered search, automatic points list generation, and similar-config finding.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    docker-compose.yml                           │
│                                                                 │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │  Gitea        │  │  Sidecar (FastAPI)│  │  PostgreSQL      │  │
│  │  (vanilla)    │  │                  │  │  + pgvector      │  │
│  │               │  │  /api/parse      │  │                  │  │
│  │  Git repos    │──│  /api/search     │──│  rtac_configs    │  │
│  │  Web UI       │  │  /api/similar    │  │  points          │  │
│  │  Webhooks  ───│──│  /api/webhook    │  │  embeddings      │  │
│  │               │  │  /api/index      │  │  (vector search) │  │
│  │  Custom       │  │                  │  │                  │  │
│  │  templates ───│──│  RTAC PLG parser │  │                  │  │
│  └──────────────┘  └──────────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   n8n Webhooks  │  │  CIMGraph API   │  │   Blazegraph    │
│   (RAG Search)  │  │  (NL→SPARQL)    │  │   (CIM Graph)   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### Components

| Component | Role | Image / Build |
|-----------|------|---------------|
| **Gitea** | Git server, web UI, webhooks | `gitea/gitea:1.22` (vanilla) |
| **Sidecar** | RTAC parsing, RAG search, similar-config finder | `./plugins` (FastAPI) |
| **PostgreSQL** | Shared database for Gitea + SCADA data + vector embeddings | `pgvector/pgvector:pg16` |

### Key Design Decisions

- **Vanilla Gitea** — no fork, no compiled plugins. Gitea stays independently updatable.
- **Custom templates** — mounted read-only into Gitea to inject SCADA toolbar and buttons on XML file views.
- **Sidecar pattern** — all custom SCADA logic lives in a separate FastAPI service, called via HTTP from Gitea templates and webhooks.
- **pgvector** — PostgreSQL extension for vector similarity search, enabling RAG without an external vector DB.

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Edit .env with your passwords and tokens

# 2. Launch
docker compose up -d

# 3. Access
# Gitea:   http://localhost:3000  (first run: create admin account)
# Sidecar: http://localhost:8000/docs  (FastAPI interactive docs)
```

### First-Time Gitea Setup

1. Open http://localhost:3000
2. Complete the installation wizard (database is pre-configured)
3. Create an admin account
4. Generate an API token: Settings → Applications → Generate Token
5. Add the token to `.env` as `GITEA_TOKEN`
6. Create a webhook on your RTAC config repo:
   - URL: `http://sidecar:8000/api/webhook/push`
   - Content type: `application/json`
   - Events: Push

## API Endpoints (Sidecar)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/parse` | Upload RTAC XML → extract devices + points |
| `POST` | `/api/parse/points-list` | Upload RTAC XML → points list (JSON/CSV) |
| `POST` | `/api/search` | Semantic search across indexed configs |
| `POST` | `/api/index` | Parse + index a config for RAG search |
| `POST` | `/api/similar` | Find similar configurations |
| `POST` | `/api/webhook/push` | Gitea push webhook (auto-indexes XML files) |

## Project Structure

```
scada-studio/
├── docker-compose.yml          # Gitea + Postgres/pgvector + Sidecar
├── .env.example                # Environment variable template
│
├── gitea/                      # Gitea customization (no source code)
│   └── custom/                 # Mounted into Gitea container
│       ├── templates/custom/   # UI overrides
│       │   ├── header.tmpl     # SCADA toolbar
│       │   └── extra_links.tmpl # File-view buttons
│       └── conf/
│           └── app.ini         # Gitea config overrides
│
├── plugins/                    # Sidecar service (FastAPI)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                 # App entry point
│   ├── config.py               # Settings (pydantic-settings)
│   ├── database.py             # Async SQLAlchemy engine
│   ├── models.py               # ORM models
│   ├── api/                    # REST endpoints
│   │   ├── routes.py
│   │   ├── schemas.py
│   │   └── gitea_client.py
│   ├── rtac_plg/               # RTAC config parsing
│   │   ├── parser.py           # XML → devices + points
│   │   └── points_list.py      # Points list generation
│   ├── rag/                    # RAG search
│   │   ├── embedder.py         # Sentence-transformer embeddings
│   │   ├── indexer.py          # Parse → chunk → embed → store
│   │   └── search.py           # pgvector similarity search
│   └── similar_configs/
│       └── finder.py           # Similar config finder
│
├── db/
│   └── init.sql                # pgvector extension + schema
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEPLOYMENT.md
│   └── USER_GUIDE.md
│
├── _archive/                   # Previous React+Express implementation
│
└── railway.toml                # Railway deployment config
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_USER` | `scada` | Database user |
| `POSTGRES_PASSWORD` | — | **Required.** Database password |
| `POSTGRES_DB` | `scada_studio` | SCADA Studio database name |
| `GITEA_VERSION` | `1.22` | Gitea Docker image tag |
| `GITEA_ROOT_URL` | `http://localhost:3000` | Gitea external URL |
| `GITEA_TOKEN` | — | Gitea API token (for sidecar) |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformer model |
| `N8N_WEBHOOK_URL` | `https://n8n-g8qm-production.up.railway.app` | n8n base URL |
| `CIMGRAPH_API_URL` | `http://cimgraph-api.railway.internal` | CIMGraph API |
| `BLAZEGRAPH_URL` | `http://blazegraph.railway.internal:8080/bigdata` | Blazegraph SPARQL |

## Development

```bash
# Run sidecar locally (without Docker)
cd plugins
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Interactive API docs
open http://localhost:8000/docs
```
