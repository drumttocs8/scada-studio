"""
Points List Generator — generates structured points lists from parsed RTAC XML.

Adapted from rtac-plg/src/generate_points_list.py and generate_points_by_device.py.
Returns data directly (no filesystem I/O) for API use.
"""

import csv
import io
import json
from typing import List, Dict

from fastapi.responses import JSONResponse, StreamingResponse

from rtac_plg.parser import parse_rtac_xml_bytes

# Default schema columns when no schema file is provided
DEFAULT_COLUMNS = [
    {"field": "name", "title": "Tag Name"},
    {"field": "address", "title": "Address"},
    {"field": "type", "title": "Point Type"},
    {"field": "data_type", "title": "Data Type"},
    {"field": "description", "title": "Description"},
    {"field": "source_tag", "title": "Source"},
    {"field": "destination_tag", "title": "Destination"},
    {"field": "map_name", "title": "Map Name"},
    {"field": "_source_file", "title": "Source File"},
]

# Default data-type → point-type mapping
DEFAULT_TYPE_MAP: Dict[str, str] = {
    "MV": "AI",
    "CMV": "AI",
    "INT": "AI",
    "SPS": "BI",
    "BOOL": "BI",
    "BCR": "CT",
    "DPS": "BI",
    "INS": "AI",
    "APC": "AO",
    "INC": "AO",
    "SPC": "BO",
    "DPC": "BO",
}


def _map_point_type(point: Dict) -> str:
    """Derive point type from data_type using the default mapping."""
    dt = point.get("data_type", "") or point.get("type", "")
    return DEFAULT_TYPE_MAP.get(dt.upper(), dt)


def _map_rows(points: List[Dict], columns: List[Dict] | None = None) -> List[Dict]:
    """Map raw point dicts to schema-defined column structure."""
    cols = columns or DEFAULT_COLUMNS
    rows = []
    for p in points:
        row = {}
        for c in cols:
            field = c["field"]
            title = c.get("title", field)
            row[title] = p.get(field, "")
        # Derive point type if missing
        if not row.get("Point Type"):
            row["Point Type"] = _map_point_type(p)
        rows.append(row)
    return rows


def generate(
    xml_bytes: bytes,
    filename: str = "upload.xml",
    output_format: str = "json",
    columns: List[Dict] | None = None,
):
    """
    Parse RTAC XML and return a points list.

    Args:
        xml_bytes: raw XML content
        filename: original filename (for metadata)
        output_format: "json" or "csv"
        columns: optional schema columns override

    Returns:
        FastAPI response (JSON or streaming CSV)
    """
    _, points = parse_rtac_xml_bytes(xml_bytes, filename)
    rows = _map_rows(points, columns)

    if output_format == "csv":
        if not rows:
            return StreamingResponse(
                io.StringIO(""),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
            )

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        buf.seek(0)

        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
        )

    return JSONResponse(content={
        "filename": filename,
        "point_count": len(rows),
        "points": rows,
    })
