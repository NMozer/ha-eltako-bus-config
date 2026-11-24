"""Import of PCT14 XML exports ("exchange" format).

A PCT14 export describes one FAM14 installation: the FAM14 itself (base ID,
operating mode, list of bus addresses whose state it transmits by radio) and
every bus device with its header, channel descriptions and ID table entries.

Mapping of ID table entries to memory rows has been verified for the FSB14
against a bus read of the same installation (row = first ID row + entry - 1,
entry_id = sender ID as little-endian integer). For other device types the
entries are kept for display only until they are verified the same way.
"""

from __future__ import annotations

from typing import Any
import xml.etree.ElementTree as ET

from . import catalog
from .protocol import id_to_str

FORMAT = "pct14_xml"

# Device types whose entry_number -> memory row mapping was checked on real hardware
VERIFIED_ID_ROWS: frozenset[str] = frozenset({"FSB14"})

MAX_XML_SIZE = 5 * 1024 * 1024


class Pct14Error(ValueError):
    """The file is not a usable PCT14 export."""


def _int(node: ET.Element | None, default: int = 0) -> int:
    if node is None or node.text is None or not node.text.strip():
        return default
    try:
        return int(node.text.strip())
    except ValueError:
        return default


def _text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def _header(dev: ET.Element) -> dict[str, int]:
    h = dev.find("header")
    if h is None:
        raise Pct14Error("Gerät ohne Kopfdaten")
    keys = ("address", "addressrange", "numberofblocks", "offsetfirstblock", "versionofinstructionmanual",
            "devicetype", "versionofsoftware", "reservedbyte")
    return {k: _int(h.find(k)) for k in keys}


def _model(h: dict[str, int]) -> bytes:
    """The 4 model bytes as reported by bus discovery (manual version, type, software, reserved)."""
    return bytes((h["versionofinstructionmanual"] & 0xFF, h["devicetype"] & 0xFF,
                  h["versionofsoftware"] & 0xFF, h["reservedbyte"] & 0xFF))


def entry_id_to_str(value: int) -> str:
    return id_to_str((value & 0xFFFFFFFF).to_bytes(4, "little"))


def parse(xml_text: str) -> dict[str, Any]:
    """Parse a PCT14 export into a plain dict."""
    if len(xml_text) > MAX_XML_SIZE:
        raise Pct14Error("Datei ist zu groß für einen PCT14-Export")
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        raise Pct14Error("XML mit DOCTYPE/ENTITY wird nicht unterstützt")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as err:
        raise Pct14Error(f"Keine gültige XML-Datei: {err}") from err
    if root.tag != "exchange":
        raise Pct14Error("Kein PCT14-Export (Wurzelelement „exchange“ fehlt)")

    rootdev = root.find("rootdevice")
    if rootdev is None:
        raise Pct14Error("Der Export enthält keinen FAM14 (rootdevice)")
    data = rootdev.find("rootdevicedata")
    base = data.find("baseid") if data is not None else None
    if base is None:
        raise Pct14Error("Der Export enthält keine Basis-ID des FAM14")
    base_bytes = bytes(_int(base.find(f"baseid_byte_{i}")) & 0xFF for i in range(4))
    if not any(base_bytes):
        raise Pct14Error("Basis-ID des FAM14 ist leer")
    feedback = []
    fl = data.find("feedbacklist")
    if fl is not None:
        for fe in fl.findall("feedbackentry"):
            feedback.append({
                "address": _int(fe.find("feedbackentry_deviceaddress")),
                "devicetype": _int(fe.find("feedbackentry_devicetype")),
            })
    fam_header = _header(rootdev)

    devices = []
    devs = root.find("devices")
    for dev in devs.findall("device") if devs is not None else []:
        h = _header(dev)
        channels = {}
        chs = dev.find("channels")
        for ch in chs.findall("channel") if chs is not None else []:
            desc = (ch.get("description") or "").strip()
            try:
                number = int(ch.get("channelnumber", "0"))
            except ValueError:
                continue
            if desc and number > 0:
                channels[number] = desc
        entries = []
        rid = dev.find("data/rangeofid")
        for e in rid.findall("entry") if rid is not None else []:
            entries.append({
                "number": _int(e.find("entry_number")),
                "id": entry_id_to_str(_int(e.find("entry_id"))),
                "function": _int(e.find("entry_function")),
                "key": _int(e.find("entry_button")),
                "channel": _int(e.find("entry_channel")),
                "value": _int(e.find("entry_value")),
                "description": (e.get("description") or "").strip(),
            })
        devices.append({
            "name": _text(dev.find("name")),
            "description": _text(dev.find("description")),
            "address": h["address"],
            "size": max(1, h["addressrange"]),
            "memory_size": h["numberofblocks"],
            "model": _model(h).hex(),
            "offsetfirstblock": h["offsetfirstblock"],
            "channels": channels,
            "entries": entries,
        })

    return {
        "format": FORMAT,
        "version": root.get("version"),
        "base_id": id_to_str(base_bytes),
        "description": _text(rootdev.find("description")),
        "operating_mode": _int(data.find("operatingmode"), -1),
        "feedback": feedback,
        "fam_model": _model(fam_header).hex(),
        "devices": devices,
    }


def first_id_row(dt: catalog.DeviceType, memory_size: int) -> int | None:
    groups = catalog.groups_for(dt, memory_size)
    return min((g.start for g in groups), default=None)


def entry_row(dt: catalog.DeviceType, memory_size: int, number: int) -> int | None:
    first = first_id_row(dt, memory_size)
    if first is None or number < 1:
        return None
    row = first + number - 1
    return row if row < memory_size else None


def encode_entry(e: dict[str, Any]) -> bytes:
    sid = bytes.fromhex(e["id"].replace("-", ""))
    return sid + bytes((e["key"] & 0xFF, e["function"] & 0xFF, e["channel"] & 0xFF, e["value"] & 0xFF))


def device_memory(dev: dict[str, Any]) -> tuple[list[str | None], bool]:
    """Memory rows (hex or None) reconstructed from the ID table, and whether that was possible."""
    model = bytes.fromhex(dev["model"])
    dt = catalog.identify(model, dev["size"])
    memory: list[str | None] = [None] * dev["memory_size"]
    if dt.key not in VERIFIED_ID_ROWS:
        return memory, False
    for g in catalog.groups_for(dt, dev["memory_size"]):
        for row in range(g.start, g.end):
            memory[row] = "00" * 8
    for e in dev["entries"]:
        row = entry_row(dt, dev["memory_size"], e["number"])
        if row is not None:
            memory[row] = encode_entry(e).hex()
    return memory, True


def channel_names(dev: dict[str, Any]) -> dict[str, str]:
    """Channel descriptions keyed by the bus address of the channel."""
    return {str(dev["address"] + number - 1): name for number, name in dev["channels"].items()}
