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


# ─── Device Mappings (cross-profile) ────────────────────────────────────


class DeviceMappingCreate(BaseModel):
    """Create or update a device mapping."""
    substation: str = Field(..., min_length=1, description="Substation / site name")
    eq_uri: Optional[str] = Field(None, description="EQ equipment CIM mRID")
    eq_name: Optional[str] = Field(None, description="EQ equipment name")
    eq_type: Optional[str] = Field(None, description="CIM class: Breaker, PowerTransformer, etc.")
    sc_device_uri: Optional[str] = Field(None, description="SC RemoteUnit CIM mRID")
    sc_device_name: Optional[str] = Field(None, description="RemoteUnit name")
    sc_map_name: Optional[str] = Field(None, description="RTAC map name")
    pe_relay_uri: Optional[str] = Field(None, description="PE relay CIM mRID")
    pe_relay_name: Optional[str] = Field(None, description="PE relay name")
    tag_pattern: Optional[str] = Field(None, description="Regex matching SCADA tags")
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    source: str = Field("manual", description="manual | naming_convention | ai_inferred")
    model_name: Optional[str] = Field(None, description="Blazegraph model name")
    config_id: Optional[int] = Field(None, description="Related rtac_config ID")


class DeviceMappingResponse(BaseModel):
    id: int
    substation: str
    eq_uri: Optional[str] = None
    eq_name: Optional[str] = None
    eq_type: Optional[str] = None
    sc_device_uri: Optional[str] = None
    sc_device_name: Optional[str] = None
    sc_map_name: Optional[str] = None
    pe_relay_uri: Optional[str] = None
    pe_relay_name: Optional[str] = None
    tag_pattern: Optional[str] = None
    confidence: float = 1.0
    source: str = "manual"
    model_name: Optional[str] = None
    config_id: Optional[int] = None

    model_config = {"from_attributes": True}


class DeviceMappingListResponse(BaseModel):
    substation: Optional[str] = None
    count: int
    mappings: list[DeviceMappingResponse]


class AutoDetectRequest(BaseModel):
    """Request automatic device mapping via naming conventions."""
    substation: str = Field(..., description="Substation name")
    model_name: Optional[str] = Field(None, description="Blazegraph model for EQ lookup")
    config_id: Optional[int] = Field(None, description="RTAC config to match against")


class AutoDetectResponse(BaseModel):
    substation: str
    new_mappings: int
    updated_mappings: int
    details: list[dict] = []
