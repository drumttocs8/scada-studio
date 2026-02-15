"""
Search — text-based search across indexed RTAC configs and points.

Semantic/vector search is handled by n8n workflows. This module provides
simple SQL-based text search for the sidecar API.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from api.schemas import SearchResult


async def text_search(
    db: AsyncSession,
    query: str,
    top_k: int = 20,
) -> list[SearchResult]:
    """
    Full-text search across config metadata and point names/descriptions.
    Uses PostgreSQL ILIKE for simplicity.
    """
    pattern = f"%{query}%"

    sql = text("""
        SELECT
            c.id AS config_id,
            c.repo,
            c.file_path,
            p.name || COALESCE(' — ' || p.description, '') AS chunk_text,
            p.point_type AS chunk_type,
            c.device_name
        FROM points p
        JOIN rtac_configs c ON c.id = p.config_id
        WHERE p.name ILIKE :pattern
           OR p.description ILIKE :pattern
           OR p.source_tag ILIKE :pattern
           OR p.destination_tag ILIKE :pattern
           OR c.device_name ILIKE :pattern
        LIMIT :k
    """)

    result = await db.execute(sql, {"pattern": pattern, "k": top_k})
    rows = result.fetchall()

    return [
        SearchResult(
            config_id=r.config_id,
            repo=r.repo,
            file_path=r.file_path,
            chunk_text=r.chunk_text,
            chunk_type=r.chunk_type or "point",
        )
        for r in rows
    ]
