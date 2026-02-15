# User Guide

## Accessing SCADA Studio

SCADA Studio adds RTAC-specific functionality on top of Gitea. When you open Gitea, you'll see a **SCADA toolbar** at the top with links to:

- **Search** — RAG-powered semantic search across all indexed RTAC configs
- **Parse Config** — Upload and parse an RTAC XML file
- **Similar Configs** — Find configurations similar to a given one

## Managing RTAC Configs in Gitea

### Creating a Repository

1. Click **+** → **New Repository** in Gitea
2. Name it (e.g., `rtac-configs` or by substation name)
3. Push your RTAC XML exports to the repo

### Automatic Indexing

When a webhook is configured (see [Deployment Guide](DEPLOYMENT.md)), every push that includes `.xml` files automatically:

1. Fetches the XML from the repo
2. Parses it for devices and points
3. Generates text embeddings
4. Stores everything in PostgreSQL for search

### Viewing XML Files

When viewing an XML file in Gitea, you'll see extra buttons injected by the custom templates:

- **Find Similar Configs** — queries the sidecar for other configs with similar structure
- **Generate Points List** — parses the file and shows a structured points list
- **Search Similar Content** — semantic search using this file as context

## Using the Sidecar API Directly

The sidecar exposes a Swagger UI at `http://localhost:8000/docs` (or your Railway URL).

### Parse an RTAC XML File

```bash
curl -X POST http://localhost:8000/api/parse \
  -F "file=@my_rtac_config.xml"
```

### Generate Points List

```bash
# JSON output
curl -X POST "http://localhost:8000/api/parse/points-list?format=json" \
  -F "file=@my_rtac_config.xml"

# CSV output
curl -X POST "http://localhost:8000/api/parse/points-list?format=csv" \
  -F "file=@my_rtac_config.xml" -o points.csv
```

### Index a Config for Search

```bash
curl -X POST "http://localhost:8000/api/index?repo=scada/rtac-configs&file_path=Trinity_Hills.xml&commit_sha=abc123" \
  -F "file=@Trinity_Hills.xml"
```

### Semantic Search

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "DNP server with analog inputs for transformer monitoring", "top_k": 5}'
```

### Find Similar Configs

```bash
# By config ID
curl -X POST http://localhost:8000/api/similar \
  -H "Content-Type: application/json" \
  -d '{"config_id": 1, "top_k": 5}'

# By text description
curl -X POST http://localhost:8000/api/similar \
  -H "Content-Type: application/json" \
  -d '{"text": "solar inverter RTAC with Modbus client", "top_k": 5}'
```

## Workflow Summary

```
Engineer exports RTAC config (.exp → .xml via AcRTACcmd)
           ↓
Push XML to Gitea repo
           ↓
Webhook triggers sidecar auto-indexing
           ↓
Points + embeddings stored in PostgreSQL
           ↓
Search, compare, and generate points lists from Gitea UI
```
