"""
Similar Configs Finder — finds RTAC configurations that share structural
similarities (device types, point counts, naming patterns).

Uses SQL-based comparison of config metadata. Semantic similarity via
vector embeddings is handled by n8n workflows.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional

from api.schemas import SimilarConfigResult


async def find_similar(
    db: AsyncSession,
    config_id: Optional[int] = None,
    query_text: Optional[str] = None,
    top_k: int = 10,
) -> list[SimilarConfigResult]:
    """
    Find configs similar to a reference config by metadata overlap,
    or search by device name text.
    """
    if config_id is not None:
        # Find configs with similar device names or point counts
        sql = text("""
            SELECT
                c2.id AS config_id,
                c2.repo,
                c2.file_path,
                c2.device_name
            FROM rtac_configs c1
            JOIN rtac_configs c2 ON c2.id != c1.id
            WHERE c1.id = :cid
              AND (
                c2.device_name ILIKE '%' || SPLIT_PART(c1.device_name, '_', 1) || '%'
                OR (c2.metadata->>'device_count')::int = (c1.metadata->>'device_count')::int
              )
            LIMIT :k
        """)
        rows = await db.execute(sql, {"cid": config_id, "k": top_k})
    elif query_text:
        sql = text("""
            SELECT
                c.id AS config_id,
                c.repo,
                c.file_path,
                c.device_name
            FROM rtac_configs c
            WHERE c.device_name ILIKE :pattern
               OR c.file_path ILIKE :pattern
            LIMIT :k
        """)
        rows = await db.execute(sql, {"pattern": f"%{query_text}%", "k": top_k})
    else:
        return []

    return [
        SimilarConfigResult(
            config_id=r.config_id,
            repo=r.repo,
            file_path=r.file_path,
            score=1.0,  # placeholder — vector scoring done in n8n
            device_name=r.device_name,
        )
        for r in rows.fetchall()
    ]
