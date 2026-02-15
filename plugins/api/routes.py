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
    Finds XML files in the commit and indexes them automatically.
    Skips commits made by the bot itself (prevents infinite loops).
    """
    import json as json_mod
    import logging

    logger = logging.getLogger(__name__)

    repo = payload.repository.full_name
    commit_sha = payload.after

    indexed = []
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
                config_id = await index_config(
                    db, content, repo=repo, file_path=fpath,
                    commit_sha=commit_sha, filename=fpath,
                )
                indexed.append({"file": fpath, "config_id": config_id})
            except Exception as e:
                logger.warning(f"Failed to index {fpath}: {e}")
                indexed.append({"file": fpath, "error": str(e)})

        # Auto-generate points list if XML files in xml/ were modified
        if xml_files:
            try:
                # Fetch all XML files from the xml/SEL_RTAC/ directory
                # and generate a points list, then commit it back
                logger.info(f"XML files changed in {repo}, generating points list...")
                # This will be handled asynchronously — the scada-push script
                # already generates and commits points lists locally.
                # The sidecar's role is to index for search, not regenerate.
            except Exception as e:
                logger.warning(f"Points list generation skipped: {e}")

    return {"repo": repo, "commit": commit_sha, "indexed": indexed}
