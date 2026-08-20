"""
API routes — ties together all plugin modules.
"""

import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pydantic import BaseModel, Field

from database import get_db
from rtac_plg.parser import parse_rtac_xml_bytes, extract_points
from rag.indexer import index_config, index_repo_snapshot
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
    rtu_name: Optional[str] = Query(
        None,
        description=(
            "RTAC host identifier. Without it no cim:RemoteUnit is emitted for "
            "the controller itself, so the graph validator has nothing to match "
            "the host against and artifacts have no mRID to link to."
        ),
    ),
    eq_model_urn: Optional[str] = Query(None, description="URN of the dependent EQ profile"),
    format: str = Query("xml", regex="^(xml|json)$"),
):
    """
    Upload RTAC XML → generate SC (SCADA Configuration) CIM profile.

    Returns CIM-compliant RDF/XML containing:
    - cim:RemoteUnit for the RTAC host (when `rtu_name` is given) and for each
      device it talks to
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
            rtu_name=rtu_name,
            eq_model_urn=eq_model_urn,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to generate SC profile: {e}")

    if format == "json":
        return {
            "substation": substation_name,
            "profile": "SC",
            "model_urn": stats["model_urn"],
            "rtu_mrid": stats.get("rtu_mrid"),
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


@router.get("/scada/rtu-mrid", tags=["CIM Profiles"])
async def resolve_rtu_mrid(
    substation_name: str = Query(..., description="Substation the RTAC belongs to"),
    rtu_name: str = Query(..., description="RTAC host identifier"),
):
    """
    Resolve the SCADA-layer join key for an RTAC host.

    The mRID is deterministic, so any service *could* compute it — but three
    services reimplementing the same hash is how they quietly drift apart.
    This endpoint is the single answer: verance-artifact calls it when linking
    a config, a points list or a generated document to the controller, and
    verance-graph matches the same value when validating topology.
    """
    from rtac_plg.sc_profile import rtu_mrid

    return {
        "substation_name": substation_name,
        "rtu_name": rtu_name,
        "rtu_mrid": rtu_mrid(substation_name, rtu_name),
        "cim_class": "cim:RemoteUnit",
    }


# ─── SCADA Design Narrative ─────────────────────────────────────────────


class NarrativePromptsRequest(BaseModel):
    """Prompt-build request. The digest comes from /narrative/digest."""

    digest: dict = Field(..., description="Digest JSON from /narrative/digest")
    heading_level: int = Field(2, ge=1, le=4, description="Markdown level for section headings")
    extra_context: Optional[str] = Field(
        None, description="Site knowledge not present in the export"
    )
    only: Optional[list[str]] = Field(
        None, description="Limit to these section keys; omit for the full document"
    )


@router.post("/narrative/digest", tags=["Design Narrative"])
async def build_narrative_digest(
    file: UploadFile = File(..., description="Zipped RTAC project export"),
    project_name: Optional[str] = Query(None, description="Overrides the export folder name"),
):
    """
    Zipped RTAC export → narrative digest JSON.

    Condenses the whole export (hundreds of files, hundreds of MB) into a
    bounded fact base: interfaces and their settings, point inventories,
    resolved signal chains with direction, user logic, and revision history.

    Credentials found in the export — relay passwords, SNMP community
    strings, DNP authentication keys — are redacted here, so the digest is
    safe to pass to an external LLM.
    """
    from rtac_plg.narrative_digest import build_digest_from_zip

    content = await file.read()
    try:
        return build_digest_from_zip(content, project_name)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to build digest: {e}")


@router.post("/narrative/prompts", tags=["Design Narrative"])
async def build_narrative_prompts(body: NarrativePromptsRequest):
    """
    Digest → one self-contained LLM prompt per document section.

    Each prompt carries only the slice of the digest its section needs, so a
    caller can fan them out across parallel completions and concatenate the
    results in the returned order. The document header is assembled from
    facts rather than generated.
    """
    from rtac_plg.narrative_prompts import build_all_prompts, document_header

    try:
        prompts = build_all_prompts(
            body.digest,
            heading_level=body.heading_level,
            extra_context=body.extra_context,
            only=body.only,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to build prompts: {e}")

    return {
        "project": body.digest.get("project", {}).get("name", ""),
        "header": document_header(body.digest),
        "section_count": len(prompts),
        "sections": prompts,
    }


class NarrativeDocxRequest(BaseModel):
    """Render request for the assembled narrative."""

    markdown: str = Field(..., description="Assembled narrative Markdown, header block included")
    title: Optional[str] = Field(None, description="Overrides the title parsed from the leading H1")
    subtitle: Optional[str] = Field(None, description="Overrides the parsed subtitle")
    filename: Optional[str] = Field(None, description="Download filename, without extension")


@router.post("/narrative/docx", tags=["Design Narrative"])
async def render_narrative_docx_endpoint(body: NarrativeDocxRequest):
    """
    Assembled narrative Markdown → formatted Word document.

    The LLM writes Markdown because that is what it is reliably good at and
    because a plain-text intermediate stays diffable; this renders it for
    delivery. Tables get repeating shaded header rows, banded body rows and
    width allocated by content, so a point list that runs several pages stays
    readable.
    """
    from fastapi.responses import Response
    from rtac_plg.narrative_docx import render_narrative_docx

    try:
        payload = render_narrative_docx(
            body.markdown,
            title=body.title,
            subtitle=body.subtitle,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to render document: {e}")

    stem = body.filename or (body.title or "SCADA_Design_Narrative").replace(" ", "_")
    return Response(
        content=payload,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={"Content-Disposition": f'attachment; filename="{stem}.docx"'},
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
    touched_xml: set[str] = set()

    for commit in payload.commits:
        # Skip bot commits to prevent infinite webhook loops
        if "SCADA Studio Bot" in commit.message or "[bot]" in commit.message:
            logger.info(f"Skipping bot commit: {commit.message[:60]}")
            continue

        xml_files = [
            f for f in commit.added + commit.modified
            if f.startswith("xml/") and f.endswith(".xml")
        ]

        # Indexing is per-repo, not per-file: a substation's devices are spread
        # across many files, and the topology validator needs all of them in one
        # config. Handled once after this loop.
        touched_xml.update(xml_files)

        for fpath in xml_files:
            try:
                content = await fetch_file_from_gitea(repo, fpath, commit_sha)

                # Generate SC profile from RTAC XML
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

    # Re-index the whole xml/ tree as one config whenever any of it changed.
    # Indexing only the changed files would leave a config describing a
    # fraction of the substation, which the validator would read as devices
    # having been removed.
    snapshot = None
    if touched_xml:
        try:
            from api.gitea_client import list_repo_files

            entries = await list_repo_files(repo, path_prefix="xml/", ref=commit_sha)
            files = [
                (e["path"], await fetch_file_from_gitea(repo, e["path"], ref=commit_sha))
                for e in entries
            ]
            xml_tree_sha256 = None
            try:
                raw = await fetch_file_from_gitea(repo, "active.json", ref=commit_sha)
                xml_tree_sha256 = json.loads(raw.decode("utf-8")).get("xml_tree_sha256")
            except Exception:
                pass
            snapshot = await index_repo_snapshot(
                db, repo=repo, commit_sha=commit_sha,
                files=files, xml_tree_sha256=xml_tree_sha256,
            )
            indexed.append({"snapshot": snapshot})
        except Exception as e:
            logger.exception(f"Snapshot index failed for {repo}@{commit_sha}")
            try:
                await db.rollback()
            except Exception:
                pass
            indexed.append({"snapshot_error": f"{type(e).__name__}: {e}"})

    return {
        "repo": repo,
        "commit": commit_sha,
        "indexed": indexed,
        "snapshot": snapshot,
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


@router.get("/node-config", tags=["LLM API"])
async def config_for_graph_node(
    node_uri: str = Query(..., description="Graph node URI or mRID"),
    substation: Optional[str] = Query(None, description="Narrow to one substation"),
    q: Optional[str] = Query(None, description="Filter returned points by text"),
    top_k: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Grounding for GraphRAG: what does the RTAC config say about THIS node?

    A retrieval layer that silently returns nothing is the worst possible
    behaviour here, because "no config data" and "this device is missing from
    the config" are the same empty list but opposite conclusions -- the second
    is a drift finding the engineer needs to see. So this never returns a bare
    empty result: `status` always says which of the two it is, and `message`
    says it in words the calling model can quote.

      not_mapped   node has no device mapping yet
      no_config    mapped, but no RTAC config is indexed for it
      not_in_config  mapped to a device the current config does not contain
      no_points    device is in the config but has no points mapped
      ok           points found

    It answers in every case rather than refusing when something is invalid.
    Blocking on invalid state would hide exactly the drift the graph exists to
    catch; callers that want strictness can act on `status` themselves.
    """
    from sqlalchemy import select, or_
    from models import RtacConfig, DeviceMapping, Point

    def envelope(status: str, message: str, **extra):
        body = {
            "node_uri": node_uri,
            "status": status,
            "message": message,
            "has_config_data": status == "ok",
            "mapping": None,
            "config": None,
            "device": None,
            "point_count": 0,
            "points": [],
        }
        body.update(extra)
        return body

    # ── 1. Node -> device mapping. Accept a URI from any profile. ──
    stmt = select(DeviceMapping).where(
        or_(
            DeviceMapping.eq_uri == node_uri,
            DeviceMapping.sc_device_uri == node_uri,
            DeviceMapping.pe_relay_uri == node_uri,
        )
    )
    if substation:
        stmt = stmt.where(DeviceMapping.substation == substation)
    mapping = (await db.execute(stmt)).scalars().first()

    if mapping is None:
        return envelope(
            "not_mapped",
            f"No RTAC device is mapped to node {node_uri!r}"
            + (f" in substation {substation!r}" if substation else "")
            + ". Map it on the SCADA Mapping tab before asking about its "
              "configuration. This means the link is missing, not that the "
              "device is absent from the RTAC config.",
        )

    map_info = {
        "id": mapping.id,
        "substation": mapping.substation,
        "eq_name": mapping.eq_name,
        "sc_device_name": mapping.sc_device_name,
        "sc_map_name": mapping.sc_map_name,
        "confidence": mapping.confidence,
        "source": mapping.source,
    }

    # ── 2. Resolve the config: the one recorded on the mapping, else the
    #       substation's current snapshot. ──
    config = None
    if mapping.config_id:
        config = (await db.execute(
            select(RtacConfig).where(RtacConfig.id == mapping.config_id)
        )).scalar_one_or_none()
    if config is None:
        candidates = (await db.execute(
            select(RtacConfig).order_by(RtacConfig.parsed_at.desc()).limit(50)
        )).scalars().all()
        sub = (mapping.substation or "").lower()
        config = next(
            (c for c in candidates
             if ((c.metadata_ or {}).get("substation") or "").lower() == sub),
            None,
        )

    if config is None:
        return envelope(
            "no_config",
            f"Node {node_uri!r} is mapped to RTAC device "
            f"{mapping.sc_map_name or mapping.sc_device_name!r}, but no RTAC "
            f"configuration is indexed for substation {mapping.substation!r}. "
            f"Sync the substation's repo on the SCADA Mapping tab.",
            mapping=map_info,
        )

    meta = config.metadata_ or {}
    config_info = {
        "config_id": config.id,
        "repo": config.repo,
        "commit_sha": config.commit_sha,
        "substation": meta.get("substation"),
        "device_count": meta.get("device_count"),
        "point_count": meta.get("point_count"),
        "citation_url": _gitea_blob_url(config.repo, config.file_path, config.commit_sha),
    }

    # ── 3. Locate the device inside that config. ──
    target = (mapping.sc_map_name or mapping.sc_device_name or "").strip()
    device = next(
        (d for d in meta.get("devices", [])
         if target and target.lower() in {
             str(d.get("map_name", "")).lower(),
             str(d.get("device_name", "")).lower(),
             str(d.get("name", "")).lower(),
         }),
        None,
    )

    if device is None:
        # Mapped to something the config no longer has: real drift, not absence.
        return envelope(
            "not_in_config",
            f"Node {node_uri!r} is mapped to RTAC device {target!r}, but that "
            f"device is NOT present in the current config for "
            f"{meta.get('substation')!r} (commit {config.commit_sha[:8]}, "
            f"{meta.get('device_count', 0)} devices). Either the device was "
            f"removed from the RTAC config or the mapping is stale -- this is a "
            f"drift finding, not missing data.",
            mapping=map_info,
            config=config_info,
            available_devices=[
                d.get("map_name") or d.get("device_name") for d in meta.get("devices", [])
            ][:50],
        )

    device_info = {
        "name": device.get("device_name") or device.get("name"),
        "map_name": device.get("map_name"),
        "role": device.get("role"),
        "protocol": device.get("protocol"),
        "manufacturer": device.get("manufacturer"),
        "model": device.get("model"),
        "connection_type": device.get("connection_type"),
        "source_file": device.get("_source_file"),
    }

    # ── 4. Points belonging to that device. ──
    pstmt = select(Point).where(Point.config_id == config.id)
    if q:
        like = f"%{q}%"
        pstmt = pstmt.where(
            or_(Point.name.ilike(like), Point.description.ilike(like))
        )
    all_points = (await db.execute(pstmt)).scalars().all()

    names = {v for v in (device.get("map_name"), device.get("device_name"),
                         device.get("name")) if v}
    lowered = {n.lower() for n in names}
    points = [
        p for p in all_points
        if str((p.extra or {}).get("map_name", "")).lower() in lowered
        or any(str(p.name or "").lower().startswith(n + ".") for n in lowered)
    ]

    if not points:
        return envelope(
            "no_points",
            f"RTAC device {device_info['name']!r} "
            f"({device_info['protocol']}, {device_info['role']}) exists in the "
            f"config for {meta.get('substation')!r}, but has no points mapped to "
            f"it"
            + (f" matching {q!r}" if q else "")
            + ". For a DNP server this usually means no outstation point map is "
              "assigned; for a client it means no tags are enabled. The device "
              "is configured, its point list is empty.",
            mapping=map_info,
            config=config_info,
            device=device_info,
        )

    return envelope(
        "ok",
        f"{len(points)} point(s) configured on RTAC device "
        f"{device_info['name']!r} for node {node_uri!r}.",
        mapping=map_info,
        config=config_info,
        device=device_info,
        point_count=len(points),
        points=[
            {
                "name": p.name,
                "address": p.address,
                "point_type": p.point_type,
                "data_type": p.data_type,
                "description": p.description,
                "source_tag": p.source_tag,
                "destination_tag": p.destination_tag,
            }
            for p in points[:top_k]
        ],
    )


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
    from api.gitea_client import list_repos, get_effective_gitea, GiteaAuthError
    from sqlalchemy import select, func
    from models import RtacConfig

    # No owner means every repo the token can see, which is the normal case:
    # substations are pushed by whichever engineer did the work.
    effective_owner = owner or get_effective_gitea().get("owner") or None
    try:
        repos = await list_repos(owner=effective_owner, limit=limit)
    except GiteaAuthError as e:
        # 401, not 502 — the instance answered fine, it refused our credentials.
        raise HTTPException(status_code=401, detail=str(e))
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
    head_sha = None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            meta = await client.get(f"{cfg['url']}/api/v1/repos/{full_name}", headers=headers)
            if meta.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Repo not found: {full_name}")
            meta.raise_for_status()
            branch = meta.json().get("default_branch") or "main"
            # The snapshot is identified by the branch head, not by per-file
            # blob shas, because the config being indexed is the whole tree.
            br = await client.get(f"{cfg['url']}/api/v1/repos/{full_name}/branches/{branch}", headers=headers)
            if br.status_code == 200:
                head_sha = (br.json().get("commit") or {}).get("id")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Resolve branch failed for {full_name}")
        raise HTTPException(status_code=502, detail=f"Gitea branch lookup failed: {type(e).__name__}: {e}")

    # Config repos put the active RTAC export under xml/. Other folders hold
    # XML that is emphatically not an RTAC config — cim/ holds a CIM RDF
    # profile, which the parser would happily index as a config with zero
    # devices and zero points. Prefer xml/, and only fall back to a whole-repo
    # walk (minus cim/) for repos predating the layout.
    try:
        files = await list_repo_files(full_name, path_prefix="xml/", ref=branch)
        if not files:
            files = [
                f
                for f in await list_repo_files(full_name, path_prefix="", ref=branch)
                if not f["path"].lower().startswith("cim/")
            ]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gitea list failed: {e}")

    snapshot_sha = head_sha or branch

    # Already at this commit? Nothing to do.
    if not force:
        existing = (
            await db.execute(
                select(RtacConfig)
                .where(RtacConfig.repo == full_name)
                .where(RtacConfig.commit_sha == snapshot_sha)
                .where(RtacConfig.file_path == "xml/")
            )
        ).scalar_one_or_none()
        if existing:
            meta = existing.metadata_ or {}
            return {
                "repo": full_name,
                "branch": branch,
                "commit_sha": snapshot_sha,
                "config_id": existing.id,
                "skipped": True,
                "summary": {
                    "devices": meta.get("device_count", 0),
                    "points": meta.get("point_count", 0),
                    "files_parsed": meta.get("file_count", 0),
                },
            }

    # Fetch every file, then index the tree as one config. A substation's
    # devices are spread across many files; only the whole set is meaningful
    # to diff against a graph model.
    errors: list[dict] = []
    payload: list[tuple[str, bytes]] = []
    for entry in files:
        fpath = entry["path"]
        try:
            payload.append((fpath, await fetch_file_from_gitea(full_name, fpath, ref=branch)))
        except Exception as e:
            logger.exception(f"Fetch failed for {full_name}/{fpath}")
            errors.append({"file": fpath, "error": f"{type(e).__name__}: {e}"})

    if not payload:
        raise HTTPException(
            status_code=502,
            detail=f"No XML could be fetched from {full_name}: {errors[:3]}",
        )

    # Read the tree fingerprint the pusher recorded, when present. It changes
    # exactly when the config does, so it is the honest identity for a
    # snapshot; the commit sha also moves for unrelated edits (README, etc).
    xml_tree_sha256 = None
    try:
        raw = await fetch_file_from_gitea(full_name, "active.json", ref=branch)
        xml_tree_sha256 = json.loads(raw.decode("utf-8")).get("xml_tree_sha256")
    except Exception:
        pass  # Pre-dates active.json, or repo does not use scada-push.

    try:
        result = await index_repo_snapshot(
            db,
            repo=full_name,
            commit_sha=snapshot_sha,
            files=payload,
            xml_tree_sha256=xml_tree_sha256,
        )
    except Exception as e:
        logger.exception(f"Snapshot index failed for {full_name}")
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Indexing failed: {type(e).__name__}: {e}")

    errors.extend(result.get("errors") or [])
    return {
        "repo": full_name,
        "branch": branch,
        "commit_sha": snapshot_sha,
        "xml_tree_sha256": xml_tree_sha256,
        "config_id": result["config_id"],
        "replaced_configs": result["replaced"],
        "errors": errors,
        "summary": {
            "devices": result["devices"],
            "points": result["points"],
            "files_parsed": result["files_parsed"],
            "errors": len(errors),
        },
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
