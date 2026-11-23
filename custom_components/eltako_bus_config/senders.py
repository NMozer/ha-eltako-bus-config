"""Persistent list of senders seen on the bus (PCT14 'ID-Erkennung')."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from .protocol import RadioTelegram, id_to_str

Loader = Callable[[], Awaitable[dict[str, Any] | None]]
Saver = Callable[[dict[str, Any]], None]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def classify(tel: RadioTelegram) -> str:
    sender = tel.sender
    if sender[:3] == b"\x00\x00\x00":
        return "bus_device"  # feedback of a bus actuator
    if sender[:3] == b"\x00\x00\xb0":
        return "bus_sender"  # e.g. FGW14-USB / Home Assistant
    if tel.rocker:
        return "rocker"
    if tel.window_handle:
        return "window_handle"
    if tel.org == 0x06:
        return "contact"
    if tel.org == 0x07:
        return "sensor"
    return "rps"


class SenderStore:
    """Senders with user given names, kept across restarts."""

    def __init__(self, load: Loader, save: Saver) -> None:
        self._load = load
        self._save = save
        self.senders: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        data = await self._load() or {}
        self.senders = {s["id"]: s for s in data.get("senders", []) if "id" in s}

    def _persist(self) -> None:
        self._save({"senders": list(self.senders.values())})

    def list(self) -> list[dict[str, Any]]:
        return sorted(self.senders.values(), key=lambda s: (s.get("name") or "~", s["id"]))

    def observe(self, tel: RadioTelegram) -> dict[str, Any]:
        sid = id_to_str(tel.sender)
        now = _now()
        entry = self.senders.get(sid)
        if entry is None:
            entry = self.senders[sid] = {
                "id": sid,
                "name": "",
                "kind": classify(tel),
                "org": tel.kind,
                "eep": None,
                "keys": [],
                "count": 0,
                "first_seen": now,
            }
        kind = classify(tel)
        if entry["kind"] in ("unknown", "rps", "sensor") and kind not in ("rps", "sensor"):
            entry["kind"] = kind
        entry["count"] += 1
        entry["last_seen"] = now
        entry["last_data"] = tel.data.hex(" ")
        if tel.eep:
            entry["eep"] = tel.eep
        is_release = tel.org == 0x05 and (tel.status & 0x10) == 0 and tel.data[0] == 0x00
        if not is_release:
            entry["presses"] = entry.get("presses", 0) + 1
        if rocker := tel.rocker:
            key, direction = rocker
            if key not in entry["keys"]:
                entry["keys"] = sorted([*entry["keys"], key])
            entry["last_press"] = {"key": key, "direction": direction, "at": now}
        if tel.is_teach_in:
            entry["teach_in"] = True
        self._persist()
        return entry

    def add_known(self, sid: str, *, kind: str = "unknown", key: int | None = None) -> dict[str, Any]:
        """Register a sender found in a device's ID table (not seen live)."""
        entry = self.senders.setdefault(
            sid, {"id": sid, "name": "", "kind": kind, "org": None, "eep": None, "keys": [], "count": 0,
                  "first_seen": _now(), "from_memory": True}
        )
        if key in (5, 6) and key not in entry["keys"]:
            entry["keys"] = sorted([*entry["keys"], key])
        self._persist()
        return entry

    def update(self, sid: str, **changes: Any) -> dict[str, Any]:
        entry = self.senders.get(sid)
        if entry is None:
            entry = self.add_known(sid)
        for key in ("name", "kind", "hidden"):
            if key in changes and changes[key] is not None:
                entry[key] = changes[key]
        self._persist()
        return entry

    def delete(self, sid: str) -> None:
        self.senders.pop(sid, None)
        self._persist()

    def clear_unnamed(self) -> int:
        before = len(self.senders)
        self.senders = {k: v for k, v in self.senders.items() if v.get("name")}
        self._persist()
        return before - len(self.senders)
