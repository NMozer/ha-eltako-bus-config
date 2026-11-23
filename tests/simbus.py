"""A simulated Eltako Series 14 bus (FAM14 + actuators) for tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from custom_components.eltako_bus_config.protocol import (
    HSEQ_RMT,
    HSEQ_RRT,
    ORG_DISCOVERY,
    ORG_IDENTIFY,
    ORG_LOCK,
    ORG_MEM_READ,
    ORG_MEM_SELECT,
    ORG_MEM_WRITE,
    Frame,
    FrameReader,
)


@dataclass
class SimDevice:
    address: int
    size: int
    model: bytes
    memory: list[bytes] = field(default_factory=lambda: [bytes(8)] * 128)
    classifier: int = 0x08

    @property
    def memory_size(self) -> int:
        return len(self.memory)


class SimBus:
    def __init__(self, *, echo: bool = True, fam: bool = True, drop_writes: bool = False) -> None:
        self.echo = echo
        self.fam = fam
        self.drop_writes = drop_writes
        self.devices: dict[int, SimDevice] = {}
        self.fam_device = SimDevice(255, 1, b"\x07\xff\x22\x00", [bytes(8)] * 8, classifier=0x00)
        self.fam_device.memory[1] = bytes.fromhex("ff a1 b2 80 00 00 00 00".replace(" ", ""))
        self.locked = False
        self.selected: int | None = None
        self.identified: list[int] = []
        self.requests: list[Frame] = []
        self.reader: asyncio.StreamReader | None = None
        self._frames = FrameReader()

    def add(self, dev: SimDevice) -> SimDevice:
        self.devices[dev.address] = dev
        return dev

    # ---- stream plumbing
    async def connect(self):
        self.reader = asyncio.StreamReader()
        return self.reader, _Writer(self)

    def _reply(self, frame: Frame) -> None:
        assert self.reader
        self.reader.feed_data(frame.serialize())

    def inject_radio(self, org: int, data: bytes, sender: bytes, status: int = 0x30) -> None:
        payload = data + bytes(4 - len(data)) if org == 0x07 else data[:1] + b"\x00\x00\x00"
        self._reply(Frame(HSEQ_RRT, org, payload + sender, status))

    def _discovery_reply(self, dev: SimDevice) -> Frame:
        return Frame(
            HSEQ_RMT,
            ORG_DISCOVERY,
            bytes((dev.address, dev.size, dev.memory_size, dev.classifier)) + dev.model,
            0,
        )

    def _device(self, address: int) -> SimDevice | None:
        if address == 255 and self.fam:
            return self.fam_device
        return self.devices.get(address)

    def handle(self, data: bytes) -> None:
        if self.echo:
            assert self.reader
            self.reader.feed_data(data)
        for f in self._frames.feed(data):
            self.requests.append(f)
            if not f.is_request:
                continue
            if f.org == ORG_LOCK:
                self.locked = f.address == 0xFF
                if self.fam:
                    self._reply(self._discovery_reply(self.fam_device))
            elif f.org == ORG_DISCOVERY:
                dev = self._device(f.address)
                if dev:
                    self._reply(self._discovery_reply(dev))
            elif f.org == ORG_MEM_READ:
                dev = self._device(f.address)
                row = f.data[7]
                if dev and row < dev.memory_size:
                    self._reply(Frame(HSEQ_RMT, ORG_MEM_READ, dev.memory[row], row))
            elif f.org == ORG_MEM_SELECT:
                if self._device(f.address):
                    self.selected = f.address
                    self._reply(Frame(HSEQ_RMT, ORG_MEM_SELECT, bytes(8), f.address))
            elif f.org == ORG_MEM_WRITE:
                dev = self._device(self.selected) if self.selected is not None else None
                if dev:
                    if not self.drop_writes:
                        mem = list(dev.memory)
                        mem[f.address] = f.data
                        dev.memory = mem
                    self._reply(Frame(HSEQ_RMT, ORG_MEM_WRITE, bytes(8), f.address))
            elif f.org == ORG_IDENTIFY:
                self.identified.append(f.address)


class _Writer:
    def __init__(self, bus: SimBus) -> None:
        self.bus = bus
        self.closed = False

    def write(self, data: bytes) -> None:
        # deliver asynchronously like a real UART would
        asyncio.get_running_loop().call_soon(self.bus.handle, bytes(data))

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None
