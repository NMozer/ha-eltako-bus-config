"""Installations ("Anlagen"): one per FAM14, identified by its base ID.

A house can have several FAM14 in different distribution boards. All of
them live in one project: device memory as last read (or imported), channel
names, the FAM14's radio feedback list and changes planned while the
installation was not connected.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
import re
from typing import Any

from .protocol import id_add, str_to_id

NO_FAM = "OHNE-FAM14"  # key for a bus without FAM14 (direct RS485 adapter)
PROJECT_FORMAT = "eltako_bus_config_project"
PROJECT_VERSION = 1

Loader = Callable[[], Awaitable[dict[str, Any] | None]]
Saver = Callable[[dict[str, Any]], None]

_BASE_RE = re.compile(r"^[0-9A-F]{2}(-[0-9A-F]{2}){3}$")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def valid_site_id(site_id: str) -> bool:
    return site_id == NO_FAM or bool(_BASE_RE.match(site_id))


def new_site(site_id: str, **fields: Any) -> dict[str, Any]:
    site = {
        "id": site_id,
        "base_id": site_id if site_id != NO_FAM else None,
        "name": "",
        "location": "",
        "source": "bus",
        "created": _now(),
        "updated": _now(),
        "devices": [],
        "last_scan": None,
        "channels": {},
        "device_names": {},
        "feedback": [],
        "operating_mode": None,
        "pending": {},
        "pct_entries": {},
    }
    site.update(fields)
    return site


class SiteStore:
    """All installations of the house plus house-wide settings."""

    def __init__(self, load: Loader, save: Saver) -> None:
        self._load = load
        self._save = save
        self.sites: dict[str, dict[str, Any]] = {}
        self.active: str | None = None
        self.house: dict[str, Any] = {"stick_base_id": None}

    async def async_load(self) -> None:
        data = await self._load() or {}
        self.sites = {s["id"]: s for s in data.get("sites", []) if valid_site_id(s.get("id", ""))}
        for site in self.sites.values():
            for key, default in new_site(site["id"]).items():
                site.setdefault(key, default)
        self.active = data.get("active") if data.get("active") in self.sites else None
        self.house.update(data.get("house") or {})

    def persist(self) -> None:
        self._save({"sites": list(self.sites.values()), "active": self.active, "house": dict(self.house)})

    # ---------------------------------------------------------------- basics
    def get(self, site_id: str | None) -> dict[str, Any] | None:
        return self.sites.get(site_id) if site_id else None

    @property
    def current(self) -> dict[str, Any] | None:
        return self.get(self.active)

    def ensure(self, site_id: str, **fields: Any) -> dict[str, Any]:
        if not valid_site_id(site_id):
            raise ValueError(f"Ungültige Anlagen-ID: {site_id}")
        site = self.sites.get(site_id)
        if site is None:
            site = self.sites[site_id] = new_site(site_id, **fields)
        return site

    def select(self, site_id: str) -> dict[str, Any]:
        site = self.sites.get(site_id)
        if site is None:
            raise KeyError(f"Anlage {site_id} ist nicht bekannt")
        self.active = site_id
        self.persist()
        return site

    def update_meta(self, site_id: str, *, name: str | None = None, location: str | None = None) -> dict[str, Any]:
        site = self.sites[site_id]
        if name is not None:
            site["name"] = name.strip()
        if location is not None:
            site["location"] = location.strip()
        site["updated"] = _now()
        self.persist()
        return site

    def delete(self, site_id: str) -> None:
        self.sites.pop(site_id, None)
        if self.active == site_id:
            self.active = next(iter(self.sites), None)
        self.persist()

    def store_devices(self, site_id: str, devices: list[dict[str, Any]], last_scan: str | None) -> dict[str, Any]:
        site = self.ensure(site_id)
        site["devices"] = devices
        site["last_scan"] = last_scan
        site["updated"] = _now()
        if site.get("source") == "pct14" and last_scan:
            site["source"] = "pct14+bus"
        self.persist()
        return site

    # ------------------------------------------------------------- channels
    def channels(self, site_id: str | None) -> dict[str, str]:
        site = self.get(site_id)
        return dict(site["channels"]) if site else {}

    def rename_channel(self, site_id: str, address: int, name: str) -> dict[str, str]:
        site = self.sites[site_id]
        name = (name or "").strip()
        if name:
            site["channels"][str(address)] = name
        else:
            site["channels"].pop(str(address), None)
        self.persist()
        return dict(site["channels"])

    # -------------------------------------------------------------- pending
    def set_pending(self, site_id: str, pending: dict[str, dict[str, str]]) -> dict[str, Any]:
        site = self.sites[site_id]
        clean: dict[str, dict[str, str]] = {}
        for addr, rows in (pending or {}).items():
            rows = {str(int(r)): v.lower() for r, v in rows.items() if re.fullmatch(r"[0-9a-fA-F]{16}", v)}
            if rows:
                clean[str(int(addr))] = rows
        site["pending"] = clean
        self.persist()
        return site

    def merge_pending(self, site_id: str, address: int, rows: dict[int, str]) -> None:
        site = self.sites[site_id]
        cur = site["pending"].setdefault(str(address), {})
        for row, value in rows.items():
            cur[str(row)] = value
        self.persist()

    def clear_pending(self, site_id: str, address: int, rows: list[int] | None = None) -> None:
        site = self.get(site_id)
        if not site:
            return
        cur = site["pending"].get(str(address))
        if cur is None:
            return
        if rows is None:
            site["pending"].pop(str(address), None)
        else:
            for row in rows:
                cur.pop(str(row), None)
            if not cur:
                site["pending"].pop(str(address), None)
        self.persist()

    # ------------------------------------------------------------ feedback
    @staticmethod
    def feedback_ids(site: dict[str, Any]) -> list[dict[str, Any]]:
        """Radio IDs the FAM14 uses for the state of its bus devices (base ID + bus address)."""
        if not site.get("base_id"):
            return []
        base = str_to_id(site["base_id"])
        from .protocol import id_to_str

        return [{"address": f["address"], "id": id_to_str(id_add(base, f["address"])),
                 "devicetype": f.get("devicetype")} for f in site.get("feedback", [])]

    # --------------------------------------------------------------- export
    def summary(self, connected_id: str | None) -> list[dict[str, Any]]:
        out = []
        for site in sorted(self.sites.values(), key=lambda s: (s.get("name") or "~", s["id"])):
            devs = [d for d in site["devices"] if not d.get("is_fam")]
            out.append({
                "id": site["id"],
                "base_id": site["base_id"],
                "name": site["name"],
                "location": site["location"],
                "source": site["source"],
                "devices": len(devs),
                "read": sum(1 for d in devs if d.get("memory") and all(r is not None for r in d["memory"])),
                "last_scan": site["last_scan"],
                "updated": site["updated"],
                "pending": sum(len(r) for r in site["pending"].values()),
                "feedback": self.feedback_ids(site),
                "operating_mode": site["operating_mode"],
                "active": site["id"] == self.active,
                "connected": site["id"] == connected_id,
            })
        return out

    def export_sites(self) -> list[dict[str, Any]]:
        return [dict(s) for s in self.sites.values()]

    def import_site(self, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Merge an installation from a project file. Returns (site, created)."""
        site_id = data.get("id") or data.get("base_id")
        if not site_id or not valid_site_id(site_id):
            raise ValueError("Anlage ohne gültige Basis-ID in der Projektdatei")
        created = site_id not in self.sites
        site = self.ensure(site_id)
        for key in ("name", "location", "operating_mode"):
            if data.get(key) not in (None, ""):
                site[key] = data[key]
        if data.get("feedback"):
            site["feedback"] = data["feedback"]
        if data.get("devices") and (created or not site["devices"] or
                                    (data.get("last_scan") or "") > (site.get("last_scan") or "")):
            site["devices"] = data["devices"]
            site["last_scan"] = data.get("last_scan")
        for key in ("channels", "device_names", "pct_entries"):
            for k, v in (data.get(key) or {}).items():
                site[key].setdefault(k, v)
        for addr, rows in (data.get("pending") or {}).items():
            site["pending"].setdefault(addr, {}).update(rows)
        if created:
            site["source"] = data.get("source") or "project"
        site["updated"] = _now()
        return site, created

    def used_ids(self) -> set[str]:
        """All sender IDs present in any ID table or planned change of any installation."""
        from . import catalog
        from .protocol import id_to_str

        used: set[str] = set()
        for site in self.sites.values():
            for dev in site["devices"]:
                mem = dev.get("memory") or []
                try:
                    dt = catalog.identify(bytes.fromhex(dev["model"]), int(dev["size"]))
                except (KeyError, ValueError):
                    continue
                for g in catalog.groups_for(dt, len(mem)):
                    for row in range(g.start, g.end):
                        val = mem[row] if row < len(mem) else None
                        if val and any(bytes.fromhex(val)[:4]):
                            used.add(id_to_str(bytes.fromhex(val)[:4]))
            for rows in site["pending"].values():
                for val in rows.values():
                    if any(bytes.fromhex(val)[:4]):
                        used.add(id_to_str(bytes.fromhex(val)[:4]))
        return used
