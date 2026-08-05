"""
SCADA Design Narrative — section plan and prompt construction.

Stage 2 of narrative generation.  `narrative_digest` turns an RTAC export
into a bounded fact base; this module turns that fact base into a sequence
of self-contained LLM prompts, one per document section.

Why sections rather than one call: the full digest for a mid-size plant is
~650 KB, and even where that fits a context window, asking for a whole
document in one shot produces uniformly shallow prose.  Each section gets
only the slice it needs, so the model has room to actually say something
about it.

The hard rule enforced throughout is that the model may only write what the
digest supports.  A design narrative that invents a setpoint or a DNP index
is worse than no narrative at all, so every prompt carries an explicit
no-inference instruction and the sections that make claims about numbers are
handed those numbers verbatim.
"""

import json
from typing import Callable, Dict, List, Optional

# ─── Shared voice ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a senior SCADA and protection engineer writing the as-built Design \
Basis / Design Narrative for a substation or generating-plant automation \
controller. Your reader is another power-systems engineer who has just \
inherited this system and needs to understand it well enough to modify it \
safely.

How you write:
- Plain technical prose in complete sentences. Explain *why* the \
configuration is the way it is, where the evidence supports a reason.
- Concrete and specific. Name the device, the protocol, the DNP index, the \
tag, the timeout value.
- Tables for point maps, interface schedules and settings. Prose for intent, \
data flow and behaviour. Never a wall of bullet fragments.
- Use the engineering register: "the RTAC polls", "the map presents", \
"unsolicited reporting is disabled". Not marketing language, not tutorial \
language, no filler openers.

Absolute constraints:
- Every factual claim must be supported by the supplied data. You are \
describing a real installed system that people will operate from this \
document.
- Never invent a tag name, address, IP, setpoint, timer or device. If \
something a reader would expect is absent from the data, say it is not \
present in the export rather than guessing.
- Where the data reveals a genuine problem — a point written twice, a \
disabled interface, a missing quality source — state it plainly as an \
observation. Do not editorialise or soften it.
- Output GitHub-flavoured Markdown starting at the given heading level. Do \
not restate the document title or add a preamble about what you are doing.
"""


# ─── Slice helpers ───────────────────────────────────────────────────────


def _without(obj: Dict, *keys: str) -> Dict:
    return {k: v for k, v in obj.items() if k not in keys}


def _device_summary(device: Dict) -> Dict:
    """A device without its point inventory — identity and configuration."""
    summary = _without(device, "point_summary")
    points = device.get("point_summary", {})
    summary["point_totals"] = {
        "total": points.get("total", 0),
        "by_type": points.get("by_type", {}),
        "by_group": points.get("by_group", {}),
    }
    return summary


def _roster(digest: Dict) -> List[Dict]:
    """One line per interface — enough to introduce the system."""
    return [
        {
            "name": d["name"],
            "instance": d["instance_name"],
            "protocol": d["protocol"],
            "role": d["role"],
            "manufacturer": d.get("manufacturer", ""),
            "model": d.get("model", ""),
            "map_name": d.get("map_name", ""),
            "points": d.get("point_summary", {}).get("total", 0),
        }
        for d in digest.get("devices", [])
    ]


def _devices_by_role(digest: Dict, role: str) -> List[Dict]:
    return [_device_summary(d) for d in digest.get("devices", []) if d.get("role") == role]


# ─── Section slicers ─────────────────────────────────────────────────────


def _slice_overview(digest: Dict) -> Dict:
    return {
        "project": digest.get("project", {}),
        "stats": _without(digest.get("stats", {}), "skipped_files"),
        "controller": digest.get("controller", {}),
        "network": digest.get("network", {}),
        "interface_roster": _roster(digest),
    }


def _slice_comms(digest: Dict) -> Dict:
    return {
        "network": digest.get("network", {}),
        "controller": digest.get("controller", {}),
        "devices": [_device_summary(d) for d in digest.get("devices", [])],
        "shared_maps": [
            {
                "name": m["name"],
                "instance": m["instance_name"],
                "protocol": m.get("list_type", ""),
                "points": m.get("point_summary", {}).get("total", 0),
                "by_type": m.get("point_summary", {}).get("by_type", {}),
            }
            for m in digest.get("maps", [])
        ],
    }


def _slice_acquisition(digest: Dict) -> Dict:
    """Upstream: what the RTAC reads from field devices."""
    clients = [d for d in digest.get("devices", []) if d.get("role") == "client"]
    return {
        "client_devices": [
            {
                **_device_summary(d),
                "point_detail": d.get("point_summary", {}),
            }
            for d in clients
        ],
        "not_tag_processed": digest.get("signal_chains", {}).get("not_tag_processed", []),
    }


def _slice_presentation(digest: Dict) -> Dict:
    """Downstream: what the RTAC presents to masters, and to whom."""
    chains = digest.get("signal_chains", {})
    server_interfaces = {
        k: v for k, v in chains.get("interfaces", {}).items() if v.get("kind") == "map"
    }
    return {
        "server_devices": _devices_by_role(digest, "server"),
        "maps": [
            {**_without(m, "point_summary"), "point_detail": m.get("point_summary", {})}
            for m in digest.get("maps", [])
        ],
        "interfaces": server_interfaces,
    }


def _slice_signal_processing(digest: Dict) -> Dict:
    chains = digest.get("signal_chains", {})
    interfaces = chains.get("interfaces", {})
    derived = {
        key: [t for t in iface.get("telemetry", []) if t.get("derived")]
        for key, iface in interfaces.items()
    }
    return {
        "tag_processor_summary": digest.get("tag_processor", {}),
        "interfaces": interfaces,
        "derived_by_interface": {k: v for k, v in derived.items() if v},
    }


def _slice_control(digest: Dict) -> Dict:
    chains = digest.get("signal_chains", {})
    controls = {
        key: iface.get("controls", [])
        for key, iface in chains.get("interfaces", {}).items()
        if iface.get("controls")
    }
    return {
        "controller": digest.get("controller", {}),
        "user_logic": digest.get("logic", []),
        "virtual_tags": digest.get("virtual_tags", []),
        "controls_by_interface": controls,
    }


def _slice_alarming(digest: Dict) -> Dict:
    chains = digest.get("signal_chains", {})
    alarmed = []
    for key, iface in chains.get("interfaces", {}).items():
        for entry in iface.get("telemetry", []) + iface.get("controls", []):
            if entry.get("alarm") or entry.get("logging_category") or entry.get(
                "logging_on_message"
            ):
                alarmed.append({"interface": key, **entry})
    return {
        "alarmed_and_logged_points": alarmed,
        "internal_targets": chains.get("internal_targets", {}),
        "comm_monitoring_logic": [
            p
            for p in digest.get("logic", [])
            if "alarm" in p.get("name", "").lower()
            or "comm" in p.get("name", "").lower()
        ],
    }


def _slice_findings(digest: Dict) -> Dict:
    chains = digest.get("signal_chains", {})
    sparse = [
        {
            "interface": d["instance_name"],
            "protocol": d["protocol"],
            "role": d["role"],
            "enabled_points": d.get("point_summary", {}).get("total", 0),
            "point_groups": d.get("point_groups", {}),
        }
        for d in digest.get("devices", [])
    ]
    return {
        "stats": digest.get("stats", {}),
        "duplicate_writes": chains.get("duplicates", []),
        "not_tag_processed": chains.get("not_tag_processed", []),
        "unresolved_mappings": chains.get("unresolved", []),
        "enabled_point_counts": sparse,
    }


def _slice_revisions(digest: Dict) -> Dict:
    return {"project": digest.get("project", {})}


# ─── Section plan ────────────────────────────────────────────────────────


class Section:
    def __init__(
        self,
        key: str,
        title: str,
        slicer: Callable[[Dict], Dict],
        guidance: str,
    ) -> None:
        self.key = key
        self.title = title
        self.slicer = slicer
        self.guidance = guidance


SECTIONS: List[Section] = [
    Section(
        "overview",
        "System Overview",
        _slice_overview,
        """Open with what this controller is and what plant it runs — infer the \
plant type and its commercial context only from evidence in the data \
(interface names, vendor names, the revision history), and say what the \
evidence is.

Then cover, in prose:
- The controller's role: how many interfaces, split between devices it reads \
from and masters it serves.
- The parties involved: which external organisations appear as interfaces, \
and what each relationship appears to be.
- Task structure and scan rate, and what that implies about the control \
timeframe.
- Network configuration: interfaces, addressing, segmentation and what each \
segment appears to carry.

Close with a short interface schedule table: Interface | Protocol | Role | \
Peer | Points.""",
    ),
    Section(
        "communications",
        "Communications Architecture",
        _slice_comms,
        """Describe every configured interface and the settings that govern it.

Organise by role — first the client connections the controller polls, then \
the server connections it answers. Within each, group by protocol.

For each interface give a settings table of the parameters that actually \
matter operationally: addressing (DNP addresses, IP ports, unit IDs), \
timing (poll periods, offline timers, confirmation timeouts, retries), and \
behavioural flags (unsolicited reporting, time sync, control enables, \
event buffer sizes and modes). Omit parameters left at defaults with no \
bearing on behaviour.

Then explain in prose what the settings mean together. Where a value is \
notably non-default or restrictive, say so and what it implies — a long \
confirmation timeout, disabled unsolicited reporting, or an anonymous-client \
allowance each tell you something about how the link behaves and how it was \
troubleshot.

Note where several server devices share one map, and what that means: the \
same data presented to multiple masters over separate sessions.""",
    ),
    Section(
        "acquisition",
        "Data Acquisition — Field Devices",
        _slice_acquisition,
        """Describe what the controller reads from each upstream device.

For each client interface: what the device is, what it is being polled for, \
how the point map is organised (the point groups are the protocol's own \
page names — 'Analog Inputs', 'Meter', 'Holding Registers', 'Status OIDs'), \
and the poll configuration where present.

Pay attention to the ratio of enabled to available points. A device \
exposing hundreds of possible points with only a handful enabled is a \
deliberate engineering decision to poll only what is used, and is worth \
stating explicitly with the numbers.

Where an interface has no Tag Processor rows at all, explain that its data \
is consumed directly by a device function block or by user logic rather \
than being remapped — do not imply the interface is unused.

Use tables for point inventories. Keep each device to a short paragraph plus \
its table.""",
    ),
    Section(
        "presentation",
        "Data Presentation — SCADA and Utility Masters",
        _slice_presentation,
        """Describe what the controller publishes, to whom, and on what address.

For each server map: which masters it is served to, the protocol, and the \
full telemetry point list as a table — DNP index, tag, type, description, \
and the source it is derived from. Where a map is small, enumerate it \
completely; where it is large, characterise it by type and address range and \
enumerate only the points carried in the data.

This is the section a utility or operations reader will turn to first, so be \
precise about indices and directions. Distinguish clearly between points the \
controller publishes (telemetry) and points a master writes (controls) — \
controls are covered in detail later, so here only note their presence and \
count.

Where the same map serves several masters, state that each master sees an \
identical image.""",
    ),
    Section(
        "signal_processing",
        "Signal Processing and Tag Mapping",
        _slice_signal_processing,
        """Explain how field data becomes published data.

Start with the Tag Processor's role and scale — how many mappings, how many \
are pass-through versus computed.

Then work through the computed mappings. For each meaningful group, give the \
destination, the expression, and an explanation in words of what the \
expression does and why an engineer would write it: unit scaling, sign \
conventions for import versus export, threshold comparisons that turn an \
analogue into a status, aggregation across devices.

Cover time and quality propagation explicitly. Where a mapping carries a \
time source and quality source, explain that the published point inherits \
the field device's timestamp and validity rather than the controller's, and \
why that matters to a master. Where a mapping lacks them, note it.

Use a table of destination | expression | meaning for the computed points, \
with prose around it explaining the patterns.""",
    ),
    Section(
        "control",
        "Control and Automation Logic",
        _slice_control,
        """Describe how the controller acts, not just what it reports.

Cover the task structure first: which programs run in which task, in what \
order, at what scan rate, and why order matters where it does.

Then the control paths. For each control point a master can write, trace the \
full path: which master writes it, the point and index, what the controller \
does with the value, and what feedback point confirms it. Setpoint and \
mode-command paths deserve individual treatment.

Then walk the user logic. For each program or function block, explain what \
it does in engineering terms — quote the significant lines of Structured \
Text where they carry the logic, but explain rather than transcribe. Cover \
the operating modes, interlocks, command sequencing and any first-scan or \
initialisation behaviour.

Be precise about direction: a control received from a master and routed \
onward to plant equipment is a different thing from an internal setpoint.""",
    ),
    Section(
        "alarming",
        "Alarming, Logging and Diagnostics",
        _slice_alarming,
        """Describe how the system reports its own health and records events.

Cover:
- Points configured for alarming, with their categories and messages.
- Chatter filtering where configured, and what problem it exists to solve.
- Security and system event logging.
- Communications monitoring: how link failure is detected on each interface, \
what timers govern it, and what the controller does when a link drops.

Where dedicated logic exists to detect a comms failure mode, explain the \
failure mode it was written for — that is usually recoverable from the logic \
plus the revision history.""",
    ),
    Section(
        "findings",
        "Observations and Configuration Findings",
        _slice_findings,
        """State what the configuration data reveals about the health of this \
project. This section is an engineering review, not a summary.

Address each of these where the data supports it:
- Points written by more than one Tag Processor row. Explain the consequence: \
solve order decides which write survives, so the later row silently wins. \
Name the points and rows.
- Interfaces configured but carrying no mapped points, and whether that \
looks deliberate.
- Mappings that could not be resolved to a point.
- Disproportion between available and enabled points.

For each finding give the evidence, the likely consequence, and what an \
engineer should check. Rank by operational significance. If a category has \
no findings, say so in one line rather than padding.

Do not report a finding the data does not support.""",
    ),
    Section(
        "revisions",
        "Revision History",
        _slice_revisions,
        """Present the project revision history as a table: Version | Date | \
Author | Organisation | Change. Normalise the dates to ISO format where \
they are unambiguous, and keep the engineer's own wording for the change \
description.

Follow the table with a short prose reading of what the history shows — \
recurring problem areas, which interfaces required the most attention, and \
what that suggests a maintainer should be careful about. This is often the \
most useful paragraph in the whole document, because it records problems \
that were found the hard way.""",
    ),
]

SECTIONS_BY_KEY = {s.key: s for s in SECTIONS}


# ─── Prompt construction ─────────────────────────────────────────────────


def build_section_prompt(
    digest: Dict,
    section: Section,
    heading_level: int = 2,
    extra_context: Optional[str] = None,
) -> Dict:
    """
    Build one self-contained prompt for a section.

    Returns a dict with `system` and `user` so it can be posted to any chat
    completion API without further assembly.
    """
    data = section.slicer(digest)
    project = digest.get("project", {}).get("name", "the project")
    heading = "#" * heading_level

    user = f"""\
Write the "{section.title}" section of the SCADA Design Narrative for {project}.

Begin with the heading `{heading} {section.title}` and use `{'#' * (heading_level + 1)}` \
for any subsections.

{section.guidance}
"""
    if extra_context:
        user += f"\nAdditional context for this project:\n{extra_context}\n"

    user += f"""
Data for this section, extracted from the RTAC project export. This is the \
only source you may draw on:

```json
{json.dumps(data, indent=1, ensure_ascii=False)}
```
"""
    return {
        "key": section.key,
        "title": section.title,
        "system": SYSTEM_PROMPT,
        "user": user,
        "data_chars": len(json.dumps(data)),
    }


def build_all_prompts(
    digest: Dict,
    heading_level: int = 2,
    extra_context: Optional[str] = None,
    only: Optional[List[str]] = None,
) -> List[Dict]:
    """Build prompts for every section, in document order."""
    sections = (
        [SECTIONS_BY_KEY[k] for k in only if k in SECTIONS_BY_KEY] if only else SECTIONS
    )
    return [
        build_section_prompt(digest, s, heading_level, extra_context) for s in sections
    ]


def document_header(digest: Dict) -> str:
    """The title block, assembled from facts rather than generated."""
    project = digest.get("project", {})
    stats = digest.get("stats", {})
    name = project.get("name", "RTAC Project")
    revisions = project.get("revision_history", [])
    latest = revisions[0] if revisions else {}

    lines = [
        f"# SCADA Design Narrative — {name}",
        "",
        "| | |",
        "| --- | --- |",
        f"| Source | RTAC project export ({stats.get('xml_files_seen', 0)} XML files) |",
        f"| Interfaces | {stats.get('devices', 0)} |",
        f"| Configured points | {stats.get('total_points', 0):,} |",
        f"| Tag Processor mappings | {stats.get('tag_processor_mappings', 0)} |",
    ]
    if latest:
        lines.append(
            f"| Latest revision | {latest.get('version', '')} "
            f"({latest.get('date', '')}, {latest.get('author', '')}) |"
        )
    lines += [
        "",
        "> Generated from the RTAC configuration export. Every statement is "
        "derived from the exported configuration; nothing is inferred from "
        "site documentation or field observation.",
        "",
    ]
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────


def main() -> None:
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(
        description="Build SCADA Design Narrative prompts from a digest JSON."
    )
    ap.add_argument("digest", help="Path to digest JSON from narrative_digest")
    ap.add_argument("-o", "--output-dir", help="Write one .md prompt file per section")
    ap.add_argument("--only", nargs="*", help="Limit to these section keys")
    ap.add_argument("--list", action="store_true", help="List sections and slice sizes")
    args = ap.parse_args()

    digest = json.loads(Path(args.digest).read_text(encoding="utf-8"))
    prompts = build_all_prompts(digest, only=args.only)

    if args.list or not args.output_dir:
        total = 0
        for p in prompts:
            total += p["data_chars"]
            print(f"  {p['key']:18s} {p['title']:42s} {p['data_chars']:>8,} chars")
        print(f"  {'':18s} {'TOTAL':42s} {total:>8,} chars")
        if not args.output_dir:
            return

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "00_header.md").write_text(document_header(digest), encoding="utf-8")
    for i, p in enumerate(prompts, start=1):
        (out / f"{i:02d}_{p['key']}.prompt.md").write_text(
            f"<!-- SYSTEM -->\n{p['system']}\n\n<!-- USER -->\n{p['user']}",
            encoding="utf-8",
        )
    print(f"Wrote {len(prompts)} prompts to {out}")


if __name__ == "__main__":
    main()
