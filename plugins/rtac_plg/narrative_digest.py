"""
Narrative Digest — condenses a full RTAC project export into a bounded,
LLM-consumable fact base for generating a SCADA Design Narrative.

The problem this solves: a real RTAC export is hundreds of megabytes across
hundreds of XML files (ORS1's SCADA DNP map alone is 27 MB).  None of that
fits in a context window, and most of it is boilerplate — POU pin defaults,
disabled map rows, vendor library data types.  But the parts an engineer
would actually write about — the comms interfaces and their settings, the
Tag Processor expressions, the user logic, the revision history — are small.

So this module walks the export and emits a digest JSON: everything
narrative-relevant, nothing else, with hard caps on the parts that can blow
up.  The rule that keeps it bounded and still dense is *relevance by
reference*: a point on a 20,000-row map is only carried through if the Tag
Processor or user logic mentions it, or if its device is small enough to
enumerate outright.

Stage 2 (the LLM) writes prose from this digest and never sees raw XML.
"""

import io
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

try:
    from rtac_plg.sc_profile import RTAC_TO_POINT_TYPE
except ModuleNotFoundError:  # running this file directly as a script
    from sc_profile import RTAC_TO_POINT_TYPE

# ─── Tunable caps ────────────────────────────────────────────────────────

# A device whose enabled-point count is at or below this is enumerated in
# full; above it, only referenced + sampled points survive.
FULL_ENUMERATION_LIMIT = 400

# Per-device cap on sampled (unreferenced) points, spread across data types.
SAMPLE_PER_DEVICE = 60

# Pages carrying no design intent — "POU Pin Settings" is up to ~200 rows of
# function-block plumbing that is identical across every project.
SKIP_PAGES = {"POU Pin Settings"}

# A tabular page (polls, message settings, commands) is carried verbatim if
# it is this small; larger ones fall back to a row count.
TABLE_ROW_LIMIT = 30

# Settings whose values are credentials.  RTAC exports carry these as
# encrypted blobs (relay access passwords, SNMP community strings, SSH
# passwords), but the digest is designed to be posted to an LLM API and
# stored alongside generated documents, so they are dropped at extraction
# rather than filtered downstream.  The setting *name* is kept, because
# "this link is password-protected" is itself a fact worth narrating.
SECRET_SETTING_MARKERS = (
    "password",
    "community",
    "secret",
    "passphrase",
    "certification key",
    "authentication key",
    "private key",
)

REDACTED = "<redacted>"

# Backstop for secrets whose setting name gives nothing away — RTAC stores
# them as PGP-armoured base64, which no legitimate setting value resembles.
# Name matching alone missed "Authority Certification Key", so shape is
# checked too.
_ARMOURED_SECRET_RE = re.compile(r"^[A-Za-z0-9+/]{80,}={0,2}$")


def _is_secret(setting_name: str, value: str = "") -> bool:
    lowered = setting_name.lower()
    if any(marker in lowered for marker in SECRET_SETTING_MARKERS):
        return True
    return bool(value) and bool(_ARMOURED_SECRET_RE.match(value))

# Map-file settings columns worth keeping on a point record.
POINT_COLUMNS = {
    "Tag Name": "name",
    "Point Number": "address",
    "Tag Type": "type",
    "Comment": "description",
    "Event Class": "event_class",
    "Default Variation": "default_variation",
    "Class": "event_class",
    "Scale Factor": "scale_factor",
    "Deadband": "deadband",
    "Units": "units",
}

# A SourceExpression is "derived" (worth calling out in prose) if it does
# more than pass a tag straight through.
_DERIVED_RE = re.compile(r"[+\-*/<>=]|\bAND\b|\bOR\b|\bNOT\b|\bIF\b|\(", re.I)

# Tag references inside expressions / structured text: Device.Tag or
# Device.Tag.field
_TAG_REF_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b")


# ─── Small helpers ───────────────────────────────────────────────────────


def _text(elem: Optional[ET.Element], default: str = "") -> str:
    if elem is None or elem.text is None:
        return default
    return elem.text.strip()


def _row_to_dict(row: ET.Element) -> Dict[str, str]:
    """Flatten a <Row><Setting><Column/><Value/></Setting>… into a dict."""
    out: Dict[str, str] = {}
    for setting in row.findall("Setting"):
        col = _text(setting.find("Column"))
        val = _text(setting.find("Value"))
        if col:
            out[col] = val
    return out


def _settings_rows_to_dict(rows: Iterable[ET.Element]) -> Dict[str, str]:
    """
    Collapse a settings page into {setting_name: value}.

    Settings pages are column-named "Setting"/"Value"/"Comment", so each row
    is one named setting rather than one record.
    """
    out: Dict[str, str] = {}
    for row in rows:
        d = _row_to_dict(row)
        name = d.get("Setting")
        if name:
            value = d.get("Value", "")
            if value and value != "None":
                out[name] = REDACTED if _is_secret(name, value) else value
    return out


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# ─── Digest container ────────────────────────────────────────────────────


@dataclass
class Digest:
    project: Dict = field(default_factory=dict)
    controller: Dict = field(default_factory=dict)
    network: Dict = field(default_factory=dict)
    devices: List[Dict] = field(default_factory=list)
    maps: List[Dict] = field(default_factory=list)
    signal_chains: Dict = field(default_factory=dict)
    tag_processor: Dict = field(default_factory=dict)
    logic: List[Dict] = field(default_factory=list)
    virtual_tags: List[Dict] = field(default_factory=list)
    libraries: List[Dict] = field(default_factory=list)
    stats: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "project": self.project,
            "controller": self.controller,
            "network": self.network,
            "devices": self.devices,
            "maps": self.maps,
            "signal_chains": self.signal_chains,
            "tag_processor": self.tag_processor,
            "logic": self.logic,
            "virtual_tags": self.virtual_tags,
            "libraries": self.libraries,
            "stats": self.stats,
        }


# ─── Revision history ────────────────────────────────────────────────────

# "V10    06212023  MMainer (RRC)  Corrected modbus commands…"
_REV_RE = re.compile(
    r"^\s*(?P<version>[Vv][\w.]*\d[\w.]*)\s+"
    r"(?P<date>\d{6,8}|\d{1,2}/\d{1,2}/\d{2,4})?\s*"
    r"(?P<author>[A-Za-z]+(?:/[A-Za-z]+)*)?\s*"
    r"(?:\((?P<org>[^)]*)\))?\s*"
    r"(?P<note>.*)$"
)


def parse_revision_history(description: str) -> List[Dict]:
    """
    Pull structured revisions out of the free-text project description.

    Engineers write these by hand, so the format drifts between entries.
    Anything that doesn't match a version header is appended to the note of
    the revision above it rather than dropped.
    """
    revisions: List[Dict] = []
    for raw_line in description.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        m = _REV_RE.match(line)
        if m and m.group("version") and len(m.group("version")) >= 2:
            revisions.append(
                {
                    "version": m.group("version"),
                    "date": m.group("date") or "",
                    "author": m.group("author") or "",
                    "organization": m.group("org") or "",
                    "note": (m.group("note") or "").strip(),
                }
            )
        elif revisions:
            revisions[-1]["note"] = (revisions[-1]["note"] + " " + line.strip()).strip()
    return revisions


# ─── Per-file extractors ─────────────────────────────────────────────────


def extract_project_info(path: Path) -> Dict:
    root = ET.parse(path).getroot()
    info = root.find(".//ProjectInfo")
    if info is None:
        return {}
    description = _text(info.find("Description"))
    return {
        "description": description,
        "revision_history": parse_revision_history(description),
    }


def extract_main_controller(path: Path) -> Dict:
    """Task structure: cycle times, watchdogs, and POU execution order."""
    root = ET.parse(path).getroot()
    mc = root.find(".//MainController")
    if mc is None:
        return {}

    tasks: Dict[str, Dict] = {}
    for task_el in mc:
        name = _strip_ns(task_el.tag)
        if not name.endswith("Task"):
            continue
        pous = [
            {
                "name": _text(item.find("Name")),
                "enabled": _text(item.find("Enabled")).lower() == "true",
            }
            for item in task_el.findall("POUs/Item")
        ]
        tasks[name] = {
            "cycle_time_ms": _text(task_el.find("CycleTime")),
            "watchdog_time_ms": _text(task_el.find("WatchdogTime")),
            "pou_execution_order": pous,
        }
    return {"tasks": tasks}


def extract_ethernet(path: Path) -> Dict:
    """
    Network interfaces, addressing and routes.

    The payload here is an embedded XML document inside <ObjectText>, so the
    interesting elements arrive as attributes rather than child elements.
    """
    root = ET.parse(path).getroot()
    schema = root.find(".//ObjectText/schema")
    if schema is None:
        return {}

    interfaces = []
    for iface in schema.findall("ipv4_network_interfaces"):
        routes = [
            {"destination": r.get("destination", ""), "gateway": r.get("gateway", "")}
            for r in iface.findall("static_routes")
        ]
        interfaces.append(
            {
                "name": iface.get("name", ""),
                "device": iface.get("device", ""),
                "ipv4_address": iface.get("ipv4_address", ""),
                "mac": iface.get("mac", ""),
                "enabled": iface.get("interface_enabled") == "true",
                "dhcp": iface.get("dhcp") == "true",
                "primary_gateway": iface.get("primary_gw") == "true",
                "web_access": iface.get("web_access") == "true",
                "static_routes": routes,
            }
        )
    return {"ipv4_interfaces": interfaces}


def extract_hosts(path: Path) -> List[Dict]:
    root = ET.parse(path).getroot()
    schema = root.find(".//ObjectText/schema")
    if schema is None:
        return []
    return [dict(h.attrib) for h in schema]


def _classify_role(protocol: str) -> str:
    if "Server" in protocol:
        return "server"
    if "Client" in protocol:
        return "client"
    return "device"


def _classify_page(rows: List[ET.Element]) -> str:
    """
    Decide what a settings page actually is.

    RTAC uses one generic <SettingPage><Row><Setting><Column/><Value/> shape
    for everything, so the page's meaning is only discoverable from its
    columns.  Name/value config uses literal columns "Setting"/"Value";
    point maps carry a "Tag Name"; anything else is a small config table
    (poll schedules, message definitions, command strings).
    """
    if not rows:
        return "empty"
    columns = {
        _text(s.find("Column"))
        for row in rows[:3]
        for s in row.findall("Setting")
    }
    if "Setting" in columns and "Value" in columns:
        return "settings"
    if "Tag Name" in columns:
        return "points"
    return "table"


def _extract_points_from_page(
    rows: List[ET.Element], group: str
) -> List[Dict]:
    """Pull enabled point records out of one protocol page."""
    points: List[Dict] = []
    for row in rows:
        d = _row_to_dict(row)
        # Disabled rows are map placeholders — they carry no design intent
        # and would multiply the digest several times over.
        if d.get("Enable", "").lower() == "false":
            continue
        point: Dict[str, str] = {}
        for col, key in POINT_COLUMNS.items():
            if d.get(col):
                point[key] = d[col]
        if point.get("name"):
            point["group"] = group
            points.append(point)
    return points


def _extract_table(rows: List[ET.Element], group: str) -> Optional[Dict]:
    """Carry a small config table verbatim; summarise a large one."""
    if len(rows) > TABLE_ROW_LIMIT:
        return {"name": group, "row_count": len(rows), "truncated": True}
    parsed = [
        {k: (REDACTED if _is_secret(k, v) else v) for k, v in d.items()}
        for d in (_row_to_dict(r) for r in rows)
        if d
    ]
    if not parsed:
        return None
    return {"name": group, "row_count": len(parsed), "rows": parsed}


def extract_device(path: Path, rel_path: str) -> Optional[Dict]:
    """
    One configured comms interface: protocol, role, connection settings, its
    point map, and any polling/message tables.

    Point maps for client devices live in protocol-specific pages under the
    connection ("Analog Inputs" for DNP, "Meter"/"Remote Bits" for SEL Fast
    Message, "Holding Registers" for Modbus, "Status OIDs" for SNMP), while
    server devices reference a shared TagList map by name instead.  Both are
    handled here.
    """
    root = ET.parse(path).getroot()
    device = root.find(".//Device")
    if device is None:
        return None

    connection = device.find("Connection")
    protocol = _text(connection.find("Protocol")) if connection is not None else ""

    settings: Dict[str, str] = {}
    points: List[Dict] = []
    tables: List[Dict] = []
    point_groups: Dict[str, int] = {}

    if connection is not None:
        for page in connection.findall("SettingPages/SettingPage"):
            page_name = _text(page.find("Name"))
            if page_name in SKIP_PAGES:
                continue
            rows = page.findall("Row")
            kind = _classify_page(rows)

            if kind == "settings":
                settings.update(_settings_rows_to_dict(rows))
            elif kind == "points":
                group_points = _extract_points_from_page(rows, page_name)
                if group_points:
                    points.extend(group_points)
                    point_groups[page_name] = len(group_points)
            elif kind == "table":
                table = _extract_table(rows, page_name)
                if table:
                    tables.append(table)

    # Devices that embed a TagList (rather than referencing a shared map).
    for taglist in device.findall(".//TagList"):
        list_name = _text(taglist.find("Name")) or "TagList"
        for page in taglist.findall(".//SettingPage"):
            embedded = _extract_points_from_page(page.findall("Row"), list_name)
            if embedded:
                points.extend(embedded)
                point_groups[list_name] = point_groups.get(list_name, 0) + len(embedded)

    child_ieds = [
        _text(c.find("Name")) or _text(c)
        for c in device.findall(".//ChildIEDs/*")
    ]

    return {
        "name": _text(device.find("Name")) or path.stem,
        # Tag references use the project instance name, which the export
        # records as the file name rather than the <Name> element — they
        # differ (device "PQM7" is referenced as "PQM7_DNP.…").
        "instance_name": path.stem,
        "file": rel_path,
        "folder": str(Path(rel_path).parent),
        "manufacturer": _text(device.find("Manufacturer")),
        "model": _text(device.find("Model")),
        "protocol": protocol,
        "role": _classify_role(protocol),
        "connection_type": _text(connection.find("ConnectionType")) if connection is not None else "",
        "map_name": settings.get("Map Name", ""),
        "settings": settings,
        "point_groups": point_groups,
        "tables": tables,
        "child_ieds": [c for c in child_ieds if c],
        "points": points,
    }


def extract_map(path: Path, rel_path: str) -> Optional[Dict]:
    """A standalone TagList file — a protocol map shared by several devices."""
    root = ET.parse(path).getroot()
    taglist = root.find("TagList")
    if taglist is None:
        return None

    points: List[Dict] = []
    point_groups: Dict[str, int] = {}
    for page in taglist.findall(".//SettingPage"):
        group = _text(page.find("Name")) or "Points"
        page_points = _extract_points_from_page(page.findall("Row"), group)
        if page_points:
            points.extend(page_points)
            point_groups[group] = len(page_points)

    return {
        "name": _text(taglist.find("Name")) or path.stem,
        "instance_name": path.stem,
        "file": rel_path,
        "list_type": _text(taglist.find("TagListType")),
        "point_groups": point_groups,
        "points": points,
    }


def extract_tag_processor(path: Path) -> Dict:
    """
    The Tag Processor is the signal chain: every row maps a source
    expression onto a destination tag, optionally with time and quality
    lineage.  This is the single most narrative-dense artifact in the export.
    """
    root = ET.parse(path).getroot()
    mappings: List[Dict] = []

    for row in root.findall(".//SettingPage/Row"):
        d = _row_to_dict(row)
        destination = d.get("DestinationTagName", "")
        if not destination or d.get("Build", "").lower() == "false":
            continue

        source = d.get("SourceExpression", "")
        mapping = {
            "destination": destination,
            "destination_type": d.get("DTDataType", ""),
            "source_expression": source,
            "source_type": d.get("SEDataType", ""),
            "solve_order": d.get("SolveOrder", ""),
            "derived": bool(source) and bool(_DERIVED_RE.search(source)),
        }
        for col, key in (
            ("TimeSource", "time_source"),
            ("QualitySource", "quality_source"),
            ("LoggingCategory", "logging_category"),
            ("LoggingOnMessage", "logging_on_message"),
            ("LoggingOffMessage", "logging_off_message"),
            ("LoggingChatterTime", "chatter_time"),
        ):
            if d.get(col) and d[col] != "None":
                mapping[key] = d[col]
        if d.get("LoggingAlarmEnable", "").lower() == "true":
            mapping["alarm"] = True
        mappings.append(mapping)

    derived = [m for m in mappings if m["derived"]]
    return {
        "mapping_count": len(mappings),
        "derived_count": len(derived),
        "alarmed_count": sum(1 for m in mappings if m.get("alarm")),
        "mappings": mappings,
    }


def extract_pou(path: Path, rel_path: str) -> Optional[Dict]:
    """User logic — declaration and implementation of a POU, verbatim."""
    root = ET.parse(path).getroot()
    pou = root.find("POU")
    if pou is None:
        return None
    content = pou.find("Content")
    if content is None:
        return None
    implementation = _text(content.find("Implementation"))
    if not implementation:
        return None
    return {
        "name": _text(pou.find("Name")) or path.stem,
        "kind": _text(pou.find("POUKind")),
        "file": rel_path,
        "task": Path(rel_path).parent.name,
        "interface": _text(content.find("Interface")),
        "implementation": implementation,
    }


def extract_gvl(path: Path, rel_path: str) -> Optional[Dict]:
    root = ET.parse(path).getroot()
    gvl = root.find("GVL")
    if gvl is None:
        return None
    content = gvl.find("Content")
    return {
        "name": _text(gvl.find("Name")) or path.stem,
        "file": rel_path,
        "declaration": _text(content.find("Interface")) if content is not None else "",
    }


# ─── Relevance filtering ─────────────────────────────────────────────────


def collect_referenced_tags(tag_processor: Dict, pous: List[Dict]) -> Set[str]:
    """
    Every tag named by the Tag Processor or by user logic.

    These are the points the design actually *does* something with, as
    opposed to the thousands that exist only because a vendor map template
    declared them.  Matching is case-insensitive because RTAC tag references
    are, and engineers are inconsistent about it (the ORS1 export has both
    `PQM7_DNP.W3.q` and `PQM7_DNP.w3.q`).
    """
    referenced: Set[str] = set()

    def add_from(text: str) -> None:
        for match in _TAG_REF_RE.findall(text or ""):
            parts = match.split(".")
            # Record progressively shorter prefixes so `Dev.Tag.stVal` also
            # matches a point recorded as `Dev.Tag`.
            for i in range(len(parts), 1, -1):
                referenced.add(".".join(parts[:i]).lower())

    for mapping in tag_processor.get("mappings", []):
        add_from(mapping.get("destination", ""))
        add_from(mapping.get("source_expression", ""))
        add_from(mapping.get("time_source", ""))
        add_from(mapping.get("quality_source", ""))

    for pou in pous:
        add_from(pou.get("implementation", ""))
        add_from(pou.get("interface", ""))

    return referenced


# ─── Signal chains ───────────────────────────────────────────────────────

# Data types that mark a point as an operate/command point.  This is the
# direction test from rtac-plg's generate_points_by_device: a Tag Processor
# row whose *source* is an operate point is a control the RTAC received and
# is routing onward; every other row is telemetry the RTAC is publishing.
CONTROL_SOURCE_TYPES = {"operAPC", "operSPC"}

# Leading token of a source expression, minus any operator punctuation.
_LEADING_TOKEN_RE = re.compile(r"^[\s(]*([A-Za-z_][A-Za-z0-9_.]*)")


def _source_tag_of(expression: str) -> str:
    """The primary tag an expression reads from."""
    if not expression:
        return ""
    m = _LEADING_TOKEN_RE.match(expression)
    return m.group(1) if m else ""


def build_signal_chains(
    devices: List[Dict], maps: List[Dict], tag_processor: Dict
) -> Dict:
    """
    Resolve every Tag Processor row into a directional signal chain, grouped
    by the interface that owns the point.

    A point list on its own says what exists; it does not say which direction
    data moves or what it is derived from.  Walking the Tag Processor and
    resolving each row against the point inventory answers both, which is
    what lets the narrative say "the RTAC publishes X to NYSEG, computed from
    Y" rather than just listing addresses.

    Interfaces are keyed by the owning map or device instance, and server
    devices sharing a map (ORS1 serves the same InvEnergy map to three
    different masters) are listed together against that one map.
    """
    # Index every known point by its fully-qualified tag name.  Point names
    # already carry their owner prefix, so this is a flat lookup.
    points_by_name: Dict[str, Dict] = {}
    owner_of_point: Dict[str, str] = {}

    def index_owner(owner_key: str, container: Dict) -> None:
        for point in container.get("points", []):
            name = point.get("name", "")
            if not name:
                continue
            key = name.lower()
            points_by_name.setdefault(key, point)
            owner_of_point.setdefault(key, owner_key)

    interfaces: Dict[str, Dict] = {}

    for mapping in maps:
        key = mapping["instance_name"]
        bound = [
            d["name"] for d in devices if d.get("map_name", "").lower() == key.lower()
        ]
        interfaces[key] = {
            "kind": "map",
            "map_name": mapping.get("name", ""),
            "protocol": mapping.get("list_type", ""),
            "served_to": bound,
            "role": "server" if bound else "unbound",
            "telemetry": [],
            "controls": [],
        }
        index_owner(key, mapping)

    for device in devices:
        key = device["instance_name"]
        # A server device's points live in its shared map, already indexed.
        if device.get("map_name"):
            continue
        interfaces[key] = {
            "kind": "device",
            "device_name": device.get("name", ""),
            "protocol": device.get("protocol", ""),
            "role": device.get("role", ""),
            "telemetry": [],
            "controls": [],
        }
        index_owner(key, device)

    unresolved: List[Dict] = []
    internal: Dict[str, List[Dict]] = {}
    seen: Dict[Tuple, List[int]] = {}

    for row_index, mapping in enumerate(tag_processor.get("mappings", []), start=1):
        destination = mapping.get("destination", "")
        expression = mapping.get("source_expression", "")
        source_tag = _source_tag_of(expression)

        source_point = points_by_name.get(source_tag.lower())
        source_type = (source_point or {}).get("type", "")
        is_control = source_type in CONTROL_SOURCE_TYPES

        # For a control the device point is the source; otherwise it is the
        # destination the Tag Processor is writing.
        point_name = source_tag if is_control else destination
        point = points_by_name.get(point_name.lower())
        owner = owner_of_point.get(point_name.lower())

        if not point or not owner:
            # Not every Tag Processor row targets a protocol point.  Rows
            # writing SystemTags (security and diagnostic event logging) or
            # POU-owned tags are legitimate destinations that simply do not
            # live on an interface, so they are grouped by namespace rather
            # than reported as failures.
            namespace = point_name.split(".", 1)[0] if "." in point_name else ""
            if namespace:
                entry = {
                    "tag_processor_row": row_index,
                    "target": point_name,
                    "source_expression": expression,
                }
                for key in ("logging_category", "logging_on_message", "alarm"):
                    if mapping.get(key):
                        entry[key] = mapping[key]
                internal.setdefault(namespace, []).append(entry)
            else:
                unresolved.append(
                    {
                        "tag_processor_row": row_index,
                        "destination": destination,
                        "source_expression": expression,
                        "reason": "point not found in any device or map",
                    }
                )
            continue

        entry = {
            "tag_processor_row": row_index,
            "point": point_name,
            "address": point.get("address", ""),
            "data_type": point.get("type", ""),
            "point_type": RTAC_TO_POINT_TYPE.get(point.get("type", ""), ""),
            "group": point.get("group", ""),
            "expression": expression,
            "derived": mapping.get("derived", False),
        }
        for key in ("description",):
            if point.get(key):
                entry["comment"] = point[key]
        for key in (
            "time_source",
            "quality_source",
            "alarm",
            "logging_category",
            "logging_on_message",
            "logging_off_message",
            "chatter_time",
        ):
            if mapping.get(key):
                entry[key] = mapping[key]

        if is_control:
            entry["routed_to"] = destination
            interfaces[owner]["controls"].append(entry)
        else:
            entry["sourced_from"] = source_tag
            interfaces[owner]["telemetry"].append(entry)

        # A point written by more than one Tag Processor row is a genuine
        # config defect — the later row silently wins.
        seen.setdefault((owner, point_name.lower(), is_control), []).append(row_index)

    duplicates = [
        {"interface": owner, "point": name, "tag_processor_rows": rows}
        for (owner, name, _), rows in seen.items()
        if len(rows) > 1
    ]

    for iface in interfaces.values():
        iface["counts"] = {
            "telemetry": len(iface["telemetry"]),
            "controls": len(iface["controls"]),
        }

    # An interface with no Tag Processor rows is not idle — its points are
    # driven by device POUs or user logic instead.  That distinction matters
    # to the narrative, so record why rather than dropping it.
    active = {k: v for k, v in interfaces.items() if v["telemetry"] or v["controls"]}
    not_tag_processed = [
        {
            "interface": k,
            "protocol": v.get("protocol", ""),
            "role": v.get("role", ""),
            "note": "no Tag Processor rows; driven by device POU or user logic",
        }
        for k, v in interfaces.items()
        if k not in active
    ]

    return {
        "interfaces": active,
        "not_tag_processed": not_tag_processed,
        "internal_targets": {
            namespace: {"count": len(entries), "entries": entries}
            for namespace, entries in sorted(internal.items())
        },
        "duplicates": duplicates,
        "unresolved": unresolved,
        "unresolved_count": len(unresolved),
    }


def _sample_points(points: List[Dict], limit: int) -> List[Dict]:
    """Spread a sample across data types so no type is invisible."""
    by_type: Dict[str, List[Dict]] = {}
    for p in points:
        by_type.setdefault(p.get("type", "?"), []).append(p)
    if not by_type:
        return []

    per_type = max(1, limit // len(by_type))
    sampled: List[Dict] = []
    for group in by_type.values():
        sampled.extend(group[:per_type])
    return sampled[:limit]


def condense_points(
    points: List[Dict],
    referenced: Set[str],
    prefixes: Iterable[str] = (),
) -> Dict:
    """
    Reduce a point list to a bounded summary plus the points worth naming.

    Small maps pass through whole.  Large ones keep the referenced points —
    the ones wired into logic — and a type-stratified sample of the rest, so
    the narrative can still describe the map's shape without listing it.

    Args:
        prefixes: Names this map/device may be referenced by.  A point is
            declared as a bare tag but referenced through its owner, and the
            owner has up to three aliases (file stem, <Name>, "Map Name"),
            which do not reliably agree.
    """
    by_type: Dict[str, int] = {}
    by_group: Dict[str, int] = {}
    addresses: Dict[str, List[int]] = {}
    for p in points:
        t = p.get("type", "?")
        by_type[t] = by_type.get(t, 0) + 1
        g = p.get("group", "?")
        by_group[g] = by_group.get(g, 0) + 1
        addr = p.get("address")
        if addr and addr.isdigit():
            addresses.setdefault(t, []).append(int(addr))

    address_ranges = {
        t: {"min": min(v), "max": max(v), "count": len(v)}
        for t, v in addresses.items()
        if v
    }

    if len(points) <= FULL_ENUMERATION_LIMIT:
        return {
            "total": len(points),
            "by_type": by_type,
            "by_group": by_group,
            "address_ranges": address_ranges,
            "enumerated": True,
            "points": points,
        }

    clean_prefixes = [p.lower() for p in prefixes if p]

    def is_referenced(p: Dict) -> bool:
        name = p.get("name", "").lower()
        if not name:
            return False
        if name in referenced:
            return True
        return any(f"{prefix}.{name}" in referenced for prefix in clean_prefixes)

    kept = [p for p in points if is_referenced(p)]
    remainder = [p for p in points if not is_referenced(p)]

    return {
        "total": len(points),
        "by_type": by_type,
        "by_group": by_group,
        "address_ranges": address_ranges,
        "enumerated": False,
        "referenced_points": kept,
        "referenced_count": len(kept),
        "sampled_points": _sample_points(remainder, SAMPLE_PER_DEVICE),
        "omitted_count": max(0, len(remainder) - SAMPLE_PER_DEVICE),
    }


# ─── Top-level walk ──────────────────────────────────────────────────────


def _iter_xml(root_dir: Path) -> Iterable[Tuple[Path, str]]:
    for path in sorted(root_dir.rglob("*.xml")):
        yield path, str(path.relative_to(root_dir)).replace("\\", "/")


def build_digest(export_root: str | Path, project_name: Optional[str] = None) -> Dict:
    """
    Walk an unpacked RTAC export and produce the narrative digest.

    Args:
        export_root: Directory containing the export (the folder holding
            `Project Info.xml`, `SEL_RTAC/`, `POUs/`).
        project_name: Overrides the directory name as the project label.

    Returns:
        The digest as a plain dict, ready to serialise as JSON.
    """
    root_dir = Path(export_root)
    if not root_dir.is_dir():
        raise NotADirectoryError(f"Export root not found: {root_dir}")

    digest = Digest()
    digest.project["name"] = project_name or root_dir.name
    digest.project["export_root"] = str(root_dir)

    pous: List[Dict] = []
    skipped: List[Dict] = []
    files_seen = 0

    for path, rel in _iter_xml(root_dir):
        files_seen += 1
        name = path.name
        try:
            if name == "Project Info.xml":
                digest.project.update(extract_project_info(path))
                continue
            if name == "Main Controller.xml":
                digest.controller = extract_main_controller(path)
                continue
            if name == "Ethernet Settings.xml":
                digest.network.update(extract_ethernet(path))
                continue
            if name == "Hosts.xml":
                digest.network["hosts"] = extract_hosts(path)
                continue
            if name == "Tag Processor.xml":
                digest.tag_processor = extract_tag_processor(path)
                continue

            # The vendor POU library under POUs/ is thousands of data-type
            # and function-block definitions — reference material, not design
            # intent.  Only user logic is carried.
            if rel.startswith("POUs/"):
                continue

            if "/User Logic/" in f"/{rel}":
                pou = extract_pou(path, rel)
                if pou:
                    pous.append(pou)
                continue

            if "Virtual Tag Lists" in rel:
                gvl = extract_gvl(path, rel)
                if gvl:
                    digest.virtual_tags.append(gvl)
                continue

            if "/Devices/" in f"/{rel}":
                device = extract_device(path, rel)
                if device:
                    digest.devices.append(device)
                    continue
                mapping = extract_map(path, rel)
                if mapping:
                    digest.maps.append(mapping)
                    continue

        except ET.ParseError as exc:
            skipped.append({"file": rel, "reason": f"parse error: {exc}"})

    digest.logic = pous

    # Both of these need the full point inventory, so they run after the
    # whole walk and before points are condensed away.
    digest.signal_chains = build_signal_chains(
        digest.devices, digest.maps, digest.tag_processor
    )
    referenced = collect_referenced_tags(digest.tag_processor, pous)

    for device in digest.devices:
        device["point_summary"] = condense_points(
            device.pop("points", []),
            referenced,
            (device.get("instance_name"), device.get("name"), device.get("map_name")),
        )
    for mapping in digest.maps:
        mapping["point_summary"] = condense_points(
            mapping.pop("points", []),
            referenced,
            (mapping.get("instance_name"), mapping.get("name")),
        )

    # Every mapping now exists in resolved form under signal_chains, so the
    # raw row list would be a second copy of the largest section.
    digest.tag_processor.pop("mappings", None)

    digest.stats = {
        "xml_files_seen": files_seen,
        "devices": len(digest.devices),
        "shared_maps": len(digest.maps),
        "user_logic_pous": len(pous),
        "tag_processor_mappings": digest.tag_processor.get("mapping_count", 0),
        "resolved_signal_chains": sum(
            i["counts"]["telemetry"] + i["counts"]["controls"]
            for i in digest.signal_chains["interfaces"].values()
        ),
        "unresolved_mappings": digest.signal_chains["unresolved_count"],
        "duplicate_writes": len(digest.signal_chains["duplicates"]),
        "referenced_tags": len(referenced),
        "total_points": sum(
            d["point_summary"]["total"] for d in digest.devices + digest.maps
        ),
        "skipped_files": skipped,
        "roles": _count(d["role"] for d in digest.devices),
        "protocols": _count(d["protocol"] for d in digest.devices if d["protocol"]),
    }

    return digest.to_dict()


def build_digest_from_zip(zip_bytes: bytes, project_name: Optional[str] = None) -> Dict:
    """
    Build a digest from a zipped RTAC export.

    RTAC exports arrive as a directory tree, so the API surface takes a zip
    and unpacks it to a temporary directory rather than reimplementing the
    walk over zip entries.

    If the archive wraps everything in a single top-level folder — which
    is how they are normally produced — that folder is treated as the export
    root so `Project Info.xml` is found where the walk expects it.
    """
    import shutil
    import tempfile
    import zipfile

    tmp = Path(tempfile.mkdtemp(prefix="rtac_export_"))
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            archive.extractall(tmp)

        root = tmp
        entries = [p for p in root.iterdir() if not p.name.startswith("__MACOSX")]
        if len(entries) == 1 and entries[0].is_dir():
            root = entries[0]

        return build_digest(root, project_name or root.name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _count(values: Iterable[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


# ─── CLI ─────────────────────────────────────────────────────────────────


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description="Build a narrative digest from an unpacked RTAC export."
    )
    ap.add_argument("export_root", help="Directory containing the RTAC export")
    ap.add_argument("-o", "--output", help="Write digest JSON here (default: stdout)")
    ap.add_argument("--project-name", help="Override the project label")
    args = ap.parse_args()

    digest = build_digest(args.export_root, args.project_name)
    payload = json.dumps(digest, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        stats = digest["stats"]
        print(f"Wrote {args.output} ({len(payload):,} chars)")
        print(
            f"  {stats['devices']} devices, {stats['shared_maps']} maps, "
            f"{stats['user_logic_pous']} POUs, "
            f"{stats['tag_processor_mappings']} tag-processor mappings, "
            f"{stats['total_points']:,} points"
        )
    else:
        print(payload)


if __name__ == "__main__":
    main()
