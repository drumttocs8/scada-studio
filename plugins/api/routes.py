"""
API routes — ties together all plugin modules.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

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
