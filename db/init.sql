-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Separate database for Gitea (Gitea manages its own schema)
-- Created via GITEA__database__NAME env var; Gitea auto-creates if user has rights.
-- We grant the shared user access:
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'gitea') THEN
    PERFORM dblink_exec('dbname=postgres', 'CREATE DATABASE gitea');
  END IF;
EXCEPTION WHEN OTHERS THEN
  -- dblink not available; Gitea will create its own DB on first run
  NULL;
END $$;

-- ─── SCADA Studio schema ─────────────────────────────────────────────────

-- Indexed RTAC configurations (one row per parsed file)
CREATE TABLE IF NOT EXISTS rtac_configs (
    id              SERIAL PRIMARY KEY,
    repo            TEXT NOT NULL,            -- Gitea repo (owner/name)
    file_path       TEXT NOT NULL,            -- path inside repo
    commit_sha      TEXT NOT NULL,
    device_name     TEXT,
    parsed_at       TIMESTAMPTZ DEFAULT NOW(),
    metadata        JSONB DEFAULT '{}',       -- flexible extra fields
    UNIQUE (repo, file_path, commit_sha)
);

-- Individual points extracted from configs
CREATE TABLE IF NOT EXISTS points (
    id              SERIAL PRIMARY KEY,
    config_id       INTEGER REFERENCES rtac_configs(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    address         TEXT,
    point_type      TEXT,                     -- AI, BI, AO, BO, CT …
    data_type       TEXT,                     -- MV, SPS, BOOL …
    description     TEXT,
    source_tag      TEXT,
    destination_tag TEXT,
    extra           JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Embeddings for RAG search (1 embedding per logical chunk)
CREATE TABLE IF NOT EXISTS embeddings (
    id              SERIAL PRIMARY KEY,
    config_id       INTEGER REFERENCES rtac_configs(id) ON DELETE CASCADE,
    chunk_text      TEXT NOT NULL,
    chunk_type      TEXT DEFAULT 'config',    -- 'config', 'point', 'device'
    embedding       vector(384),              -- all-MiniLM-L6-v2 dimension
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- HNSW index for fast approximate nearest-neighbor search
CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw
    ON embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- B-tree indexes for common lookups
CREATE INDEX IF NOT EXISTS idx_rtac_configs_repo ON rtac_configs(repo);
CREATE INDEX IF NOT EXISTS idx_points_config ON points(config_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_config ON embeddings(config_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_type ON embeddings(chunk_type);
