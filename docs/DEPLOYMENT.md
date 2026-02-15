# Deployment Guide

## Railway Deployment

1. **Push to GitHub**: `git push origin main`
2. **Add Service**: In Railway project "splendid-nature", add new service from this GitHub repo
3. **Environment Variables**: Set in Railway dashboard (see `.env.example`)
   - `JWT_SECRET` — generate a secure random string
   - `GITEA_URL` — your Gitea instance URL
   - `GITEA_TOKEN` — API token for Gitea access
4. **Auto-deploy**: Railway builds using `Dockerfile` and `railway.toml`
5. **Health Check**: Railway pings `GET /health` to verify deployment

### Railway Environment Variables

The following are auto-available via Railway internal networking:
- `CIMGRAPH_API_URL=http://cimgraph-api.railway.internal`
- `BLAZEGRAPH_URL=http://blazegraph.railway.internal:8080/bigdata`
- `N8N_WEBHOOK_URL=https://n8n-g8qm-production.up.railway.app`

## Local Development (Docker)

```bash
# Build
docker build -t scada-studio .

# Run
docker run -p 4000:4000 \
  -e JWT_SECRET=dev-secret \
  -e GITEA_URL=http://host.docker.internal:3000 \
  scada-studio
```

## Local Development (No Docker)

```bash
# Terminal 1: Backend
cd backend && npm install && npm run dev

# Terminal 2: Frontend
cd frontend && npm install && npm run dev
```

Frontend dev server (Vite) proxies `/api` to `localhost:4000`.