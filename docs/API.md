# SCADA Studio API Reference

## Health

### `GET /health`
Returns service status. Always returns 200 if app is running (Railway health check pattern).

```json
{ "status": "healthy", "service": "scada-studio-backend", "version": "0.1.0" }
```

## Configs

### `POST /api/configs/upload`
Upload RTAC XML file. Multipart form with `file` field.

**Response:**
```json
{ "id": "uuid", "filename": "config.xml", "devices": 3, "points": 150, "tagMappings": 45 }
```

### `GET /api/configs`
List all uploaded configurations.

### `GET /api/configs/:id`
Get config detail with parsed devices and points.

### `GET /api/configs/:id/xml`
Get raw XML content.

### `POST /api/configs/:id/generate-points`
Generate structured points list from parsed config.

## Query

### `POST /api/query/search`
RAG search via n8n webhook. Proxies to `N8N_WEBHOOK_URL/webhook/rag-search`.

**Request:** `{ "query": "What DNP points are configured?" }`

### `POST /api/query/cim-topology`
CIM topology query. Accepts natural language or raw SPARQL.

**Request:** `{ "query": "Show transformers" }` or `{ "sparql": "SELECT ..." }`

## Repositories

### `GET /api/repos`
List Gitea repositories.

### `POST /api/repos`
Create new repository.

## Diff

### `POST /api/diff/compare`
Compare two XML strings.

**Request:** `{ "xml1": "...", "xml2": "..." }`

## Settings

### `GET /api/settings/gitea`
Get current Gitea connection settings.

### `POST /api/settings/gitea`
Update Gitea connection settings.