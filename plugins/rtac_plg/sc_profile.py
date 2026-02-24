"""
SC (SCADA Configuration) Profile Generator

Converts parsed RTAC data (devices + points) into a CIM-compliant RDF/XML
profile following the Verance Extended CIM architecture.

Uses standard CIM classes (cim:Analog, cim:Discrete, cim:Accumulator,
cim:Control, cim:RemoteUnit, cim:RemoteSource, cim:RemoteControl,
cim:CommunicationLink) plus Verance extension classes (ver:SCADAPoint,
ver:DataFlowPath) for RTAC-specific metadata.

Profile links to the EQ (Equipment) profile via shared mRIDs.
"""

import uuid
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent, tostring

# ─── Namespace URIs ──────────────────────────────────────────────────────

CIM_NS = "http://iec.ch/TC57/CIM100#"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
MD_NS = "http://iec.ch/TC57/61970-552/ModelDescription/1#"
VER_NS = "http://verance.ai/CIM/SecondarySystem/1#"
PROFILE_URI = "http://verance.ai/CIM/SCADAConfiguration/1"

# ─── RTAC data type → CIM measurement class mapping ─────────────────────

_RTAC_TO_CIM_CLASS = {
    # Analog Inputs
    "MV": "Analog",
    "CMV": "Analog",
    "INT": "Analog",
    "INS": "Analog",
    # Binary Inputs
    "SPS": "Discrete",
    "BOOL": "Discrete",
    "DPS": "Discrete",
    # Counters
    "BCR": "Accumulator",
    # Analog Outputs / Controls
    "APC": "AnalogControl",
    "INC": "AnalogControl",
    "operAPC": "AnalogControl",
    # Binary Outputs / Controls
    "SPC": "Command",
    "DPC": "Command",
    "operSPC": "Command",
}

_RTAC_TO_POINT_TYPE = {
    "MV": "AI", "CMV": "AI", "INT": "AI", "INS": "AI",
    "SPS": "BI", "BOOL": "BI", "DPS": "BI",
    "BCR": "CT",
    "APC": "AO", "INC": "AO", "operAPC": "AO",
    "SPC": "BO", "DPC": "BO", "operSPC": "BO",
}

_CONTROL_TYPES = {"operAPC", "operSPC", "APC", "INC", "SPC", "DPC"}


def _deterministic_uuid(namespace: str, *parts: str) -> str:
    """Generate a deterministic UUID from namespace + parts for reproducibility."""
    seed = "|".join([namespace] + list(parts))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def _make_mrid(prefix: str, *parts: str) -> str:
    """Create a prefixed mRID like '_sc-<uuid>'."""
    uid = _deterministic_uuid(prefix, *parts)
    return f"_{prefix}-{uid}"


# ─── RDF/XML Builder ─────────────────────────────────────────────────────


class SCProfileBuilder:
    """
    Builds a SCADA Configuration (SC) CIM profile from parsed RTAC data.

    Usage:
        builder = SCProfileBuilder(
            substation_name="maple",
            eq_model_urn="urn:uuid:eq-model-001",
        )
        builder.add_devices(devices)
        builder.add_points(points)
        xml_bytes = builder.serialize()
    """

    def __init__(
        self,
        substation_name: str,
        eq_model_urn: Optional[str] = None,
        pe_model_urn: Optional[str] = None,
        model_description: Optional[str] = None,
        equipment_mapping: Optional[Dict[str, str]] = None,
    ):
        self.substation_name = substation_name
        self.eq_model_urn = eq_model_urn
        self.pe_model_urn = pe_model_urn
        self.model_urn = f"urn:uuid:{_deterministic_uuid('sc-model', substation_name)}"
        self.model_description = model_description or (
            f"SCADA Configuration profile for {substation_name}"
        )
        # Maps RTAC tag names/patterns → CIM equipment mRIDs from EQ profile
        self.equipment_mapping = equipment_mapping or {}

        # Collected elements
        self._remote_units: Dict[str, Element] = {}   # map_name → element
        self._measurements: List[Element] = []
        self._remote_sources: List[Element] = []
        self._remote_controls: List[Element] = []
        self._comm_links: List[Element] = []
        self._dataflows: List[Element] = []

        # Stats
        self.stats = {
            "remote_units": 0,
            "analog_points": 0,
            "discrete_points": 0,
            "accumulator_points": 0,
            "control_points": 0,
            "data_flows": 0,
        }

    def add_devices(self, devices: List[Dict]) -> None:
        """
        Add RTAC devices as cim:RemoteUnit instances.

        Captures ALL device types — both server devices (SCADA masters the
        RTAC serves data TO) and client devices (relays/IEDs the RTAC reads
        FROM).  The ``role`` field distinguishes them:
        - "server": downstream masters (EMS, SCADA host)
        - "client": upstream IEDs, relays, meters
        - "device": unknown role

        The RTAC itself does not appear as a device in the export — it IS
        the export source.  Call ``set_rtu_identity()`` to add it as the
        central node.
        """
        for dev in devices:
            device_name = dev.get("name") or dev.get("device_name", "UnknownDevice")
            map_name = dev.get("map_name", device_name)
            source_file = dev.get("_source_file", "")
            protocol = dev.get("protocol", "")
            role = dev.get("role", "device")
            manufacturer = dev.get("manufacturer", "")
            model = dev.get("model", "")

            mrid = _make_mrid("rtu", self.substation_name, map_name)

            rtu = Element(f"{{{CIM_NS}}}RemoteUnit")
            rtu.set(f"{{{RDF_NS}}}ID", mrid)

            name_el = SubElement(rtu, f"{{{CIM_NS}}}IdentifiedObject.name")
            name_el.text = device_name

            mrid_el = SubElement(rtu, f"{{{CIM_NS}}}IdentifiedObject.mRID")
            mrid_el.text = mrid

            # Map role to CIM RemoteUnitType
            if role == "server":
                ru_type = "RemoteUnitType.ControlCenter"
            elif role == "client":
                ru_type = "RemoteUnitType.IED"
            else:
                ru_type = "RemoteUnitType.RTU"

            type_el = SubElement(rtu, f"{{{CIM_NS}}}RemoteUnit.remoteUnitType")
            type_el.set(f"{{{RDF_NS}}}resource", f"{CIM_NS}{ru_type}")

            # Verance extensions
            if source_file:
                sf_el = SubElement(rtu, f"{{{VER_NS}}}RemoteUnit.sourceFile")
                sf_el.text = source_file

            if map_name:
                mn_el = SubElement(rtu, f"{{{VER_NS}}}RemoteUnit.mapName")
                mn_el.text = map_name

            if protocol:
                pr_el = SubElement(rtu, f"{{{VER_NS}}}RemoteUnit.protocol")
                pr_el.text = protocol

            if role:
                rl_el = SubElement(rtu, f"{{{VER_NS}}}RemoteUnit.role")
                rl_el.text = role

            if manufacturer:
                mf_el = SubElement(rtu, f"{{{VER_NS}}}RemoteUnit.manufacturer")
                mf_el.text = manufacturer

            if model:
                md_el = SubElement(rtu, f"{{{VER_NS}}}RemoteUnit.model")
                md_el.text = model

            self._remote_units[map_name] = rtu
            self.stats["remote_units"] += 1

    def set_rtu_identity(self, rtu_name: str) -> None:
        """
        Add the RTAC itself as the central RemoteUnit node.

        The RTAC doesn't appear as a device in its own export — it IS the
        export source.  This method creates a special central node that all
        client devices read from and all server devices receive from.

        Args:
            rtu_name: The RTU/RTAC identifier (e.g. "ORS1-PPC-R151")
        """
        mrid = _make_mrid("rtac", self.substation_name, rtu_name)

        rtu = Element(f"{{{CIM_NS}}}RemoteUnit")
        rtu.set(f"{{{RDF_NS}}}ID", mrid)

        name_el = SubElement(rtu, f"{{{CIM_NS}}}IdentifiedObject.name")
        name_el.text = rtu_name

        mrid_el = SubElement(rtu, f"{{{CIM_NS}}}IdentifiedObject.mRID")
        mrid_el.text = mrid

        type_el = SubElement(rtu, f"{{{CIM_NS}}}RemoteUnit.remoteUnitType")
        type_el.set(f"{{{RDF_NS}}}resource", f"{CIM_NS}RemoteUnitType.SubstationControlSystem")

        role_el = SubElement(rtu, f"{{{VER_NS}}}RemoteUnit.role")
        role_el.text = "rtu"

        self._remote_units[f"__rtac__{rtu_name}"] = rtu
        self.stats["remote_units"] += 1

    def add_points(self, points: List[Dict]) -> None:
        """
        Add RTAC points as CIM Measurement/Control instances.

        Each point becomes:
        - cim:Analog, cim:Discrete, cim:Accumulator, or cim:Control
        - cim:RemoteSource or cim:RemoteControl linking to RemoteUnit
        - ver:SCADAPoint extensions for RTAC-specific metadata
        """
        for pt in points:
            tag_name = pt.get("name", "")
            address = pt.get("address", "")
            data_type = pt.get("type", "")
            description = pt.get("description", "")
            map_name = pt.get("map_name", "")
            source_file = pt.get("_source_file", "")

            if not tag_name:
                continue

            cim_class = _RTAC_TO_CIM_CLASS.get(data_type, "Discrete")
            point_type = _RTAC_TO_POINT_TYPE.get(data_type, "BI")
            is_control = data_type in _CONTROL_TYPES

            mrid = _make_mrid("pt", self.substation_name, tag_name)

            # ── Build measurement/control element ──
            if is_control:
                elem = Element(f"{{{CIM_NS}}}Control")
                self.stats["control_points"] += 1
            elif cim_class == "Analog":
                elem = Element(f"{{{CIM_NS}}}Analog")
                self.stats["analog_points"] += 1
            elif cim_class == "Accumulator":
                elem = Element(f"{{{CIM_NS}}}Accumulator")
                self.stats["accumulator_points"] += 1
            else:
                elem = Element(f"{{{CIM_NS}}}Discrete")
                self.stats["discrete_points"] += 1

            elem.set(f"{{{RDF_NS}}}ID", mrid)

            # Standard CIM attributes
            n = SubElement(elem, f"{{{CIM_NS}}}IdentifiedObject.name")
            n.text = tag_name

            m = SubElement(elem, f"{{{CIM_NS}}}IdentifiedObject.mRID")
            m.text = mrid

            if description:
                d = SubElement(elem, f"{{{CIM_NS}}}IdentifiedObject.description")
                d.text = description

            if not is_control:
                mt = SubElement(elem, f"{{{CIM_NS}}}Measurement.measurementType")
                mt.text = point_type

            # ── Link to EQ profile equipment (if mapping exists) ──
            eq_mrid = self._resolve_equipment_mrid(tag_name, map_name)
            if eq_mrid:
                if is_control:
                    psr = SubElement(elem, f"{{{CIM_NS}}}Control.PowerSystemResource")
                else:
                    psr = SubElement(elem, f"{{{CIM_NS}}}Measurement.PowerSystemResource")
                psr.set(f"{{{RDF_NS}}}resource", f"#{eq_mrid}")

            # ── Verance SCADA extensions ──
            if address:
                addr_el = SubElement(elem, f"{{{VER_NS}}}SCADAPoint.dnp3Address")
                addr_el.text = str(address)

            proto_el = SubElement(elem, f"{{{VER_NS}}}SCADAPoint.protocol")
            proto_el.text = "DNP3"

            dt_el = SubElement(elem, f"{{{VER_NS}}}SCADAPoint.dataType")
            dt_el.text = data_type

            tn_el = SubElement(elem, f"{{{VER_NS}}}SCADAPoint.tagName")
            tn_el.text = tag_name

            if source_file:
                sf = SubElement(elem, f"{{{VER_NS}}}SCADAPoint.sourceFile")
                sf.text = source_file

            self._measurements.append(elem)

            # ── RemoteSource / RemoteControl linking point → RTU ──
            rtu_mrid = self._resolve_rtu_mrid(map_name)
            if rtu_mrid:
                if is_control:
                    rc_mrid = _make_mrid("rc", self.substation_name, tag_name)
                    rc = Element(f"{{{CIM_NS}}}RemoteControl")
                    rc.set(f"{{{RDF_NS}}}ID", rc_mrid)
                    ref = SubElement(rc, f"{{{CIM_NS}}}RemoteControl.Control")
                    ref.set(f"{{{RDF_NS}}}resource", f"#{mrid}")
                    rtu_ref = SubElement(rc, f"{{{CIM_NS}}}RemotePoint.RemoteUnit")
                    rtu_ref.set(f"{{{RDF_NS}}}resource", f"#{rtu_mrid}")
                    self._remote_controls.append(rc)
                else:
                    rs_mrid = _make_mrid("rs", self.substation_name, tag_name)
                    rs = Element(f"{{{CIM_NS}}}RemoteSource")
                    rs.set(f"{{{RDF_NS}}}ID", rs_mrid)
                    ref = SubElement(rs, f"{{{CIM_NS}}}RemoteSource.MeasurementValue")
                    ref.set(f"{{{RDF_NS}}}resource", f"#{mrid}")
                    rtu_ref = SubElement(rs, f"{{{CIM_NS}}}RemotePoint.RemoteUnit")
                    rtu_ref.set(f"{{{RDF_NS}}}resource", f"#{rtu_mrid}")
                    self._remote_sources.append(rs)

    def _resolve_equipment_mrid(self, tag_name: str, map_name: str) -> Optional[str]:
        """Try to resolve an EQ profile equipment mRID from the tag name."""
        # Direct lookup
        if tag_name in self.equipment_mapping:
            return self.equipment_mapping[tag_name]
        # Try map_name prefix
        if map_name and map_name in self.equipment_mapping:
            return self.equipment_mapping[map_name]
        return None

    def _resolve_rtu_mrid(self, map_name: str) -> Optional[str]:
        """Get the RemoteUnit mRID for a given map name."""
        if map_name and map_name in self._remote_units:
            return self._remote_units[map_name].get(f"{{{RDF_NS}}}ID")
        # If only one RTU, default to it
        if len(self._remote_units) == 1:
            return list(self._remote_units.values())[0].get(f"{{{RDF_NS}}}ID")
        return None

    def serialize(self) -> bytes:
        """Serialize to CIM RDF/XML bytes."""
        # Register namespace prefixes so ET uses rdf/cim/md/ver instead of ns0/ns1/…
        ET.register_namespace("rdf", RDF_NS)
        ET.register_namespace("cim", CIM_NS)
        ET.register_namespace("md", MD_NS)
        ET.register_namespace("ver", VER_NS)

        # ── Build the RDF root ──
        root = Element(f"{{{RDF_NS}}}RDF")

        # ── FullModel header ──
        header = SubElement(root, f"{{{MD_NS}}}FullModel")
        header.set(f"{{{RDF_NS}}}about", self.model_urn)

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        st = SubElement(header, f"{{{MD_NS}}}Model.scenarioTime")
        st.text = ts
        cr = SubElement(header, f"{{{MD_NS}}}Model.created")
        cr.text = ts
        desc = SubElement(header, f"{{{MD_NS}}}Model.description")
        desc.text = self.model_description
        auth = SubElement(header, f"{{{MD_NS}}}Model.modelingAuthoritySet")
        auth.text = f"http://verance.ai/SA/{self.substation_name}"
        prof = SubElement(header, f"{{{MD_NS}}}Model.profile")
        prof.text = PROFILE_URI

        if self.eq_model_urn:
            dep = SubElement(header, f"{{{MD_NS}}}Model.DependentOn")
            dep.set(f"{{{RDF_NS}}}resource", self.eq_model_urn)
        if self.pe_model_urn:
            dep = SubElement(header, f"{{{MD_NS}}}Model.DependentOn")
            dep.set(f"{{{RDF_NS}}}resource", self.pe_model_urn)

        # ── Append all elements ──
        for rtu in self._remote_units.values():
            root.append(rtu)
        for m in self._measurements:
            root.append(m)
        for rs in self._remote_sources:
            root.append(rs)
        for rc in self._remote_controls:
            root.append(rc)
        for cl in self._comm_links:
            root.append(cl)
        for df in self._dataflows:
            root.append(df)

        # Pretty-print
        indent(root, space="  ")

        xml_declaration = b'<?xml version="1.0" encoding="UTF-8"?>\n'
        body = tostring(root, encoding="unicode", xml_declaration=False)

        return xml_declaration + body.encode("utf-8")

    def get_stats(self) -> Dict:
        """Return generation statistics."""
        total = sum([
            self.stats["analog_points"],
            self.stats["discrete_points"],
            self.stats["accumulator_points"],
            self.stats["control_points"],
        ])
        return {
            **self.stats,
            "total_points": total,
            "substation": self.substation_name,
            "model_urn": self.model_urn,
        }


# ─── Convenience function ────────────────────────────────────────────────


def generate_sc_profile(
    devices: List[Dict],
    points: List[Dict],
    substation_name: str,
    rtu_name: Optional[str] = None,
    eq_model_urn: Optional[str] = None,
    pe_model_urn: Optional[str] = None,
    equipment_mapping: Optional[Dict[str, str]] = None,
) -> Tuple[bytes, Dict]:
    """
    Generate SC profile XML from parsed RTAC data.

    Args:
        devices: Parsed RTAC devices (both client and server)
        points: Parsed RTAC points
        substation_name: Name for the substation this profile belongs to
        rtu_name: RTU/RTAC identifier (e.g. "ORS1-PPC-R151"); added as central node
        eq_model_urn: URN of the dependent EQ profile (optional)
        pe_model_urn: URN of the dependent PE profile (optional)
        equipment_mapping: Dict mapping RTAC tag names → CIM equipment mRIDs

    Returns:
        Tuple of (xml_bytes, stats_dict)
    """
    builder = SCProfileBuilder(
        substation_name=substation_name,
        eq_model_urn=eq_model_urn,
        pe_model_urn=pe_model_urn,
        equipment_mapping=equipment_mapping,
    )
    if rtu_name:
        builder.set_rtu_identity(rtu_name)
    builder.add_devices(devices)
    builder.add_points(points)
    return builder.serialize(), builder.get_stats()


def generate_sc_profile_from_bytes(
    xml_bytes: bytes,
    filename: str,
    substation_name: str,
    eq_model_urn: Optional[str] = None,
    equipment_mapping: Optional[Dict[str, str]] = None,
) -> Tuple[bytes, Dict]:
    """
    Parse RTAC XML bytes and generate SC profile in one step.

    Args:
        xml_bytes: Raw RTAC XML content
        filename: Original filename
        substation_name: Substation name for the profile
        eq_model_urn: URN of dependent EQ profile
        equipment_mapping: Tag name → equipment mRID mapping

    Returns:
        Tuple of (sc_profile_xml_bytes, stats_dict)
    """
    from rtac_plg.parser import parse_rtac_xml_bytes

    devices, points = parse_rtac_xml_bytes(xml_bytes, filename=filename)
    return generate_sc_profile(
        devices, points, substation_name,
        eq_model_urn=eq_model_urn,
        equipment_mapping=equipment_mapping,
    )
