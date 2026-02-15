"""
RAG Search — semantic similarity search over indexed RTAC configs.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from rag.embedder import embed_texts
from api.schemas import SearchResult


async def semantic_search(
    db: AsyncSession,
    query: str,
    top_k: int = 10,
) -> list[SearchResult]:
    """
    Embed the query and find nearest-neighbor chunks in pgvector.
    Uses cosine distance via the HNSW index.
    """
    # Embed the query
    [query_vec] = embed_texts([query])

    # pgvector cosine distance operator: <=>
    sql = text("""
        SELECT
            e.config_id,
            c.repo,
            c.file_path,
            e.chunk_text,
            e.chunk_type,
            1 - (e.embedding <=> :qvec::vector) AS score,
            e.metadata AS meta
        FROM embeddings e
        JOIN rtac_configs c ON c.id = e.config_id
        ORDER BY e.embedding <=> :qvec::vector
        LIMIT :k
    """)

    result = await db.execute(sql, {"qvec": str(query_vec), "k": top_k})
    rows = result.fetchall()

    return [
        SearchResult(
            config_id=r.config_id,
            repo=r.repo,
            file_path=r.file_path,
            chunk_text=r.chunk_text,
            chunk_type=r.chunk_type,
            score=float(r.score),
            metadata=r.meta or {},
        )
        for r in rows
    ]
