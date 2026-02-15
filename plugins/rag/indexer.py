"""
RAG Indexer — parses RTAC XML, chunks it, and stores embeddings in pgvector.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import RtacConfig, Point, Embedding
from rtac_plg.parser import parse_rtac_xml_bytes, extract_points
from rag.embedder import embed_texts


def chunk_config(
    devices: list[dict], points: list[dict], filename: str
) -> list[dict]:
    """
    Break a parsed RTAC config into searchable text chunks.

    Chunking strategy:
    - 1 chunk per device (device name + metadata)
    - 1 chunk per group of points (batched by device / source file)
    - 1 summary chunk for the whole config
    """
    chunks = []

    # Summary chunk
    device_names = [d.get("name", "unknown") for d in devices]
    summary = (
        f"RTAC config '{filename}' with {len(devices)} device(s): "
        f"{', '.join(device_names)}. "
        f"Total points: {len(points)}."
    )
    chunks.append({"text": summary, "type": "config"})

    # Per-device chunks
    for dev in devices:
        dev_text = f"Device: {dev.get('name', 'unknown')}"
        if dev.get("type"):
            dev_text += f" (type: {dev['type']})"
        if dev.get("protocol"):
            dev_text += f", protocol: {dev['protocol']}"
        chunks.append({"text": dev_text, "type": "device"})

    # Point chunks (batch ~20 points per chunk to keep size reasonable)
    BATCH_SIZE = 20
    for i in range(0, len(points), BATCH_SIZE):
        batch = points[i : i + BATCH_SIZE]
        lines = []
        for p in batch:
            line = p.get("name", "?")
            if p.get("type"):
                line += f" [{p['type']}]"
            if p.get("address"):
                line += f" @{p['address']}"
            if p.get("description"):
                line += f" — {p['description']}"
            lines.append(line)
        chunk_text = f"Points from '{filename}':\n" + "\n".join(lines)
        chunks.append({"text": chunk_text, "type": "point"})

    return chunks


async def index_config(
    db: AsyncSession,
    xml_bytes: bytes,
    repo: str,
    file_path: str,
    commit_sha: str,
    filename: str,
) -> int:
    """
    Parse an RTAC XML file, store points and embeddings.
    Returns the config_id.
    """
    # Check if already indexed
    existing = await db.execute(
        select(RtacConfig).where(
            RtacConfig.repo == repo,
            RtacConfig.file_path == file_path,
            RtacConfig.commit_sha == commit_sha,
        )
    )
    if row := existing.scalar_one_or_none():
        return row.id

    # Parse XML
    devices, points = parse_rtac_xml_bytes(xml_bytes, filename=filename)

    # Store config record
    config = RtacConfig(
        repo=repo,
        file_path=file_path,
        commit_sha=commit_sha,
        device_name=devices[0].get("name") if devices else None,
        metadata_={"device_count": len(devices), "point_count": len(points)},
    )
    db.add(config)
    await db.flush()  # get config.id

    # Store points
    for p in points:
        db.add(Point(
            config_id=config.id,
            name=p.get("name", ""),
            address=p.get("address"),
            point_type=p.get("type"),
            data_type=p.get("data_type"),
            description=p.get("description"),
            source_tag=p.get("source_tag"),
            destination_tag=p.get("destination_tag"),
            extra={k: v for k, v in p.items()
                   if k not in ("name", "address", "type", "data_type",
                                "description", "source_tag", "destination_tag")},
        ))

    # Generate and store embeddings
    chunks = chunk_config(devices, points, filename)
    texts = [c["text"] for c in chunks]
    vectors = embed_texts(texts)

    for chunk, vec in zip(chunks, vectors):
        db.add(Embedding(
            config_id=config.id,
            chunk_text=chunk["text"],
            chunk_type=chunk["type"],
            embedding=vec,
            metadata_={"repo": repo, "file_path": file_path},
        ))

    await db.commit()
    return config.id
