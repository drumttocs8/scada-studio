"""
SCADA Studio Sidecar — configuration shared across all modules.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database (PostgreSQL + pgvector)
    database_url: str = "postgresql+asyncpg://scada:scada@localhost:5432/scada_studio"

    # Gitea
    gitea_url: str = "http://localhost:3000"
    gitea_token: str = ""

    # Embedding model (sentence-transformers)
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # External Verance services
    n8n_webhook_url: str = "https://n8n-g8qm-production.up.railway.app"
    cimgraph_api_url: str = "http://cimgraph-api.railway.internal"
    blazegraph_url: str = "http://blazegraph.railway.internal:8080/bigdata"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
