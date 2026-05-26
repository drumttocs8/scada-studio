"""
Indexer — parses RTAC XML files and stores configs + points in PostgreSQL.

Embedding/RAG search is handled externally by n8n workflows; this module
just ensures parsed data is available in the DB for queries.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import RtacConfig, Point
from rtac_plg.parser import parse_rtac_xml_bytes


async def index_config(
    db: AsyncSession,
    xml_bytes: bytes,
    repo: str,
    file_path: str,
    commit_sha: str,
    filename: str,
) -> int:
    """
    Parse an RTAC XML file and store config + points in the database.
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

    # Derive substation from repo (e.g. "scada/trinity-hills" → "trinity-hills")
    substation = repo.split("/")[-1] if "/" in repo else repo

    # Identify the RTAC host device (the one acting as both client and server
    # is usually absent — pick the first server device, else the first device).
    servers = [d for d in devices if d.get("role") == "server"]
    clients = [d for d in devices if d.get("role") == "client"]
    host_name = (
        devices[0].get("name") if devices else None
    )

    # Store config record (devices captured in metadata for LLM / validator use)
    config = RtacConfig(
        repo=repo,
        file_path=file_path,
        commit_sha=commit_sha,
        device_name=host_name,
        metadata_={
            "substation": substation,
            "device_count": len(devices),
            "point_count": len(points),
            "server_count": len(servers),
            "client_count": len(clients),
            "devices": devices,
        },
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

    await db.commit()
    return config.id
