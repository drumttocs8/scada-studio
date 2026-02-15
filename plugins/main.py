"""
SCADA Studio Sidecar — FastAPI application.

Provides RTAC config processing, RAG search, and similar-config finding
as a companion service to vanilla Gitea.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    settings = get_settings()

    # Auto-create tables if they don't exist (runs pgvector CREATE EXTENSION too)
    try:
        from database import _get_engine
        from models import Base
        from sqlalchemy import text
        engine, _ = _get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified / created")
    except Exception as e:
        logger.warning(f"Database migration skipped (will retry on first request): {e}")

    # Lazy-load embedding model in background (don't block startup/healthcheck)
    try:
        from rag.embedder import load_embedding_model
        load_embedding_model(settings.embedding_model)
        logger.info("Embedding model loaded")
    except Exception as e:
        logger.warning(f"Embedding model not loaded (will retry on first request): {e}")
    yield


app = FastAPI(
    title="SCADA Studio Sidecar",
    description="RTAC config processing, RAG search, and similar-config finding for Gitea",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Gitea custom templates call this service
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import routes after app creation (routes import database/models lazily)
from api.routes import router as api_router  # noqa: E402

app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "scada-studio-sidecar"}
