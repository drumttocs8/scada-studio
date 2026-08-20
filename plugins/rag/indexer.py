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


# Files that carry no device or point data. They parse fine and would each
# become an empty config, cluttering the picker with entries that can only
# produce a wrong validation result.
_NON_DEVICE_FILES = (
    "navigator layout.xml",
    "project info.xml",
    "project information.xml",
)


async def index_repo_snapshot(
    db: AsyncSession,
    repo: str,
    commit_sha: str,
    files: list[tuple[str, bytes]],
    xml_tree_sha256: str | None = None,
) -> dict:
    """
    Index a whole config repo as ONE config: a substation's active state.

    A repo holds one substation's RTAC export spread over many XML files —
    one per IED, plus System and Tag Processor. Indexing each file separately
    yields configs holding a single device, and the topology validator diffs a
    config's devices against a whole substation model, so a per-file config
    reports every other device as missing. The unit that means something is
    the repo at a commit, so that is what gets stored.

    Replaces any previous configs for `repo` — `xml/` is the active state, and
    a substation has exactly one. Points cascade on delete.
    """
    from sqlalchemy import delete

    all_devices: list[dict] = []
    all_points: list[dict] = []
    parsed_files: list[str] = []
    failed: list[dict] = []

    for path, content in files:
        if path.rsplit("/", 1)[-1].lower() in _NON_DEVICE_FILES:
            continue
        try:
            devices, points = parse_rtac_xml_bytes(content, filename=path.split("/")[-1])
        except Exception as e:
            failed.append({"file": path, "error": f"{type(e).__name__}: {e}"})
            continue
        for d in devices:
            d.setdefault("_source_file", path)
        all_devices.extend(devices)
        all_points.extend(points)
        parsed_files.append(path)

    substation = repo.split("/")[-1] if "/" in repo else repo
    servers = [d for d in all_devices if d.get("role") == "server"]
    clients = [d for d in all_devices if d.get("role") == "client"]

    # Drop prior versions of this substation before inserting the new one.
    old_ids = (
        await db.execute(select(RtacConfig.id).where(RtacConfig.repo == repo))
    ).scalars().all()
    if old_ids:
        await db.execute(delete(RtacConfig).where(RtacConfig.id.in_(old_ids)))

    config = RtacConfig(
        repo=repo,
        file_path="xml/",  # the tree, not a single file
        commit_sha=commit_sha,
        device_name=(servers[0].get("name") if servers else None),
        metadata_={
            "substation": substation,
            "device_count": len(all_devices),
            "point_count": len(all_points),
            "server_count": len(servers),
            "client_count": len(clients),
            "devices": all_devices,
            "xml_tree_sha256": xml_tree_sha256,
            "source_files": parsed_files,
            "file_count": len(parsed_files),
            "parse_errors": failed,
        },
    )
    db.add(config)
    await db.flush()

    for p in all_points:
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
    return {
        "config_id": config.id,
        "replaced": len(old_ids),
        "files_parsed": len(parsed_files),
        "devices": len(all_devices),
        "points": len(all_points),
        "errors": failed,
    }
