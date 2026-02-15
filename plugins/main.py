"""
SCADA Studio Sidecar — FastAPI application.

Provides RTAC config processing, RAG search, and similar-config finding
as a companion service to vanilla Gitea.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from api.routes import router as api_router
from rag.embedder import load_embedding_model


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    settings = get_settings()
    # Pre-load the embedding model so first request isn't slow
    load_embedding_model(settings.embedding_model)
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

app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "scada-studio-sidecar"}
