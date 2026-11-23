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

from . import catalog
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
    parse_discovery_reply,
    parse_radio,
)
from .senders import SenderStore
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
        self._stop_listen: asyncio.Event | None = None

    # ------------------------------------------------------------- utilities
    def _emit(self, **event: Any) -> None:
        event.setdefault("operation", self.operation)
        try:
            self._progress(event)
        except Exception:  # pragma: no cover
            _LOGGER.exception("progress callback failed")

    async def _changed(self) -> None:
        self.register_known_senders()
        if self._on_devices_changed:
            await self._on_devices_changed()

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
        await self._changed()
        return [d.as_dict() for _, d in sorted(self.devices.items())]

    async def read_device(self, address: int) -> dict[str, Any]:
        async with self._session(f"read:{address}") as t:
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

    def register_known_senders(self) -> None:
        """Make all IDs found in device ID tables known to the sender store."""
        if not self.senders:
            return
        for dev in self.devices.values():
            for g in catalog.groups_for(dev.device_type, dev.memory_size):
                for row in range(g.start, g.end):
                    val = dev.memory[row] if row < len(dev.memory) else None
                    if not val or not any(val[:4]):
                        continue
                    sid = id_to_str(val[:4])
                    kind = "bus_sender" if val[:3] == b"\x00\x00\xb0" else "unknown"
                    self.senders.add_known(sid, kind=kind, key=val[4], function=val[5])

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
        return {
            "operation": self.operation,
            "last_error": self.last_error,
            "last_scan": self.last_scan,
            "base_id": self.base_id,
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
