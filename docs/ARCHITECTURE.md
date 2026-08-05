# Architecture

## Overview

SCADA Studio uses a **sidecar pattern** alongside vanilla Gitea:

```
                     ┌─────────────┐
   Engineer ────────►│   Gitea     │  Git push, web UI
                     │  (vanilla)  │
                     └──────┬──────┘
                            │ webhook (push event)
                            ▼
                     ┌──────────────┐
                     │   Sidecar    │  FastAPI service
                     │  (plugins/)  │
                     └──────┬───────┘
                            │ SQL + pgvector
                            ▼
                     ┌──────────────┐
                     │  PostgreSQL  │  Shared DB
                     │  + pgvector  │
                     └──────────────┘
```

## Data Flow

### Automatic Indexing (push)

1. Engineer pushes RTAC XML to a Gitea repo
2. Gitea fires a push webhook to the sidecar
3. Sidecar fetches the new/modified XML files via Gitea API
4. RTAC PLG parser extracts devices + points
5. Text chunks are generated and embedded via sentence-transformers
6. Points and embeddings are stored in PostgreSQL (pgvector)

### RAG Search

1. User sends a natural-language query to `POST /api/search`
2. Query is embedded using the same sentence-transformer model
3. pgvector finds nearest-neighbor chunks via HNSW cosine distance
4. Results are returned with repo, file path, and relevance score

### Similar Configuration Finding

1. User provides a config ID or descriptive text
2. System retrieves / generates the embedding
3. pgvector finds config-level summary chunks with highest cosine similarity
4. Returns ranked list of similar configs across all repos

### SCADA Design Narrative Generation

1. A zipped RTAC project export is posted to `POST /api/narrative/digest`
2. `rtac_plg/narrative_digest.py` walks the export and emits a bounded fact
   base — interfaces and their settings, point inventories, user logic and
   revision history. Credentials in the export (relay passwords, SNMP
   community strings, DNP authentication keys) are **redacted at extraction**
   so the digest is safe to send to an external LLM
3. Tag Processor rows are resolved into directional signal chains, reusing
   rtac-plg's rule that a row sourced from an `operAPC`/`operSPC` point is a
   control being received rather than telemetry being published
4. `POST /api/narrative/prompts` slices that digest into one self-contained
   prompt per document section
5. The caller (an n8n workflow, `SCADA Design Narrative — RTAC Export`) fans
   the prompts out across LLM calls and concatenates the results

The split exists because a real export is hundreds of megabytes — ORS1's
SCADA DNP map alone is 27 MB — so raw XML can never reach a context window.
Bounding is by *relevance*: a point on a large map survives only if the Tag
Processor or user logic references it.

### Points List Generation

1. User uploads RTAC XML (or it's fetched from Gitea)
2. Parser extracts devices and enabled point records
3. Points are mapped through schema columns and type mapping
4. Output returned as JSON or CSV

## Database Schema

- **rtac_configs** — one row per parsed file (repo + path + commit)
- **points** — individual point records linked to a config
- **embeddings** — vector embeddings for RAG search (384-dim, all-MiniLM-L6-v2)

## Why Sidecar Instead of Gitea Fork?

| Approach | Pros | Cons |
|----------|------|------|
| **Sidecar** (chosen) | Gitea stays vanilla and updatable; SCADA logic is independent; Python ecosystem for ML | Extra HTTP hop; separate container |
| **Gitea fork** | Tighter UI integration; single binary | Hard to update Gitea; must maintain Go patches |
| **Gitea Actions only** | No extra service needed | Limited UI integration; no live search |

## External Service Integration

The sidecar can optionally proxy to other Verance AI services:

- **n8n** — trigger n8n webhooks for complex workflows
- **CIMGraph API** — natural language → SPARQL queries against CIM models
- **Blazegraph** — direct SPARQL queries for CIM topology
