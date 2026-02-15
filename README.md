# SCADA Studio

Web-based RTAC configuration management tool with points list generation, RAG search, and CIM topology visualization.

## Features

- **RTAC XML Parsing** — Upload RTAC XML exports, extract devices, points, and tag mappings (TypeScript port of [RTAC PLG](../rtac-plg/) parsing engine)
- **Points List Generation** — Generate structured points lists grouped by server device with source/destination mapping, download as JSON/CSV
- **Monaco XML Editor** — View and edit RTAC XML configs with syntax highlighting
- **RAG Search** — Query RTAC configurations via n8n RAG search webhooks
- **CIM Topology** — Generate CIM-style topology queries via Blazegraph SPARQL and CIMGraph API
- **XML Diff** — Compare two RTAC XML configurations side-by-side
- **Gitea Integration** — Connect to Gitea or any compatible Git server for version control
- **Railway Ready** — Single-container deployment for Railway alongside existing Verance AI tools

## Architecture

```
┌─────────────────────────────────────────────┐
│           SCADA Studio (Railway)            │
│  ┌─────────────┐  ┌──────────────────────┐  │
│  │  React UI   │  │   Express Backend    │  │
│  │  (Vite/MUI) │  │   - RTAC XML Parser  │  │
│  │             │──│   - Points List Gen  │  │
│  │  Dashboard  │  │   - Gitea Service    │  │
│  │  Editor     │  │   - Query Proxy      │  │
│  │  Query      │  │   - Diff Engine      │  │
│  │  Diff       │  │                      │  │
│  │  Settings   │  │                      │  │
│  └─────────────┘  └──────────┬───────────┘  │
└──────────────────────────────┼──────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   n8n Webhooks  │  │  CIMGraph API   │  │   Blazegraph    │
│   (RAG Search)  │  │  (NL→SPARQL)    │  │   (CIM Graph)   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

## Quick Start

### Local Development

```bash
# Backend
cd backend
npm install
npm run dev     # → http://localhost:4000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev     # → http://localhost:5173 (proxies /api → :4000)
```

### Railway Deployment

1. Push to GitHub
2. Add service in Railway from repo
3. Set environment variables (see `.env.example`)
4. Railway auto-builds via `Dockerfile` + `railway.toml`

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `4000` | Server port (Railway sets this) |
| `JWT_SECRET` | `scada-studio-dev-secret` | Auth token signing key |
| `GITEA_URL` | `http://localhost:3000` | Gitea server URL |
| `GITEA_TOKEN` | — | Gitea API token |
| `N8N_WEBHOOK_URL` | `https://n8n-g8qm-production.up.railway.app` | n8n webhook base |
| `CIMGRAPH_API_URL` | `http://cimgraph-api.railway.internal` | CIMGraph API |
| `BLAZEGRAPH_URL` | `http://blazegraph.railway.internal:8080/bigdata` | Blazegraph SPARQL |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/configs/upload` | Upload RTAC XML file |
| `GET` | `/api/configs` | List uploaded configs |
| `GET` | `/api/configs/:id` | Get config details (devices, points) |
| `GET` | `/api/configs/:id/xml` | Get raw XML |
| `POST` | `/api/configs/:id/generate-points` | Generate points list |
| `POST` | `/api/query/search` | RAG search |
| `POST` | `/api/query/cim-topology` | CIM topology query |
| `POST` | `/api/diff/compare` | Compare two XML files |
| `GET` | `/api/repos` | List Gitea repositories |
| `GET/POST` | `/api/settings/gitea` | Gitea connection settings |

## Tech Stack

- **Frontend**: React 18, MUI 5, Monaco Editor, Vite, Zustand, TanStack Query
- **Backend**: Express 4, TypeScript, fast-xml-parser, simple-git, Axios
- **Deployment**: Docker (multi-stage), Railway