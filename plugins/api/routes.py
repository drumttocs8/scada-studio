"""
API routes — ties together all plugin modules.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pydantic import BaseModel, Field

from database import get_db
from rtac_plg.parser import parse_rtac_xml_bytes, extract_points
from rag.indexer import index_config
from rag.search import text_search
from similar_configs.finder import find_similar
from api.schemas import (
    ParseResponse,
    SearchRequest,
    SearchResponse,
    SimilarRequest,
    SimilarResponse,
    WebhookPayload,
    IndexResponse,
    DeviceMappingCreate,
    DeviceMappingResponse,
    DeviceMappingListResponse,
    AutoDetectRequest,
    AutoDetectResponse,
)
from api.gitea_client import fetch_file_from_gitea, commit_file_to_gitea

router = APIRouter()


# ─── RTAC PLG ────────────────────────────────────────────────────────────


@router.post("/parse", response_model=ParseResponse, tags=["RTAC PLG"])
async def parse_rtac_config(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload an RTAC XML export and extract points."""
    content = await file.read()
    try:
        devices, points = parse_rtac_xml_bytes(content, filename=file.filename or "upload.xml")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse XML: {e}")

    return ParseResponse(
        filename=file.filename or "upload.xml",
        device_count=len(devices),
        point_count=len(points),
        devices=devices,
        points=points,
    )


@router.post("/parse/points-list", tags=["RTAC PLG"])
async def generate_points_list(
    file: UploadFile = File(...),
    format: str = Query("json", regex="^(json|csv)$"),
):
    """Upload RTAC XML → returns points list as JSON or CSV."""
    from rtac_plg.points_list import generate

    content = await file.read()
    return generate(content, file.filename or "upload.xml", output_format=format)


# ─── CIM Profile Generation ─────────────────────────────────────────────


@router.post("/parse/sc-profile", tags=["CIM Profiles"])
async def generate_sc_profile_endpoint(
    file: UploadFile = File(...),
    substation_name: str = Query(..., description="Substation name for the profile"),
    eq_model_urn: Optional[str] = Query(None, description="URN of the dependent EQ profile"),
    format: str = Query("xml", regex="^(xml|json)$"),
):
    """
    Upload RTAC XML → generate SC (SCADA Configuration) CIM profile.

    Returns CIM-compliant RDF/XML containing:
    - cim:RemoteUnit for each RTAC server device
    - cim:Analog / cim:Discrete / cim:Accumulator / cim:Control for each point
    - cim:RemoteSource / cim:RemoteControl linking points to RTUs
    - ver:SCADAPoint extensions for DNP3 addresses and tag names
    """
    from rtac_plg.sc_profile import generate_sc_profile_from_bytes
    from fastapi.responses import Response

    content = await file.read()
    try:
        xml_bytes, stats = generate_sc_profile_from_bytes(
            content,
            filename=file.filename or "upload.xml",
            substation_name=substation_name,
            eq_model_urn=eq_model_urn,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to generate SC profile: {e}")

    if format == "json":
        return {
            "substation": substation_name,
            "profile": "SC",
            "model_urn": stats["model_urn"],
            "stats": stats,
            "xml_preview": xml_bytes.decode("utf-8")[:2000],
            "xml_size_bytes": len(xml_bytes),
        }

    return Response(
        content=xml_bytes,
        media_type="application/rdf+xml",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{substation_name}_SC_v1.xml"'
            )
        },
    )


# ─── RAG Search ──────────────────────────────────────────────────────────


@router.post("/search", response_model=SearchResponse, tags=["RAG"])
async def search_configs(
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Text search across indexed RTAC configurations."""
    results = await text_search(db, body.query, top_k=body.top_k)
    return SearchResponse(query=body.query, results=results)


@router.post("/index", response_model=IndexResponse, tags=["RAG"])
async def index_file(
    file: UploadFile = File(...),
    repo: str = Query(..., description="Gitea repo (owner/name)"),
    file_path: str = Query(..., description="Path inside repo"),
    commit_sha: str = Query("manual", description="Commit SHA"),
    db: AsyncSession = Depends(get_db),
):
    """Parse an RTAC XML file and store embeddings for RAG search."""
    content = await file.read()
    config_id = await index_config(
        db, content, repo=repo, file_path=file_path,
        commit_sha=commit_sha, filename=file.filename or "upload.xml",
    )
    return IndexResponse(config_id=config_id, status="indexed")


# ─── Similar Configs ─────────────────────────────────────────────────────


@router.post("/similar", response_model=SimilarResponse, tags=["Similar Configs"])
async def similar_configs(
    body: SimilarRequest,
    db: AsyncSession = Depends(get_db),
):
    """Find configurations similar to a given config or text."""
    results = await find_similar(db, body.config_id, body.text, top_k=body.top_k)
    return SimilarResponse(results=results)


# ─── Gitea Webhook ───────────────────────────────────────────────────────


@router.post("/webhook/push", tags=["Webhooks"])
async def gitea_push_webhook(
    payload: WebhookPayload,
    db: AsyncSession = Depends(get_db),
):
    """
    Called by Gitea on push events.

    For each RTAC XML file in the commit:
      1. Index for RAG search (text + embeddings)
      2. Generate SC (SCADA Configuration) CIM profile
      3. Commit the SC profile back to the Gitea repo under profiles/
      4. Forward the SC profile to Blazegraph via cim-admin

    Skips commits made by the bot itself (prevents infinite loops).
    """
    import logging

    logger = logging.getLogger(__name__)

    repo = payload.repository.full_name
    commit_sha = payload.after

    # Derive substation name from repo (e.g. "scada/trinity-hills" → "trinity-hills")
    substation_name = repo.split("/")[-1] if "/" in repo else repo

    indexed = []
    profiles_generated = []

    for commit in payload.commits:
        # Skip bot commits to prevent infinite webhook loops
        if "SCADA Studio Bot" in commit.message or "[bot]" in commit.message:
            logger.info(f"Skipping bot commit: {commit.message[:60]}")
            continue

        xml_files = [
            f for f in commit.added + commit.modified
            if f.startswith("xml/") and f.endswith(".xml")
        ]

        for fpath in xml_files:
            try:
                content = await fetch_file_from_gitea(repo, fpath, commit_sha)

                # 1. Index for RAG search
                config_id = await index_config(
                    db, content, repo=repo, file_path=fpath,
                    commit_sha=commit_sha, filename=fpath,
                )
                indexed.append({"file": fpath, "config_id": config_id})

                # 2. Generate SC profile from RTAC XML
                sc_result = await _generate_and_store_sc_profile(
                    repo=repo,
                    xml_content=content,
                    filename=fpath,
                    substation_name=substation_name,
                    logger=logger,
                )
                if sc_result:
                    profiles_generated.append(sc_result)

            except Exception as e:
                logger.warning(f"Failed to process {fpath}: {e}")
                indexed.append({"file": fpath, "error": str(e)})

    return {
        "repo": repo,
        "commit": commit_sha,
        "indexed": indexed,
        "profiles_generated": profiles_generated,
    }


async def _generate_and_store_sc_profile(
    repo: str,
    xml_content: bytes,
    filename: str,
    substation_name: str,
    logger,
) -> dict | None:
    """
    Generate an SC CIM profile from RTAC XML, commit it to Gitea,
    and forward it to Blazegraph via cim-admin.

    Returns a summary dict on success, None on failure.
    """
    from rtac_plg.sc_profile import generate_sc_profile_from_bytes
    from config import get_settings
    import httpx

    settings = get_settings()

    try:
        sc_xml_bytes, stats = generate_sc_profile_from_bytes(
            xml_content,
            filename=filename,
            substation_name=substation_name,
        )
    except Exception as e:
        logger.warning(f"SC profile generation failed for {filename}: {e}")
        return None

    result = {
        "source_file": filename,
        "substation": substation_name,
        "model_urn": stats.get("model_urn", ""),
        "stats": stats,
    }

    # ── Commit SC profile back to Gitea ──
    # Use a stable filename so it always reflects "current" state
    sc_filename = f"profiles/{substation_name}_SC.xml"
    try:
        commit_result = await commit_file_to_gitea(
            repo=repo,
            file_path=sc_filename,
            content=sc_xml_bytes,
            message=f"[bot] Update SC profile from {filename.split('/')[-1]}",
        )
        result["gitea_path"] = sc_filename
        result["gitea_commit"] = commit_result.get("content", {}).get("sha", "")
        logger.info(f"SC profile committed to {repo}/{sc_filename}")
    except Exception as e:
        logger.warning(f"Failed to commit SC profile to Gitea: {e}")
        result["gitea_error"] = str(e)

    # ── Forward SC profile to Blazegraph via cim-admin ──
    import_url = f"{settings.cim_admin_url}/api/profiles/import"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                import_url,
                params={
                    "profile_type": "SC",
                    "substation_name": substation_name,
                },
                files={
                    "file": (f"{substation_name}_SC.xml", sc_xml_bytes, "application/rdf+xml"),
                },
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                result["blazegraph_imported"] = data.get("success", False)
                result["blazegraph_model_urn"] = data.get("model_urn", "")
                logger.info(f"SC profile imported to Blazegraph for {substation_name}")
            else:
                logger.warning(f"Blazegraph import returned {resp.status_code}: {resp.text[:200]}")
                result["blazegraph_error"] = f"HTTP {resp.status_code}"
    except Exception as e:
        # Blazegraph push is best-effort; don't fail the webhook
        logger.warning(f"Failed to forward SC profile to Blazegraph: {e}")
        result["blazegraph_error"] = str(e)

    return result


# ─── Device Mappings (cross-profile) ─────────────────────────────────────


@router.get("/mappings", response_model=DeviceMappingListResponse, tags=["Device Mappings"])
async def list_mappings(
    substation: Optional[str] = Query(None, description="Filter by substation"),
    model_name: Optional[str] = Query(None, description="Filter by Blazegraph model"),
    db: AsyncSession = Depends(get_db),
):
    """List device mappings, optionally filtered by substation or model."""
    from sqlalchemy import select
    from models import DeviceMapping

    stmt = select(DeviceMapping)
    if substation:
        stmt = stmt.where(DeviceMapping.substation == substation)
    if model_name:
        stmt = stmt.where(DeviceMapping.model_name == model_name)
    stmt = stmt.order_by(DeviceMapping.substation, DeviceMapping.eq_name)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return DeviceMappingListResponse(
        substation=substation,
        count=len(rows),
        mappings=[DeviceMappingResponse.model_validate(r) for r in rows],
    )


@router.post("/mappings", response_model=DeviceMappingResponse, tags=["Device Mappings"])
async def create_mapping(
    body: DeviceMappingCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create or update a device mapping (upsert on substation+eq_uri+sc_device_uri)."""
    from sqlalchemy import select
    from models import DeviceMapping

    # Check for existing mapping to upsert
    stmt = select(DeviceMapping).where(
        DeviceMapping.substation == body.substation,
        DeviceMapping.eq_uri == body.eq_uri,
        DeviceMapping.sc_device_uri == body.sc_device_uri,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(existing, field, value)
        mapping = existing
    else:
        mapping = DeviceMapping(**body.model_dump())
        db.add(mapping)

    await db.commit()
    await db.refresh(mapping)
    return DeviceMappingResponse.model_validate(mapping)


@router.post("/mappings/bulk", response_model=DeviceMappingListResponse, tags=["Device Mappings"])
async def bulk_create_mappings(
    mappings: list[DeviceMappingCreate],
    db: AsyncSession = Depends(get_db),
):
    """Bulk create/update device mappings."""
    from models import DeviceMapping

    results = []
    for body in mappings:
        mapping = DeviceMapping(**body.model_dump())
        db.add(mapping)
        results.append(mapping)

    await db.commit()
    for m in results:
        await db.refresh(m)

    return DeviceMappingListResponse(
        count=len(results),
        mappings=[DeviceMappingResponse.model_validate(m) for m in results],
    )


@router.delete("/mappings/{mapping_id}", tags=["Device Mappings"])
async def delete_mapping(
    mapping_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a device mapping by ID."""
    from sqlalchemy import select
    from models import DeviceMapping

    stmt = select(DeviceMapping).where(DeviceMapping.id == mapping_id)
    result = await db.execute(stmt)
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    await db.delete(mapping)
    await db.commit()
    return {"deleted": mapping_id}


@router.get("/mappings/export", tags=["Device Mappings"])
async def export_mappings(
    substation: str = Query(..., description="Substation to export"),
    db: AsyncSession = Depends(get_db),
):
    """Export all mappings for a substation as JSON (for git storage)."""
    from sqlalchemy import select
    from models import DeviceMapping
    from datetime import datetime, timezone

    stmt = (
        select(DeviceMapping)
        .where(DeviceMapping.substation == substation)
        .order_by(DeviceMapping.eq_name)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return {
        "substation": substation,
        "model": rows[0].model_name if rows else None,
        "mappings": [
            {
                "eq_name": r.eq_name,
                "eq_type": r.eq_type,
                "eq_uri": r.eq_uri,
                "sc_device": r.sc_device_name,
                "sc_map_name": r.sc_map_name,
                "pe_relay": r.pe_relay_name,
                "tag_pattern": r.tag_pattern,
                "confidence": r.confidence,
                "source": r.source,
            }
            for r in rows
        ],
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── LLM-facing config Q&A API ───────────────────────────────────────────
#
# These endpoints expose indexed RTAC configurations in an LLM-friendly form.
# Designed to be called from n8n HTTP Request nodes (or any tool-calling
# runtime) so an engineer can ask questions about RTAC configs and get
# grounded answers with Gitea citations.
#
# Tool manifest: GET /api/llm/tools.json (OpenAI-style function definitions).


def _gitea_blob_url(repo: str, file_path: str, commit_sha: str | None = None) -> str:
    """Build a Gitea blob URL for citation."""
    from config import get_settings
    base = get_settings().gitea_url.rstrip("/")
    ref = commit_sha if commit_sha and commit_sha != "manual" else "main"
    return f"{base}/{repo}/src/commit/{ref}/{file_path}"


def _config_summary(c, include_devices: bool = False) -> dict:
    """Compact summary of an RtacConfig row for LLM consumption."""
    meta = c.metadata_ or {}
    out = {
        "config_id": c.id,
        "repo": c.repo,
        "file_path": c.file_path,
        "commit_sha": c.commit_sha,
        "substation": meta.get("substation"),
        "host_device": c.device_name,
        "device_count": meta.get("device_count", 0),
        "point_count": meta.get("point_count", 0),
        "server_count": meta.get("server_count", 0),
        "client_count": meta.get("client_count", 0),
        "gitea_url": _gitea_blob_url(c.repo, c.file_path, c.commit_sha),
    }
    if include_devices:
        out["devices"] = meta.get("devices", [])
    return out


@router.get("/configs", tags=["LLM API"])
async def list_configs(
    substation: Optional[str] = Query(None, description="Filter by substation"),
    repo: Optional[str] = Query(None, description="Filter by Gitea repo (owner/name)"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """List indexed RTAC configurations (latest commit per file).

    LLM-friendly summary including substation, device/point counts, and
    a clickable Gitea URL for citation.
    """
    from sqlalchemy import select, func
    from models import RtacConfig

    # Latest commit per (repo, file_path)
    latest_subq = (
        select(
            RtacConfig.repo,
            RtacConfig.file_path,
            func.max(RtacConfig.parsed_at).label("latest"),
        )
        .group_by(RtacConfig.repo, RtacConfig.file_path)
        .subquery()
    )
    stmt = (
        select(RtacConfig)
        .join(
            latest_subq,
            (RtacConfig.repo == latest_subq.c.repo)
            & (RtacConfig.file_path == latest_subq.c.file_path)
            & (RtacConfig.parsed_at == latest_subq.c.latest),
        )
        .order_by(RtacConfig.parsed_at.desc())
        .limit(limit)
    )
    if repo:
        stmt = stmt.where(RtacConfig.repo == repo)

    rows = (await db.execute(stmt)).scalars().all()
    items = [_config_summary(c) for c in rows]
    if substation:
        items = [c for c in items if (c.get("substation") or "").lower() == substation.lower()]
    return {"count": len(items), "configs": items}


@router.get("/configs/{config_id}", tags=["LLM API"])
async def get_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Detailed parsed view of a single config: devices, points, citations."""
    from sqlalchemy import select
    from models import RtacConfig, Point

    cfg = (await db.execute(
        select(RtacConfig).where(RtacConfig.id == config_id)
    )).scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="config not found")

    points = (await db.execute(
        select(Point).where(Point.config_id == config_id).order_by(Point.name)
    )).scalars().all()

    summary = _config_summary(cfg, include_devices=True)
    summary["points"] = [
        {
            "name": p.name,
            "address": p.address,
            "type": p.point_type,
            "description": p.description,
            "source_tag": p.source_tag,
            "destination_tag": p.destination_tag,
        }
        for p in points
    ]
    return summary


@router.get("/configs/{config_id}/devices", tags=["LLM API"])
async def get_config_devices(
    config_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Compact device list for a config (for topology comparison).

    Each device includes: name, map_name, role (server/client), protocol,
    manufacturer, model, connection_type, and any IP address found in the
    parsed XML metadata. This is what graph-admin's RTAC validator consumes.
    """
    from sqlalchemy import select
    from models import RtacConfig

    cfg = (await db.execute(
        select(RtacConfig).where(RtacConfig.id == config_id)
    )).scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="config not found")

    meta = cfg.metadata_ or {}
    return {
        "config_id": cfg.id,
        "repo": cfg.repo,
        "file_path": cfg.file_path,
        "substation": meta.get("substation"),
        "devices": meta.get("devices", []),
        "gitea_url": _gitea_blob_url(cfg.repo, cfg.file_path, cfg.commit_sha),
    }


@router.get("/configs/by-path", tags=["LLM API"])
async def get_config_by_path(
    repo: str = Query(..., description="owner/repo"),
    file_path: str = Query(..., description="path inside repo"),
    db: AsyncSession = Depends(get_db),
):
    """Look up the latest indexed config by Gitea repo + path."""
    from sqlalchemy import select
    from models import RtacConfig

    stmt = (
        select(RtacConfig)
        .where(RtacConfig.repo == repo, RtacConfig.file_path == file_path)
        .order_by(RtacConfig.parsed_at.desc())
        .limit(1)
    )
    cfg = (await db.execute(stmt)).scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="config not indexed")
    return _config_summary(cfg, include_devices=True)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Natural-language question")
    substation: Optional[str] = Field(None, description="Restrict to one substation")
    top_k: int = Field(8, ge=1, le=50)


@router.post("/ask", tags=["LLM API"])
async def ask_rtac(
    body: AskRequest,
    db: AsyncSession = Depends(get_db),
):
    """LLM-friendly Q&A: returns ranked text snippets from RTAC configs
    with Gitea citations the calling agent can present to the engineer.

    This is a grounding endpoint — it does NOT call an LLM itself. The
    caller (n8n / Copilot / MCP) is expected to synthesise the final
    answer from the returned snippets.
    """
    results = await text_search(db, body.question, top_k=body.top_k)

    # Hydrate with config metadata for citations
    from sqlalchemy import select
    from models import RtacConfig

    config_ids = list({r.config_id for r in results})
    configs = {}
    if config_ids:
        rows = (await db.execute(
            select(RtacConfig).where(RtacConfig.id.in_(config_ids))
        )).scalars().all()
        configs = {c.id: c for c in rows}

    snippets = []
    for r in results:
        c = configs.get(r.config_id)
        if not c:
            continue
        meta = c.metadata_ or {}
        if body.substation and (meta.get("substation") or "").lower() != body.substation.lower():
            continue
        snippets.append({
            "config_id": r.config_id,
            "repo": r.repo,
            "file_path": r.file_path,
            "substation": meta.get("substation"),
            "chunk_type": r.chunk_type,
            "snippet": r.chunk_text,
            "citation_url": _gitea_blob_url(c.repo, c.file_path, c.commit_sha),
        })

    return {
        "question": body.question,
        "snippet_count": len(snippets),
        "snippets": snippets,
    }


@router.get("/llm/tools.json", tags=["LLM API"])
async def llm_tool_manifest():
    """OpenAI-style function-calling manifest for the RTAC config API.

    Drop this into an n8n AI Agent node (or any tool-calling runtime)
    to expose RTAC config Q&A to the model.
    """
    return {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "rtac_list_configs",
                    "description": (
                        "List RTAC configurations indexed in SCADA Studio. "
                        "Use this first to discover which substations and files exist."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "substation": {"type": "string"},
                            "repo": {"type": "string"},
                        },
                    },
                    "http": {"method": "GET", "path": "/api/configs"},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "rtac_get_config",
                    "description": (
                        "Get the full parsed view of a single RTAC config: "
                        "devices (server + client roles), all points, and the "
                        "Gitea blob URL for citation."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "config_id": {"type": "integer"},
                        },
                        "required": ["config_id"],
                    },
                    "http": {"method": "GET", "path": "/api/configs/{config_id}"},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "rtac_get_devices",
                    "description": (
                        "Get just the device list for a config — server "
                        "devices (DNPServer/ModbusServer/...) and client "
                        "devices (relays, meters, ...) with manufacturer "
                        "and model. Use for topology questions."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {"config_id": {"type": "integer"}},
                        "required": ["config_id"],
                    },
                    "http": {"method": "GET", "path": "/api/configs/{config_id}/devices"},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "rtac_ask",
                    "description": (
                        "Ask a natural-language question about RTAC configs. "
                        "Returns ranked text snippets with Gitea citations. "
                        "Synthesise the final answer from these snippets."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "substation": {"type": "string"},
                            "top_k": {"type": "integer", "default": 8},
                        },
                        "required": ["question"],
                    },
                    "http": {"method": "POST", "path": "/api/ask"},
                },
            },
        ]
    }


# ─── RTAC Repositories (Gitea) ───────────────────────────────────────────

class RtacRepoIn(BaseModel):
    repo: str = Field(..., description="owner/repo on the configured Gitea instance")
    branch: str = "main"
    substation: Optional[str] = None
    path_prefix: str = ""  # empty = scan entire repo for *.xml
    notes: Optional[str] = None


@router.get("/repos", tags=["RTAC Repos"])
async def list_rtac_repos(db: AsyncSession = Depends(get_db)):
    """List registered RTAC repositories."""
    from sqlalchemy import select
    from models import RtacRepo

    rows = (await db.execute(select(RtacRepo).order_by(RtacRepo.id.desc()))).scalars().all()
    return {
        "repos": [
            {
                "id": r.id,
                "repo": r.repo,
                "branch": r.branch,
                "substation": r.substation,
                "path_prefix": r.path_prefix,
                "notes": r.notes,
                "last_synced_at": r.last_synced_at.isoformat() if r.last_synced_at else None,
                "last_sync_status": r.last_sync_status,
                "last_sync_message": r.last_sync_message,
            }
            for r in rows
        ]
    }


@router.post("/repos", tags=["RTAC Repos"])
async def create_rtac_repo(body: RtacRepoIn, db: AsyncSession = Depends(get_db)):
    """Register an RTAC repository. Does not sync — call POST /repos/{id}/sync."""
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from models import RtacRepo

    existing = (
        await db.execute(select(RtacRepo).where(RtacRepo.repo == body.repo))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Repo already registered: {body.repo}")

    row = RtacRepo(
        repo=body.repo,
        branch=body.branch or "main",
        substation=body.substation,
        path_prefix=body.path_prefix or "",
        notes=body.notes,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    await db.refresh(row)
    return {"id": row.id, "repo": row.repo}


@router.delete("/repos/{repo_id}", tags=["RTAC Repos"])
async def delete_rtac_repo(repo_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, delete
    from models import RtacRepo

    row = (
        await db.execute(select(RtacRepo).where(RtacRepo.id == repo_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Repo not found")
    await db.execute(delete(RtacRepo).where(RtacRepo.id == repo_id))
    await db.commit()
    return {"ok": True}


@router.post("/repos/{repo_id}/sync", tags=["RTAC Repos"])
async def sync_rtac_repo(
    repo_id: int,
    force: bool = Query(False, description="Re-index even if commit_sha matches"),
    db: AsyncSession = Depends(get_db),
):
    """
    Walk the Gitea repo for *.xml files under `path_prefix` and index each one
    that hasn't been indexed at its current commit.
    """
    import logging
    from datetime import datetime, timezone
    from sqlalchemy import select
    from models import RtacRepo, RtacConfig
    from api.gitea_client import list_repo_files, fetch_file_from_gitea

    logger = logging.getLogger(__name__)

    row = (
        await db.execute(select(RtacRepo).where(RtacRepo.id == repo_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Repo not registered")

    indexed: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    try:
        files = await list_repo_files(
            row.repo, path_prefix=row.path_prefix or "", ref=row.branch or "main"
        )
    except Exception as e:
        row.last_synced_at = datetime.now(timezone.utc)
        row.last_sync_status = "error"
        row.last_sync_message = f"Failed to list repo files: {e}"
        await db.commit()
        raise HTTPException(status_code=502, detail=f"Gitea list failed: {e}")

    for entry in files:
        fpath = entry["path"]
        try:
            existing = (
                await db.execute(
                    select(RtacConfig)
                    .where(RtacConfig.repo == row.repo)
                    .where(RtacConfig.file_path == fpath)
                    .where(RtacConfig.commit_sha == entry["sha"])
                )
            ).scalar_one_or_none()
            if existing and not force:
                skipped.append({"file": fpath, "config_id": existing.id})
                continue

            content = await fetch_file_from_gitea(row.repo, fpath, ref=row.branch or "main")
            cfg_id = await index_config(
                db,
                content,
                repo=row.repo,
                file_path=fpath,
                commit_sha=entry["sha"],
                filename=fpath.split("/")[-1],
            )
            indexed.append({"file": fpath, "config_id": cfg_id})
        except Exception as e:
            logger.warning(f"Sync failed for {row.repo}/{fpath}: {e}")
            errors.append({"file": fpath, "error": str(e)})

    row.last_synced_at = datetime.now(timezone.utc)
    row.last_sync_status = "error" if errors and not indexed else "ok"
    row.last_sync_message = (
        f"{len(indexed)} indexed, {len(skipped)} skipped, {len(errors)} errors"
    )
    await db.commit()

    return {
        "repo": row.repo,
        "indexed": indexed,
        "skipped": skipped,
        "errors": errors,
        "summary": {
            "indexed": len(indexed),
            "skipped": len(skipped),
            "errors": len(errors),
        },
    }


# ─── Gitea Discovery (each repo = one substation's RTAC) ─────────────────

@router.get("/gitea/repos", tags=["Gitea Discovery"])
async def list_gitea_repos(
    owner: Optional[str] = Query(None, description="Gitea user/org (defaults to configured gitea_owner)"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    List Gitea repositories for SCADA Mapping. Each repo represents one
    substation's RTAC configuration.

    Returns repos plus, for each, the latest indexed RtacConfig (if any)
    so the UI can show which substations have already been parsed.
    """
    from api.gitea_client import list_repos, get_effective_gitea
    from sqlalchemy import select, func
    from models import RtacConfig

    effective_owner = owner or get_effective_gitea().get("owner") or None
    try:
        repos = await list_repos(owner=effective_owner, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gitea unreachable: {e}")

    # Look up most recent indexed config per repo (single query)
    full_names = [r["full_name"] for r in repos if r.get("full_name")]
    indexed_map: dict[str, dict] = {}
    if full_names:
        latest_subq = (
            select(
                RtacConfig.repo,
                func.max(RtacConfig.parsed_at).label("latest"),
            )
            .where(RtacConfig.repo.in_(full_names))
            .group_by(RtacConfig.repo)
            .subquery()
        )
        rows = (
            await db.execute(
                select(RtacConfig).join(
                    latest_subq,
                    (RtacConfig.repo == latest_subq.c.repo)
                    & (RtacConfig.parsed_at == latest_subq.c.latest),
                )
            )
        ).scalars().all()
        for c in rows:
            indexed_map[c.repo] = {
                "config_id": c.id,
                "file_path": c.file_path,
                "commit_sha": c.commit_sha,
                "parsed_at": c.parsed_at.isoformat() if c.parsed_at else None,
            }

    for r in repos:
        r["indexed"] = indexed_map.get(r["full_name"])

    return {"owner": effective_owner, "count": len(repos), "repos": repos}


@router.post("/gitea/repos/{owner}/{name}/sync", tags=["Gitea Discovery"])
async def sync_gitea_repo(
    owner: str,
    name: str,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """
    On-demand sync for a discovered Gitea repo. Walks the repo recursively
    for *.xml and indexes each into RtacConfig. No prior registration needed.
    """
    import logging
    from sqlalchemy import select
    from models import RtacConfig
    from api.gitea_client import list_repo_files, fetch_file_from_gitea

    logger = logging.getLogger(__name__)
    full_name = f"{owner}/{name}"

    # Resolve default branch using effective Gitea config (DB → env)
    from api.gitea_client import get_effective_gitea
    cfg = get_effective_gitea()
    if not cfg.get("url"):
        raise HTTPException(status_code=500, detail="Gitea URL not configured")
    headers = {}
    if cfg.get("token"):
        headers["Authorization"] = f"token {cfg['token']}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            meta = await client.get(f"{cfg['url']}/api/v1/repos/{full_name}", headers=headers)
            if meta.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Repo not found: {full_name}")
            meta.raise_for_status()
            branch = meta.json().get("default_branch") or "main"
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Resolve branch failed for {full_name}")
        raise HTTPException(status_code=502, detail=f"Gitea branch lookup failed: {type(e).__name__}: {e}")

    try:
        files = await list_repo_files(full_name, path_prefix="", ref=branch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gitea list failed: {e}")

    indexed: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    for entry in files:
        fpath = entry["path"]
        try:
            existing = (
                await db.execute(
                    select(RtacConfig)
                    .where(RtacConfig.repo == full_name)
                    .where(RtacConfig.file_path == fpath)
                    .where(RtacConfig.commit_sha == entry["sha"])
                )
            ).scalar_one_or_none()
            if existing and not force:
                skipped.append({"file": fpath, "config_id": existing.id})
                continue
            content = await fetch_file_from_gitea(full_name, fpath, ref=branch)
            cfg_id = await index_config(
                db,
                content,
                repo=full_name,
                file_path=fpath,
                commit_sha=entry["sha"],
                filename=fpath.split("/")[-1],
            )
            indexed.append({"file": fpath, "config_id": cfg_id})
        except Exception as e:
            logger.exception(f"Sync failed for {full_name}/{fpath}")
            errors.append({"file": fpath, "error": f"{type(e).__name__}: {e}"})
            # Roll back any partial work so the session stays usable for the next file
            try:
                await db.rollback()
            except Exception:
                pass

    try:
        await db.commit()
    except Exception as e:
        logger.exception(f"Final commit failed for {full_name}")
        try:
            await db.rollback()
        except Exception:
            pass
        errors.append({"file": "<commit>", "error": f"{type(e).__name__}: {e}"})

    return {
        "repo": full_name,
        "branch": branch,
        "indexed": indexed,
        "skipped": skipped,
        "errors": errors,
        "summary": {"indexed": len(indexed), "skipped": len(skipped), "errors": len(errors)},
    }


# ─── Gitea Connection Config ───────────────────────────────────────────────
class GiteaConfigIn(BaseModel):
    url: Optional[str] = None
    token: Optional[str] = None  # "" means clear; None/omitted means leave unchanged
    default_owner: Optional[str] = None


@router.get("/gitea/config", tags=["Gitea Discovery"])
async def get_gitea_config(db: AsyncSession = Depends(get_db)):
    """Return current Gitea connection settings (token is never returned in plaintext)."""
    from models import GiteaConnection
    from sqlalchemy import select
    from api.gitea_client import get_effective_gitea
    from config import get_settings

    row = (await db.execute(select(GiteaConnection).where(GiteaConnection.id == 1))).scalar_one_or_none()
    eff = get_effective_gitea()
    s = get_settings()
    return {
        "effective": {
            "url": eff["url"],
            "owner": eff["owner"],
            "token_set": bool(eff["token"]),
        },
        "stored": {
            "url": row.url if row else None,
            "default_owner": row.default_owner if row else None,
            "token_set": bool(row.token) if row else False,
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        },
        "env_defaults": {
            "url": s.gitea_url,
            "owner": s.gitea_owner,
            "token_set": bool(s.gitea_token),
        },
    }


@router.put("/gitea/config", tags=["Gitea Discovery"])
async def put_gitea_config(body: GiteaConfigIn, db: AsyncSession = Depends(get_db)):
    """Update stored Gitea connection settings.

    - `url`: set to a value to override env. Pass empty string to clear.
    - `token`: omit/null to leave unchanged. Empty string clears.
    - `default_owner`: empty string clears.
    """
    from models import GiteaConnection
    from sqlalchemy import select
    from api.gitea_client import refresh_gitea_cache

    row = (await db.execute(select(GiteaConnection).where(GiteaConnection.id == 1))).scalar_one_or_none()
    if row is None:
        row = GiteaConnection(id=1)
        db.add(row)

    if body.url is not None:
        row.url = body.url.strip().rstrip("/") or None
    if body.token is not None:
        row.token = body.token or None
    if body.default_owner is not None:
        row.default_owner = body.default_owner.strip() or None

    await db.commit()
    await refresh_gitea_cache()
    # Return the same shape as GET
    return await get_gitea_config(db)  # type: ignore[arg-type]


@router.post("/gitea/config/test", tags=["Gitea Discovery"])
async def test_gitea_config(body: GiteaConfigIn | None = None, db: AsyncSession = Depends(get_db)):
    """Probe the Gitea instance. Body is optional; if provided, those values
    override the saved/env config for this test only (token left unchanged
    if omitted)."""
    from api.gitea_client import get_effective_gitea, test_connection

    cfg = get_effective_gitea()
    if body is not None:
        if body.url is not None:
            cfg["url"] = (body.url.strip().rstrip("/") or "")
        if body.token is not None:
            cfg["token"] = body.token or ""
        if body.default_owner is not None:
            cfg["owner"] = body.default_owner.strip() or ""
    return await test_connection(cfg)
