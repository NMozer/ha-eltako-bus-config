"""High level bus operations: scan, read/write memory, backups."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import re
import time
from typing import Any

from . import catalog, pct14
from .protocol import (
    FAM_ADDRESS,
    DiscoveryReply,
    Frame,
    bus_lock,
    bus_unlock,
    discovery_request,
    id_to_str,
    identify_request,
    is_memory_response,
    is_org_response,
    memory_read_request,
    memory_select_request,
    memory_write_request,
    ORG_MEM_SELECT,
    ORG_MEM_WRITE,
    central_switch_data,
    id_add,
    parse_discovery_reply,
    parse_radio,
    radio_4bs_request,
    radio_rps_request,
    str_to_id,
    teach_in_4bs_data,
    TEACH_IN_EEPS,
)
from .senders import SenderStore
from .sites import NO_FAM, PROJECT_FORMAT, PROJECT_VERSION, SiteStore
from .transport import BusTransport, TransportError

_LOGGER = logging.getLogger(__name__)

BACKUP_FORMAT = "eltako_bus_config_backup"
# accepted for import/restore: backups made with the earlier name of this integration
ACCEPTED_BACKUP_FORMATS = (BACKUP_FORMAT, "eltako_pct_backup")
BACKUP_VERSION = 1

ProgressCallback = Callable[[dict[str, Any]], None]
Executor = Callable[..., Awaitable[Any]]


class BusError(Exception):
    """Operation on the bus failed."""


class BusyError(BusError):
    """Another operation is running."""


@dataclass
class BusDevice:
    address: int
    size: int
    memory_size: int
    model: bytes
    is_fam: bool
    memory: list[bytes | None] = field(default_factory=list)
    read_at: str | None = None
    source: str | None = None  # "pct14" for devices known only from a PCT14 export

    @classmethod
    def from_reply(cls, reply: DiscoveryReply) -> BusDevice:
        return cls(
            address=reply.address,
            size=reply.size,
            memory_size=reply.memory_size,
            model=reply.model,
            is_fam=reply.is_fam,
            memory=[None] * reply.memory_size,
        )

    @property
    def device_type(self) -> catalog.DeviceType:
        return catalog.identify(self.model, self.size)

    @property
    def version(self) -> str:
        hi, lo = self.model[2], self.model[3]
        return f"{hi >> 4}.{hi & 0xF}.{lo >> 4}.{lo & 0xF}"

    def as_dict(self) -> dict[str, Any]:
        dt = self.device_type
        return {
            "address": self.address,
            "size": self.size,
            "memory_size": self.memory_size,
            "model": self.model.hex(),
            "version": self.version,
            "is_fam": self.is_fam,
            "type": catalog.device_type_info(dt, self.memory_size),
            "memory": [row.hex() if row is not None else None for row in self.memory],
            "read_at": self.read_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BusDevice:
        return cls(
            address=int(data["address"]),
            size=int(data["size"]),
            memory_size=int(data["memory_size"]),
            model=bytes.fromhex(data["model"]),
            is_fam=bool(data.get("is_fam", False)),
            memory=[bytes.fromhex(r) if r else None for r in data.get("memory", [])],
            read_at=data.get("read_at"),
            source=data.get("source"),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_row(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        row = value
    else:
        row = bytes.fromhex(re.sub(r"[\s\-:]", "", value))
    if len(row) != 8:
        raise ValueError("Eine Speicherzeile hat genau 8 Byte")
    return row


class BackupStore:
    """JSON files in <config>/eltako_bus_config/backups."""

    def __init__(self, base: Path, executor: Executor) -> None:
        self.base = base
        self._exec = executor

    def _list(self) -> list[dict[str, Any]]:
        if not self.base.exists():
            return []
        result = []
        for path in sorted(self.base.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            result.append(
                {
                    "id": path.stem,
                    "name": data.get("name", path.stem),
                    "created": data.get("created"),
                    "kind": data.get("kind", "manual"),
                    "devices": len(data.get("devices", [])),
                    "size": path.stat().st_size,
                }
            )
        return result

    async def list(self) -> list[dict[str, Any]]:
        return await self._exec(self._list)

    def _path(self, backup_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", backup_id):
            raise ValueError("Ungültige Backup-ID")
        return self.base / f"{backup_id}.json"

    async def get(self, backup_id: str) -> dict[str, Any]:
        path = self._path(backup_id)
        return await self._exec(lambda: json.loads(path.read_text("utf-8")))

    async def save(self, data: dict[str, Any], prefix: str = "backup") -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_id = f"{prefix}-{stamp}-{int(time.time() * 1000) % 1000:03d}"
        path = self._path(backup_id)

        def _write() -> None:
            self.base.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1), "utf-8")
            tmp.replace(path)

        await self._exec(_write)
        return backup_id

    async def delete(self, backup_id: str) -> None:
        path = self._path(backup_id)
        await self._exec(lambda: path.unlink(missing_ok=True))


def validate_backup(data: dict[str, Any]) -> list[BusDevice]:
    if data.get("format") not in ACCEPTED_BACKUP_FORMATS:
        raise ValueError("Keine Sicherungsdatei des Bus-Konfigurators für Eltako")
    devices = [BusDevice.from_dict(d) for d in data.get("devices", [])]
    for dev in devices:
        if len(dev.memory) != dev.memory_size:
            raise ValueError(f"Gerät {dev.address}: Speichergröße passt nicht")
    return devices


class BusManager:
    """Serialises all bus access and keeps the device cache."""

    def __init__(
        self,
        transport_factory: Callable[[], BusTransport],
        backups: BackupStore,
        *,
        scan_timeout: float = 0.35,
        scan_retries: int = 1,
        progress: ProgressCallback | None = None,
        on_devices_changed: Callable[[], Awaitable[None]] | None = None,
        senders: SenderStore | None = None,
        sites: SiteStore | None = None,
        bridge: Any = None,
    ) -> None:
        self._transport_factory = transport_factory
        self.backups = backups
        self.scan_timeout = scan_timeout
        self.scan_retries = scan_retries
        self._progress = progress or (lambda _e: None)
        self._on_devices_changed = on_devices_changed
        self._lock = asyncio.Lock()
        self.devices: dict[int, BusDevice] = {}
        self.base_id: str | None = None
        self.last_scan: str | None = None
        self.operation: str | None = None
        self.last_error: str | None = None
        self.bus_locked_by_fam: bool | None = None
        self.echo: bool | None = None
        self.senders: SenderStore | None = senders
        self.sites: SiteStore | None = sites
        self.bridge = bridge
        self._connected: tuple[str, bool] | None = None  # (installation seen on the bus, seen via laptop bridge)
        self.fixed_port = True  # False when only the laptop bridge can reach a bus
        self._stop_listen: asyncio.Event | None = None

    # ------------------------------------------------------------- utilities
    def _emit(self, **event: Any) -> None:
        event.setdefault("operation", self.operation)
        try:
            self._progress(event)
        except Exception:  # pragma: no cover
            _LOGGER.exception("progress callback failed")

    async def _changed(self) -> None:
        if self.sites is not None and self.sites.active:
            self.sites.store_devices(self.sites.active, self._devices_payload(), self.last_scan)
        self.register_known_senders()
        if self._on_devices_changed:
            await self._on_devices_changed()

    def _devices_payload(self) -> list[dict[str, Any]]:
        return [d.as_dict() | {"type": None} for _, d in sorted(self.devices.items())]

    @property
    def connected_id(self) -> str | None:
        """Installation currently on the bus, as far as known (None = unknown / nothing connected)."""
        if self._connected is None:
            return None
        site_id, via_bridge = self._connected
        bridge_now = bool(self.bridge and self.bridge.attached)
        if via_bridge != bridge_now or (not bridge_now and not self.fixed_port):
            return None  # the connection it was seen on is gone
        return site_id

    @connected_id.setter
    def connected_id(self, site_id: str | None) -> None:
        self._connected = None if site_id is None else (site_id, bool(self.bridge and self.bridge.attached))

    @property
    def active_site_id(self) -> str | None:
        return self.sites.active if self.sites is not None else None

    async def _check_site(self, t: BusTransport) -> None:
        """Refuse to touch a bus whose FAM14 does not belong to the selected installation."""
        if self.sites is None or not self.sites.active:
            return
        fam = await self._discover(t, FAM_ADDRESS, timeout=0.6, retries=2)
        connected = NO_FAM
        if fam is not None:
            try:
                connected = id_to_str((await self._read_row(t, FAM_ADDRESS, 1))[:4])
            except BusError:
                return  # FAM present but base ID unreadable: no reliable check possible
        self.connected_id = connected
        if connected != self.sites.active:
            site = self.sites.get(self.sites.active) or {}
            raise BusError(
                f"Am Bus hängt {'kein FAM14' if connected == NO_FAM else f'der FAM14 {connected}'}, ausgewählt ist "
                f"die Anlage „{site.get('name') or self.sites.active}“. Bitte die passende Anlage wählen oder "
                "den Bus neu scannen."
            )

    @contextlib.asynccontextmanager
    async def _session(self, operation: str, *, lock_bus: bool = True):
        if self._lock.locked():
            raise BusyError(f"Bus ist belegt: {self.operation}")
        async with self._lock:
            self.operation = operation
            self.last_error = None
            started = time.monotonic()
            _LOGGER.info("Operation %s started", operation)
            transport = self._transport_factory()
            self._emit(state="start")
            try:
                await transport.open()
                self.echo = transport.suppress_echo
                if lock_bus:
                    self.bus_locked_by_fam = await self._lock_bus(transport)
                    _LOGGER.info("Bus lock acknowledged by FAM: %s", self.bus_locked_by_fam)
                try:
                    yield transport
                finally:
                    if lock_bus and transport.is_open:
                        with contextlib.suppress(Exception):
                            await self._unlock_bus(transport)
            except TransportError as err:
                self.last_error = str(err)
                _LOGGER.error("Operation %s: %s", operation, err)
                raise BusError(str(err)) from err
            except Exception as err:
                self.last_error = str(err)
                _LOGGER.error("Operation %s failed: %s", operation, err, exc_info=not isinstance(err, BusError))
                raise
            finally:
                _LOGGER.info(
                    "Operation %s finished after %.1fs (sent %d, received %d frames, error: %s)",
                    operation, time.monotonic() - started, transport.frames_sent, transport.frames_received,
                    self.last_error,
                )
                await transport.close()
                self._emit(state="done", error=self.last_error)
                self.operation = None

    async def _lock_bus(self, t: BusTransport) -> bool:
        """Lock the bus (FAM14 stops polling). True if a FAM acknowledged."""

        def is_fam_reply(f: Frame) -> bool:
            reply = parse_discovery_reply(f)
            return reply is not None and reply.is_fam

        for _ in range(10):
            if await t.exchange(bus_lock(), is_fam_reply, timeout=0.5, retries=1):
                return True
            await asyncio.sleep(0.2)
        _LOGGER.info("No FAM acknowledged the bus lock - assuming no FAM on the bus")
        return False

    async def _unlock_bus(self, t: BusTransport) -> None:
        def is_fam_reply(f: Frame) -> bool:
            reply = parse_discovery_reply(f)
            return reply is not None and reply.is_fam

        for _ in range(5):
            if await t.exchange(bus_unlock(), is_fam_reply, timeout=0.5, retries=1):
                return
            await asyncio.sleep(0.2)

    async def _discover(self, t: BusTransport, address: int, *, timeout: float, retries: int) -> DiscoveryReply | None:
        def match(f: Frame) -> bool:
            reply = parse_discovery_reply(f)
            return reply is not None and reply.address == address

        frame = await t.exchange(discovery_request(address), match, timeout=timeout, retries=retries)
        return parse_discovery_reply(frame) if frame else None

    async def _read_row(self, t: BusTransport, address: int, row: int) -> bytes:
        frame = await t.exchange(
            memory_read_request(address, row), lambda f: is_memory_response(f, row), timeout=1.0, retries=3
        )
        if frame is None:
            raise BusError(f"Gerät {address}: Zeile {row} konnte nicht gelesen werden")
        return frame.data

    async def _read_memory(self, t: BusTransport, dev: BusDevice, *, progress_base: float = 0, progress_span: float = 1) -> None:
        mem: list[bytes | None] = []
        for row in range(dev.memory_size):
            mem.append(await self._read_row(t, dev.address, row))
            if row % 8 == 0:
                self._emit(
                    state="progress",
                    progress=progress_base + progress_span * (row + 1) / dev.memory_size,
                    message=f"Lese Speicher von Adresse {dev.address} (Zeile {row})",
                )
        dev.memory = mem
        dev.read_at = _now()

    async def _write_row(self, t: BusTransport, address: int, row: int, value: bytes) -> None:
        sel = await t.exchange(
            memory_select_request(address), lambda f: is_org_response(f, ORG_MEM_SELECT), timeout=1.0, retries=3
        )
        if sel is None:
            raise BusError(f"Gerät {address} reagiert nicht auf Schreibauswahl (F2)")
        ack = await t.exchange(
            memory_write_request(row, value), lambda f: is_org_response(f, ORG_MEM_WRITE), timeout=1.5, retries=2
        )
        if ack is None:
            raise BusError(f"Gerät {address}: Schreiben von Zeile {row} nicht bestätigt (F4)")

    async def _read_fam(self, t: BusTransport) -> None:
        fam = await self._discover(t, FAM_ADDRESS, timeout=0.6, retries=3)
        if fam is None:
            _LOGGER.warning("FAM14 did not answer discovery at address 255")
            self.base_id = None
            return
        dev = BusDevice.from_reply(fam)
        dev.address = FAM_ADDRESS  # FAM reports 0xff as well, keep explicit
        try:
            row = await self._read_row(t, FAM_ADDRESS, 1)
            dev.memory[1] = row
            self.base_id = id_to_str(row[:4])
            _LOGGER.info("FAM14 found, base ID %s", self.base_id)
        except BusError:
            self.base_id = None
        self.devices[FAM_ADDRESS] = dev

    # ------------------------------------------------------------ operations
    async def scan(self, *, read_memory: bool = True) -> list[dict[str, Any]]:
        """Enumerate the bus like PCT14 'Geräteliste aktualisieren (und Speicher auslesen)'."""
        async with self._session("scan") as t:
            found: dict[int, BusDevice] = {}
            await self._read_fam(t)
            if FAM_ADDRESS in self.devices:
                found[FAM_ADDRESS] = self.devices[FAM_ADDRESS]
            address = 1
            while address < FAM_ADDRESS:
                self._emit(state="progress", progress=address / 254 * (0.3 if read_memory else 1),
                           message=f"Suche Geräte… Adresse {address}")
                reply = await self._discover(t, address, timeout=self.scan_timeout, retries=self.scan_retries)
                if reply is None:
                    address += 1
                    continue
                dev = BusDevice.from_reply(reply)
                old = self.devices.get(address)
                if old and old.model == dev.model and old.memory_size == dev.memory_size:
                    dev.memory, dev.read_at = old.memory, old.read_at
                found[address] = dev
                _LOGGER.info("Found %s at address %d (size %d, memory %d rows, model %s)",
                             dev.device_type.name, address, dev.size, dev.memory_size, dev.model.hex())
                self._emit(state="device", device=dev.as_dict(), message=f"Gefunden: {dev.device_type.name} @ {address}")
                address += max(1, dev.size)
            if read_memory:
                todo = [d for a, d in sorted(found.items()) if a != FAM_ADDRESS]
                for i, dev in enumerate(todo):
                    await self._read_memory(t, dev, progress_base=0.3 + 0.7 * i / max(1, len(todo)),
                                            progress_span=0.7 / max(1, len(todo)))
            self.devices = found
            self.last_scan = _now()
            self.connected_id = self.base_id or NO_FAM
            if self.sites is not None:
                self.sites.ensure(self.connected_id)
                self.sites.active = self.connected_id
        await self._changed()
        return [d.as_dict() for _, d in sorted(self.devices.items())]

    async def read_device(self, address: int) -> dict[str, Any]:
        async with self._session(f"read:{address}") as t:
            await self._check_site(t)
            reply = await self._discover(t, address, timeout=0.6, retries=3)
            if reply is None:
                raise BusError(f"Kein Gerät an Adresse {address}")
            dev = BusDevice.from_reply(reply)
            if address == FAM_ADDRESS:
                dev.address = FAM_ADDRESS
            await self._read_memory(t, dev)
            self.devices[address] = dev
        await self._changed()
        return dev.as_dict()

    async def write_rows(self, address: int, rows: dict[int, str | bytes], *, verify: bool = True) -> dict[str, Any]:
        """Write changed rows. Takes an automatic device backup before writing."""
        parsed = {int(r): parse_row(v) for r, v in rows.items()}
        if not parsed:
            raise ValueError("Keine Zeilen zum Schreiben")
        async with self._session(f"write:{address}") as t:
            await self._check_site(t)
            reply = await self._discover(t, address, timeout=0.6, retries=3)
            if reply is None:
                raise BusError(f"Kein Gerät an Adresse {address}")
            dev = self.devices.get(address)
            if dev is None or dev.model != reply.model or dev.memory_size != reply.memory_size:
                dev = BusDevice.from_reply(reply)
            for row in parsed:
                if not 0 <= row < dev.memory_size:
                    raise ValueError(f"Zeile {row} außerhalb des Speichers (0–{dev.memory_size - 1})")
            # Safety net: full read + automatic backup before anything is written
            await self._read_memory(t, dev, progress_span=0.4)
            backup_id = await self.backups.save(
                self._backup_payload([dev], name=f"Automatisch vor Schreiben auf Adresse {address}", kind="auto"),
                prefix=f"auto-{address}",
            )
            written = []
            for i, (row, value) in enumerate(sorted(parsed.items())):
                if dev.memory[row] == value:
                    continue
                self._emit(state="progress", progress=0.4 + 0.6 * i / len(parsed),
                           message=f"Schreibe Adresse {address}, Zeile {row}")
                await self._write_row(t, address, row, value)
                if verify:
                    check = await self._read_row(t, address, row)
                    if check != value:
                        raise BusError(
                            f"Verifikation fehlgeschlagen: Adresse {address}, Zeile {row} "
                            f"enthält {check.hex(' ')} statt {value.hex(' ')}"
                        )
                dev.memory[row] = value
                written.append(row)
            dev.read_at = _now()
            self.devices[address] = dev
        if self.sites is not None and self.sites.active:
            self.sites.clear_pending(self.sites.active, address, list(parsed))
        await self._changed()
        return {"device": dev.as_dict(), "written_rows": written, "backup_id": backup_id}

    async def identify(self, address: int) -> None:
        async with self._session(f"identify:{address}", lock_bus=False) as t:
            await t.send(identify_request(address))

    async def probe(self) -> dict[str, Any]:
        """Diagnose whether memory access works over the configured gateway."""
        result: dict[str, Any] = {"fam_lock_ack": False, "fam_found": False, "devices_answering": [],
                                  "memory_read_ok": False}
        async with self._session("probe") as t:
            result["echo"] = t.suppress_echo
            result["fam_lock_ack"] = bool(self.bus_locked_by_fam)
            fam = await self._discover(t, FAM_ADDRESS, timeout=0.6, retries=2)
            result["fam_found"] = fam is not None
            for address in range(1, 17):
                reply = await self._discover(t, address, timeout=0.3, retries=1)
                if reply:
                    result["devices_answering"].append(address)
                    try:
                        row = await self._read_row(t, address, 0)
                        result["memory_read_ok"] = True
                        result["sample_row"] = row.hex(" ")
                    except BusError:
                        pass
                    break
            result["frames_received"] = t.frames_received
        _LOGGER.info("Probe result: %s", result)
        return result

    def stop_listening(self) -> bool:
        """Stop a running listen/monitor operation early."""
        if self._stop_listen is not None:
            self._stop_listen.set()
            return True
        return False

    async def listen(self, seconds: float, *, max_seconds: float = 900.0, lock_bus: bool = False) -> list[dict[str, Any]]:
        """Listen on the bus (unlocked) and collect senders, like PCT14's ID detection.

        Every telegram is also passed to the sender store (if configured) so
        detected switches stay known with their names.
        """
        seen: dict[bytes, dict[str, Any]] = {}
        seconds = max(1.0, min(seconds, max_seconds))

        def on_frame(frame: Frame) -> None:
            tel = parse_radio(frame)
            if tel is None or not any(tel.sender):
                return
            entry = seen.setdefault(
                tel.sender,
                {"sender": id_to_str(tel.sender), "count": 0, "kind": tel.kind,
                 "bus_device": tel.sender[:3] == b"\x00\x00\x00", "teach_in": False},
            )
            entry["count"] += 1
            entry["last_data"] = tel.data.hex(" ")
            entry["teach_in"] = entry["teach_in"] or tel.is_teach_in
            if rocker := tel.rocker:
                entry["key"], entry["direction"] = rocker
            stored = self.senders.observe(tel) if self.senders else None
            _LOGGER.debug("Telegram from %s (%s, data %s)", entry["sender"], tel.kind, entry["last_data"])
            self._emit(state="telegram", telegram=dict(entry), sender=dict(stored) if stored else None)

        self._stop_listen = asyncio.Event()
        try:
            # Verified on hardware: the FAM14 only forwards radio telegrams to its USB port
            # while the bus is NOT locked (locked: no telegrams at all).
            async with self._session("listen", lock_bus=lock_bus) as t:
                remove = t.add_listener(on_frame)
                try:
                    end = time.monotonic() + seconds
                    while (left := end - time.monotonic()) > 0 and not self._stop_listen.is_set():
                        self._emit(state="progress", progress=1 - left / seconds, locked=lock_bus,
                                   message=f"Lausche… noch {int(left)} s – jetzt Taster drücken")
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(self._stop_listen.wait(), timeout=min(1.0, left))
                finally:
                    remove()
        finally:
            self._stop_listen = None
        _LOGGER.info("Listening finished (bus locked: %s): %d sender(s) seen", lock_bus, len(seen))
        return sorted(seen.values(), key=lambda e: (e["bus_device"], -e["count"]))

    def _all_devices(self) -> list[BusDevice]:
        devices = list(self.devices.values())
        if self.sites is not None:
            for site in self.sites.sites.values():
                if site["id"] == self.sites.active:
                    continue
                for d in site["devices"]:
                    with contextlib.suppress(Exception):
                        devices.append(BusDevice.from_dict(d))
        return devices

    def register_known_senders(self) -> None:
        """Make all IDs found in device ID tables (of all installations) known to the sender store."""
        if not self.senders:
            return
        for dev in self._all_devices():
            for g in catalog.groups_for(dev.device_type, dev.memory_size):
                for row in range(g.start, g.end):
                    val = dev.memory[row] if row < len(dev.memory) else None
                    if not val or not any(val[:4]):
                        continue
                    sid = id_to_str(val[:4])
                    kind = "bus_sender" if val[:3] == b"\x00\x00\xb0" else "unknown"
                    self.senders.add_known(sid, kind=kind, key=val[4], function=val[5])
        if self.sites is not None:
            for site in self.sites.sites.values():
                for entries in site.get("pct_entries", {}).values():
                    for e in entries:
                        if e["id"] != "00-00-00-00":
                            kind = "bus_sender" if e["id"].startswith("00-00-B0-") else "unknown"
                            self.senders.add_known(e["id"], kind=kind, key=e["key"], function=e["function"])

    # ------------------------------------------------------- installations
    def _require_sites(self) -> SiteStore:
        if self.sites is None:
            raise ValueError("Anlagenverwaltung ist nicht verfügbar")
        return self.sites

    def load_site(self, site_id: str | None) -> None:
        """Show the stored devices of an installation (without touching the bus)."""
        sites = self._require_sites()
        site = sites.get(site_id)
        devices: dict[int, BusDevice] = {}
        if site:
            for d in site["devices"]:
                with contextlib.suppress(Exception):
                    dev = BusDevice.from_dict(d)
                    devices[dev.address] = dev
        self.devices = devices
        self.last_scan = site["last_scan"] if site else None

    async def detect_site(self) -> dict[str, Any]:
        """Read the connected FAM14's base ID and open (or create) its installation."""
        async with self._session("connect") as t:
            await self._read_fam(t)
        self.connected_id = self.base_id or NO_FAM
        created = False
        if self.sites is not None:
            created = self.connected_id not in self.sites.sites
            self.sites.ensure(self.connected_id)
            self.sites.select(self.connected_id)
            self.load_site(self.connected_id)
        return {"site": self.connected_id, "created": created}

    def select_site(self, site_id: str) -> dict[str, Any]:
        if self.operation:
            raise BusyError(f"Bus ist belegt: {self.operation}")
        self._require_sites().select(site_id)
        self.load_site(site_id)
        return self.state()

    def site_details(self, site_id: str | None = None) -> dict[str, Any]:
        sites = self._require_sites()
        site = sites.get(site_id or sites.active)
        if site is None:
            return {}
        return {
            "id": site["id"], "base_id": site["base_id"], "name": site["name"], "location": site["location"],
            "source": site["source"], "operating_mode": site["operating_mode"],
            "feedback": sites.feedback_ids(site), "device_names": site["device_names"],
            "pending": site["pending"], "pct_entries": site["pct_entries"],
        }

    def import_pct14(self, xml_text: str, name: str | None = None) -> dict[str, Any]:
        """Create or update an installation from a PCT14 XML export."""
        sites = self._require_sites()
        parsed = pct14.parse(xml_text)
        site_id = parsed["base_id"]
        created = site_id not in sites.sites
        site = sites.ensure(site_id, source="pct14")
        has_bus_data = any(d.get("memory") and all(r is not None for r in d["memory"])
                           for d in site["devices"] if not d.get("is_fam"))
        devices, mapped, unmapped = [], [], []
        pct_entries: dict[str, list[dict[str, Any]]] = {}
        for dev in parsed["devices"]:
            memory, ok = pct14.device_memory(dev)
            dt = catalog.identify(bytes.fromhex(dev["model"]), dev["size"])
            label = f"{dt.name if dt.key != 'UNKNOWN' else dev['name']} Adr. {dev['address']}"
            (mapped if ok else unmapped).append(label)
            if not ok and dev["entries"]:
                pct_entries[str(dev["address"])] = dev["entries"]
            devices.append({
                "address": dev["address"], "size": dev["size"], "memory_size": dev["memory_size"],
                "model": dev["model"], "is_fam": False, "memory": memory, "read_at": None, "source": "pct14",
            })
            for addr, ch_name in pct14.channel_names(dev).items():
                site["channels"].setdefault(addr, ch_name)
            if dev["description"]:
                site["device_names"].setdefault(str(dev["address"]), dev["description"])
            if self.senders:
                for e in dev["entries"]:
                    if e["description"] and not (self.senders.senders.get(e["id"]) or {}).get("name"):
                        self.senders.update(e["id"], name=e["description"])
        if not has_bus_data:
            site["devices"] = devices
        site["pct_entries"] = pct_entries
        site["feedback"] = parsed["feedback"]
        site["operating_mode"] = parsed["operating_mode"]
        if name or (not site["name"] and parsed["description"]):
            site["name"] = (name or parsed["description"]).strip()
        sites.persist()
        if sites.active is None:
            sites.active = site_id
        if sites.active == site_id and not has_bus_data:
            self.load_site(site_id)
        self.register_known_senders()
        return {
            "site": site_id, "created": created, "devices": len(devices), "mapped": mapped,
            "unmapped": unmapped, "kept_bus_data": has_bus_data, "feedback": len(parsed["feedback"]),
        }

    def export_project(self) -> dict[str, Any]:
        sites = self._require_sites()
        return {
            "format": PROJECT_FORMAT,
            "version": PROJECT_VERSION,
            "created": _now(),
            "house": dict(sites.house),
            "sites": sites.export_sites(),
            "senders": self.senders.list() if self.senders else [],
        }

    def import_project(self, data: dict[str, Any]) -> dict[str, Any]:
        sites = self._require_sites()
        if data.get("format") != PROJECT_FORMAT:
            raise ValueError("Keine Projektdatei des Bus-Konfigurators")
        created = updated = 0
        for raw in data.get("sites", []):
            _site, is_new = sites.import_site(raw)
            created += is_new
            updated += not is_new
        for key, value in (data.get("house") or {}).items():
            if value and not sites.house.get(key):
                sites.house[key] = value
        senders = 0
        if self.senders:
            for snd in data.get("senders", []):
                sid = snd.get("id")
                if not sid:
                    continue
                cur = self.senders.senders.get(sid)
                if cur is None:
                    self.senders.senders[sid] = snd
                    senders += 1
                elif snd.get("name") and not cur.get("name"):
                    cur["name"] = snd["name"]
                    senders += 1
            if senders:
                self.senders.update(next(iter(self.senders.senders)))  # persist
        if sites.active is None and sites.sites:
            sites.active = next(iter(sites.sites))
        sites.persist()
        self.load_site(sites.active)
        self.register_known_senders()
        return {"created": created, "updated": updated, "senders": senders}

    # -------------------------------------------------------- radio tools
    async def send_radio(self, sender_id: str, action: str, *, eep: str = "A5-38-08", db0: int | None = None) -> dict[str, Any]:
        """Put a radio telegram on the bus (the FAM14 decides whether it is transmitted)."""
        sender = str_to_id(sender_id)
        if action == "teach_in":
            if eep not in TEACH_IN_EEPS:
                raise ValueError(f"Für {eep} kann kein Lerntelegramm erzeugt werden")
            frame = radio_4bs_request(sender, teach_in_4bs_data(eep))
        elif action in ("on", "off"):
            frame = radio_4bs_request(sender, central_switch_data(action == "on"))
        elif action == "rps":
            if db0 is None:
                raise ValueError("Für ein Tastertelegramm fehlt das Datenbyte")
            frame = radio_rps_request(sender, db0)
        else:
            raise ValueError(f"Unbekannte Aktion: {action}")
        async with self._session(f"radio:{action}", lock_bus=False) as t:
            await t.send(frame)
            await asyncio.sleep(0.2)
        raw = frame.serialize().hex(" ")
        _LOGGER.info("Radio telegram %s from %s sent: %s", action, sender_id, raw)
        return {"frame": raw}

    # ---------------------------------------------- Home Assistant senders
    def ha_sender_targets(self, stick_base_id: str | None = None) -> list[dict[str, Any]]:
        """All actuator channels of all installations that can take a Home Assistant sender ID."""
        sites = self._require_sites()
        base = str_to_id(stick_base_id) if stick_base_id else None
        base_int = int.from_bytes(base, "big") if base else None
        out = []
        for site in sites.sites.values():
            pend = site["pending"]
            for d in sorted(site["devices"], key=lambda x: x["address"]):
                if d.get("is_fam"):
                    continue
                dev = None
                with contextlib.suppress(Exception):
                    dev = BusDevice.from_dict(d)
                if dev is None:
                    continue
                dt = dev.device_type
                fn = catalog.SUGGESTED_FUNCTION.get(dt.key, {}).get("bus_sender")
                if fn is None:
                    continue
                groups = catalog.groups_for(dt, dev.memory_size)
                rows: dict[int, bytes | None] = {}
                for g in groups:
                    for r in range(g.start, g.end):
                        p = pend.get(str(dev.address), {}).get(str(r))
                        rows[r] = bytes.fromhex(p) if p else dev.memory[r] if r < len(dev.memory) else None
                known = all(v is not None for v in rows.values())
                if dt.channel_mode == catalog.CH_BITMASK and dev.size > 1:
                    bits = list(range(min(8, dev.size)))
                elif dt.channel_mode == catalog.CH_DALI:
                    bits = list(range(16)) + [16]
                else:
                    bits = [-1]
                for bit in bits:
                    ch_addr = dev.address + (bit if bit >= 0 and bit < 16 else 0)
                    if dt.channel_mode == catalog.CH_DALI and bit < 16 and str(ch_addr) not in site["channels"]:
                        continue  # only named DALI groups (plus broadcast) are offered
                    existing = []
                    for v in rows.values():
                        if not v or not any(v[:4]) or v[5] != fn:
                            continue
                        hit = (v[6] & (1 << bit)) if dt.channel_mode == catalog.CH_BITMASK and dev.size > 1 else \
                            (v[6] == bit) if dt.channel_mode == catalog.CH_DALI else True
                        vid = int.from_bytes(v[:4], "big")
                        if hit and (base_int is None or base_int < vid < base_int + 128 or v[:3] == b"\x00\x00\xb0"):
                            existing.append(id_to_str(v[:4]))
                    default = f"{dt.name} Adr. {dev.address}" + (
                        f" K{bit + 1}" if dt.channel_mode == catalog.CH_BITMASK and dev.size > 1 else
                        (" alle Gruppen" if bit == 16 else f" Gr. {bit}") if dt.channel_mode == catalog.CH_DALI else "")
                    out.append({
                        "site": site["id"], "site_name": site["name"] or site["id"], "address": dev.address,
                        "bit": bit, "device": dt.name, "label": site["channels"].get(str(ch_addr)) or default,
                        "default_label": default, "known": known, "existing": sorted(set(existing)),
                    })
        return out

    def plan_ha_senders(self, stick_base_id: str, targets: list[dict[str, Any]]) -> dict[str, Any]:
        """Give each target channel its own Home Assistant sender ID (stick base ID + n).

        The resulting ID table entries are stored as planned changes of the
        installation; they are written when it is connected ("Auf Geräte schreiben").
        """
        sites = self._require_sites()
        base = str_to_id(stick_base_id)
        if base[3] & 0x7F:
            raise ValueError("Eine Basis-ID endet auf 00 oder 80 (z. B. FF-AA-80-00)")
        sites.house["stick_base_id"] = id_to_str(base)
        used = sites.used_ids()
        next_n = 1
        done, skipped = [], []
        for tgt in targets:
            site = sites.get(tgt["site"])
            dev_data = next((d for d in (site or {}).get("devices", []) if d["address"] == tgt["address"]), None)
            if site is None or dev_data is None:
                skipped.append({**tgt, "reason": "Gerät unbekannt"})
                continue
            dev = BusDevice.from_dict(dev_data)
            dt = dev.device_type
            fn = catalog.SUGGESTED_FUNCTION.get(dt.key, {}).get("bus_sender")
            if fn is None:
                skipped.append({**tgt, "reason": f"{dt.name}: keine Controller-Funktion bekannt"})
                continue
            groups = catalog.groups_for(dt, dev.memory_size)
            group_nr = catalog._GROUP_BY_FUNCTION.get(catalog.family(dt.key) or "", {}).get(fn)
            group = next((g for g in groups if g.number == group_nr), groups[-1] if groups else None)
            if group is None:
                skipped.append({**tgt, "reason": f"{dt.name}: keine ID-Tabelle"})
                continue
            pend = site["pending"].get(str(dev.address), {})
            def value(row: int, _pend=pend, _dev=dev) -> str | None:
                if str(row) in _pend:
                    return _pend[str(row)]
                v = _dev.memory[row] if row < len(_dev.memory) else None
                return v.hex() if v is not None else None
            if any(value(r) is None for r in range(group.start, group.end)):
                skipped.append({**tgt, "reason": "ID-Tabelle nicht bekannt – erst scannen oder PCT14-Export importieren"})
                continue
            bit = int(tgt.get("bit", -1))
            if dt.channel_mode == catalog.CH_BITMASK and dev.size > 1:
                if not 0 <= bit < min(8, dev.size):
                    skipped.append({**tgt, "reason": "Kanal fehlt"})
                    continue
                ch = 1 << bit
            elif dt.channel_mode == catalog.CH_DALI:
                ch = bit if 0 <= bit <= 16 else 16
            else:
                ch = 1
            free = next((r for r in range(group.start, group.end) if not any(bytes.fromhex(value(r))[:4])), None)
            if free is None:
                skipped.append({**tgt, "reason": f"{group.label} ist voll"})
                continue
            while next_n < 128 and id_to_str(id_add(base, next_n)) in used:
                next_n += 1
            if next_n >= 128:
                skipped.append({**tgt, "reason": "Alle 127 Sender-IDs des Sticks sind vergeben"})
                continue
            sid_bytes = id_add(base, next_n)
            sid = id_to_str(sid_bytes)
            used.add(sid)
            row_hex = (sid_bytes + bytes((0, fn, ch, 0))).hex()
            sites.merge_pending(site["id"], dev.address, {free: row_hex})
            ch_addr = dev.address + (bit if dt.channel_mode == catalog.CH_BITMASK and dev.size > 1 else
                                     bit if dt.channel_mode == catalog.CH_DALI and 0 <= bit < 16 else 0)
            label = site["channels"].get(str(ch_addr)) or f"{dt.name} Adr. {ch_addr}"
            if self.senders:
                self.senders.update(sid, name=f"HA: {label}", sender_type="controller")
            done.append({**tgt, "sender_id": sid, "row": free, "function": fn, "value": row_hex, "label": label})
        sites.persist()
        return {"assigned": done, "skipped": skipped}

    # --------------------------------------------------------------- backups
    def _backup_payload(self, devices: list[BusDevice], *, name: str, kind: str) -> dict[str, Any]:
        return {
            "format": BACKUP_FORMAT,
            "version": BACKUP_VERSION,
            "created": _now(),
            "name": name,
            "kind": kind,
            "base_id": self.base_id,
            "devices": [
                {k: v for k, v in d.as_dict().items() if k != "type"} | {"type_key": d.device_type.key}
                for d in devices
            ],
        }

    async def create_backup(self, name: str | None = None) -> dict[str, Any]:
        await self.scan(read_memory=True)
        devices = [d for a, d in sorted(self.devices.items()) if a != FAM_ADDRESS]
        payload = self._backup_payload(devices, name=name or f"Sicherung {datetime.now():%d.%m.%Y %H:%M}",
                                       kind="manual")
        backup_id = await self.backups.save(payload)
        return {"id": backup_id, "devices": len(devices)}

    async def import_backup(self, data: dict[str, Any], name: str | None = None) -> str:
        validate_backup(data)
        data = dict(data)
        data["kind"] = "import"
        if name:
            data["name"] = name
        return await self.backups.save(data, prefix="import")

    def diff_backup(self, data: dict[str, Any], addresses: list[int] | None = None) -> list[dict[str, Any]]:
        """Compare a backup with the cached device memory."""
        result = []
        for bdev in validate_backup(data):
            if addresses is not None and bdev.address not in addresses:
                continue
            cur = self.devices.get(bdev.address)
            entry: dict[str, Any] = {
                "address": bdev.address,
                "type": bdev.device_type.name,
                "status": "ok",
                "rows": [],
            }
            if cur is None:
                entry["status"] = "missing"
            elif cur.model[:2] != bdev.model[:2] or cur.memory_size != bdev.memory_size or cur.size != bdev.size:
                entry["status"] = "type_mismatch"
                entry["current_type"] = cur.device_type.name
            elif any(r is None for r in cur.memory):
                entry["status"] = "not_read"
            else:
                for row, (old, new) in enumerate(zip(cur.memory, bdev.memory, strict=True)):
                    if new is not None and old != new:
                        entry["rows"].append({"row": row, "current": old.hex() if old else None, "backup": new.hex()})
                if not entry["rows"]:
                    entry["status"] = "identical"
            result.append(entry)
        return result

    async def restore_backup(self, backup_id: str, addresses: list[int]) -> list[dict[str, Any]]:
        data = await self.backups.get(backup_id)
        # refresh current memory so the diff is based on reality
        await self.scan(read_memory=True)
        results = []
        for entry in self.diff_backup(data, addresses):
            if entry["status"] != "ok":
                results.append({"address": entry["address"], "status": entry["status"], "written_rows": []})
                continue
            rows = {r["row"]: r["backup"] for r in entry["rows"]}
            res = await self.write_rows(entry["address"], rows)
            results.append({"address": entry["address"], "status": "restored", "written_rows": res["written_rows"]})
        return results

    # ----------------------------------------------------------------- state
    def state(self) -> dict[str, Any]:
        site = self.sites.current if self.sites is not None else None
        return {
            "operation": self.operation,
            "last_error": self.last_error,
            "last_scan": site["last_scan"] if site else self.last_scan,
            "base_id": site["base_id"] if site else self.base_id,
            "connected_base_id": self.base_id,
            "active_site": self.active_site_id,
            "connected_site": self.connected_id,
            "site_name": (site or {}).get("name") or "",
            "bridge": bool(self.bridge and self.bridge.attached),
            "fam_ack": self.bus_locked_by_fam,
            "echo": self.echo,
            "device_count": len([a for a in self.devices if a != FAM_ADDRESS]),
        }

    def export_cache(self) -> dict[str, Any]:
        return {
            "devices": [d.as_dict() | {"type": None} for d in self.devices.values()],
            "base_id": self.base_id,
            "last_scan": self.last_scan,
        }

    def import_cache(self, data: dict[str, Any] | None) -> None:
        if not data:
            return
        with contextlib.suppress(Exception):
            self.devices = {int(d["address"]): BusDevice.from_dict(d) for d in data.get("devices", [])}
            self.base_id = data.get("base_id")
            self.last_scan = data.get("last_scan")
