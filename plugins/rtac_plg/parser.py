"""
RTAC XML Parser — adapted from rtac-plg/src/parse_rtac_xml.py for in-memory use.

Parses RTAC XML exports (from AcRTACcmd.exe) and extracts devices + point records.
Works with bytes (uploaded files or Gitea fetches) rather than filesystem paths.
"""

import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple

POINT_TAGS = {
    "point", "Point", "Tag", "tag",
    "DataPoint", "datapoint", "DevicePoint", "devicepoint",
}


def _extract_point(elem: ET.Element) -> Dict:
    """Extract a generic point record from an XML element."""
    data: Dict = {}
    for child in elem:
        tag = child.tag.lower()
        text = (child.text or "").strip()
        if tag in ("name", "id", "tag", "tagname"):
            data["name"] = text
        elif tag in ("address", "addr", "ioaddress"):
            data["address"] = text
        elif tag in ("type", "pointtype", "datatype"):
            data["type"] = text
        elif tag in ("units", "unit", "uom"):
            data["units"] = text
        elif tag in ("description", "desc"):
            data["description"] = text
        else:
            data[child.tag] = text
    return data


def _get_setting_value(row: ET.Element, column_name: str) -> str:
    for setting in row.findall("Setting"):
        col = setting.find("Column")
        val = setting.find("Value")
        if col is not None and val is not None and col.text == column_name:
            return val.text or ""
    return ""


def _parse_rtac_taglist(
    root: ET.Element, filename: str, map_name: str = ""
) -> List[Dict]:
    """Parse RTAC TagList format (DNP/Modbus device exports)."""
    points: List[Dict] = []
    for row in root.findall(".//SettingPage/Row"):
        settings = {
            s.find("Column").text: s.find("Value").text
            for s in row.findall("Setting")
            if s.find("Column") is not None and s.find("Value") is not None
        }

        if settings.get("Enable", "").lower() != "true":
            continue

        point_data: Dict = {}
        if "Tag Name" in settings:
            point_data["name"] = settings["Tag Name"]
        if "Point Number" in settings:
            point_data["address"] = settings["Point Number"]
        if "Tag Type" in settings:
            point_data["type"] = settings["Tag Type"]
        if "Comment" in settings and settings["Comment"]:
            point_data["description"] = settings["Comment"]
        if map_name:
            point_data["map_name"] = map_name

        # Extra settings
        skip = {"tag_name", "point_number", "tag_type", "comment", "enable"}
        for col, val in settings.items():
            key = col.lower().replace(" ", "_")
            if key not in skip:
                point_data[key] = val

        if point_data:
            point_data["_source_file"] = filename
            points.append(point_data)

    return points


def _parse_device(root: ET.Element, filename: str) -> Tuple[List[Dict], List[Dict]]:
    """Parse a single Device element."""
    points: List[Dict] = []
    server_devices: List[Dict] = []

    device = root.find(".//Device")
    if device is None:
        return server_devices, points

    device_name_el = device.find(".//Name")
    device_name = device_name_el.text if device_name_el is not None else filename

    connection = device.find(".//Connection")
    if connection is not None:
        protocol_el = connection.find("Protocol")
        if protocol_el is not None and protocol_el.text == "DNPServer":
            map_name = ""
            for row in connection.findall(".//Row"):
                settings_in_row = row.findall("Setting")
                if len(settings_in_row) >= 2:
                    first_col = settings_in_row[0].find("Column")
                    first_val = settings_in_row[0].find("Value")
                    if (
                        first_col is not None
                        and first_col.text == "Setting"
                        and first_val is not None
                        and first_val.text == "Map Name"
                    ):
                        second_val = settings_in_row[1].find("Value")
                        if second_val is not None:
                            map_name = second_val.text or ""
                            break

            if map_name:
                server_devices.append(
                    {"name": device_name, "map_name": map_name, "_source_file": filename}
                )

            for taglist in device.findall(".//TagList"):
                points.extend(_parse_rtac_taglist(taglist, filename, map_name))

    return server_devices, points


# ─── Public API ──────────────────────────────────────────────────────────


def parse_rtac_xml_bytes(
    xml_bytes: bytes, filename: str = "upload.xml"
) -> Tuple[List[Dict], List[Dict]]:
    """
    Parse RTAC XML from raw bytes. Returns (devices, points).

    Tries Device structure first, then TagList, then generic point extraction.
    """
    root = ET.fromstring(xml_bytes)
    return parse_rtac_xml_root(root, filename)


def parse_rtac_xml_root(
    root: ET.Element, filename: str = "upload.xml"
) -> Tuple[List[Dict], List[Dict]]:
    """Parse from an already-parsed ElementTree root."""
    # Try Device structure
    device_el = root.find(".//Device")
    if device_el is not None:
        return _parse_device(root, filename)

    # Try TagList structure
    points: List[Dict] = []
    taglists = root.findall(".//TagList")
    if taglists:
        for tl in taglists:
            points.extend(_parse_rtac_taglist(tl, filename))
        return [], points

    # Generic point extraction
    for elem in root.iter():
        if elem.tag in POINT_TAGS:
            p = _extract_point(elem)
            if "name" not in p:
                p["name"] = elem.attrib.get("name") or elem.attrib.get("id", "")
            p["_source_file"] = filename
            points.append(p)

    return [], points


def extract_points(xml_bytes: bytes, filename: str = "upload.xml") -> List[Dict]:
    """Convenience: parse and return just the points list."""
    _, points = parse_rtac_xml_bytes(xml_bytes, filename)
    return points
