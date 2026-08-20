"""
SCADA Studio Sidecar — configuration shared across all modules.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Server
    port: int = 8000

    # Database (PostgreSQL + pgvector)
    database_url: str = "postgresql+asyncpg://scada:scada@localhost:5432/scada_studio"

    # Gitea
    gitea_url: str = "http://localhost:3000"
    # Browser-reachable Gitea origin, used only to build citation links. API
    # calls go over the internal hostname, which a person clicking a citation
    # cannot resolve; set this to the public URL so citations actually open.
    gitea_public_url: str = ""
    gitea_token: str = ""
    # Optional narrowing filter for SCADA Mapping repo discovery. Empty by
    # default: configs are pushed by whichever engineer did the work, so
    # scoping discovery to one account hides other people's substations.
    gitea_owner: str = ""

    # External Verance services (RAG/embeddings handled by n8n)
    n8n_webhook_url: str = "https://n8n-g8qm-production.up.railway.app"
    cimgraph_api_url: str = "http://cimgraph-api.railway.internal"
    cim_admin_url: str = "http://cim-admin.railway.internal"
    blazegraph_url: str = "http://blazegraph.railway.internal:8080/bigdata"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
