"""
Pydantic schemas for API request/response bodies.
"""

from pydantic import BaseModel, Field
from typing import Optional


# ─── RTAC PLG ────────────────────────────────────────────────────────────


class ParseResponse(BaseModel):
    filename: str
    device_count: int
    point_count: int
    devices: list[dict]
    points: list[dict]


# ─── RAG Search ──────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural-language search query")
    top_k: int = Field(10, ge=1, le=100, description="Number of results")


class SearchResult(BaseModel):
    config_id: int
    repo: str
    file_path: str
    chunk_text: str
    chunk_type: str
    metadata: dict = {}


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


# ─── Index ───────────────────────────────────────────────────────────────


class IndexResponse(BaseModel):
    config_id: int
    status: str


# ─── Similar Configs ─────────────────────────────────────────────────────


class SimilarRequest(BaseModel):
    config_id: Optional[int] = Field(None, description="Find configs similar to this one")
    text: Optional[str] = Field(None, description="Or search by free text")
    top_k: int = Field(10, ge=1, le=100)


class SimilarConfigResult(BaseModel):
    config_id: int
    repo: str
    file_path: str
    score: float
    device_name: Optional[str] = None


class SimilarResponse(BaseModel):
    results: list[SimilarConfigResult]


# ─── Gitea Webhook ───────────────────────────────────────────────────────


class CommitInfo(BaseModel):
    id: str
    message: str = ""
    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []


class RepoInfo(BaseModel):
    full_name: str  # e.g. "scada/rtac-configs"


class WebhookPayload(BaseModel):
    ref: str = ""
    after: str = ""  # commit SHA
    repository: RepoInfo
    commits: list[CommitInfo] = []
