"""
Similar Configs Finder — finds RTAC configurations that are structurally
or semantically similar to a given config.

Uses pgvector embeddings to compute cosine similarity between config-level
summary chunks, then ranks by score.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional

from rag.embedder import embed_texts
from api.schemas import SimilarConfigResult


async def find_similar(
    db: AsyncSession,
    config_id: Optional[int] = None,
    query_text: Optional[str] = None,
    top_k: int = 10,
) -> list[SimilarConfigResult]:
    """
    Find configs similar to a reference config or free-text query.

    Exactly one of config_id or query_text must be provided.
    """
    if config_id is not None:
        # Get the summary embedding for this config
        row = await db.execute(
            text("""
                SELECT embedding
                FROM embeddings
                WHERE config_id = :cid AND chunk_type = 'config'
                LIMIT 1
            """),
            {"cid": config_id},
        )
        result = row.fetchone()
        if result is None:
            return []
        query_vec = result.embedding
    elif query_text:
        [query_vec] = embed_texts([query_text])
    else:
        return []

    sql = text("""
        SELECT DISTINCT ON (c.id)
            c.id        AS config_id,
            c.repo,
            c.file_path,
            c.device_name,
            1 - (e.embedding <=> :qvec::vector) AS score
        FROM embeddings e
        JOIN rtac_configs c ON c.id = e.config_id
        WHERE e.chunk_type = 'config'
          AND (:exclude_id IS NULL OR c.id != :exclude_id)
        ORDER BY c.id, e.embedding <=> :qvec::vector
        LIMIT :k
    """)

    rows = await db.execute(
        sql,
        {"qvec": str(query_vec), "exclude_id": config_id, "k": top_k},
    )

    # Re-sort by score descending (DISTINCT ON requires ORDER BY on c.id first)
    results = sorted(
        [
            SimilarConfigResult(
                config_id=r.config_id,
                repo=r.repo,
                file_path=r.file_path,
                score=float(r.score),
                device_name=r.device_name,
            )
            for r in rows.fetchall()
        ],
        key=lambda x: x.score,
        reverse=True,
    )

    return results
