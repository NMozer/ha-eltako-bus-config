"""Laptop bridge: a browser with Web Serial relays the FAM14's USB port.

The panel opens the FAM14 (Mini-USB) on the computer it runs on and passes
every received chunk to Home Assistant; bytes the integration sends travel
back to the browser as subscription events. For the bus logic this is just
another serial connection, so scan, write with verification, backups and
listening work unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging

_LOGGER = logging.getLogger(__name__)

Sender = Callable[[bytes], None]


class BridgeHub:
    """Holds the one browser currently attached as serial port."""

    def __init__(self) -> None:
        self._send: Sender | None = None
        self._on_replaced: Callable[[], None] | None = None
        self._reader: asyncio.StreamReader | None = None
        self.label: str | None = None
        self.bytes_in = 0
        self.bytes_out = 0

    @property
    def attached(self) -> bool:
        return self._send is not None

    def attach(self, send: Sender, on_replaced: Callable[[], None], label: str | None = None) -> Callable[[], None]:
        if self._on_replaced is not None:
            try:
                self._on_replaced()
            except Exception:  # pragma: no cover - the old connection may already be gone
                _LOGGER.debug("Could not notify replaced bridge", exc_info=True)
        self._send, self._on_replaced, self.label = send, on_replaced, label
        self.bytes_in = self.bytes_out = 0
        _LOGGER.info("Laptop bridge attached (%s)", label or "browser")
        token = send

        def detach() -> None:
            if self._send is token:
                self._send = self._on_replaced = None
                self.label = None
                if self._reader is not None:
                    self._reader.feed_eof()
                    self._reader = None
                _LOGGER.info("Laptop bridge detached")

        return detach

    def feed(self, data: bytes) -> None:
        self.bytes_in += len(data)
        if self._reader is not None:
            self._reader.feed_data(data)

    async def connect(self) -> tuple[asyncio.StreamReader, _BridgeWriter]:
        """Connector for BusTransport."""
        if self._send is None:
            raise ConnectionError("Keine Laptop-Brücke verbunden")
        self._reader = asyncio.StreamReader()
        return self._reader, _BridgeWriter(self)

    def _write(self, data: bytes) -> None:
        if self._send is None:
            raise ConnectionError("Laptop-Brücke wurde getrennt")
        self.bytes_out += len(data)
        self._send(data)


class _BridgeWriter:
    def __init__(self, hub: BridgeHub) -> None:
        self._hub = hub

    def write(self, data: bytes) -> None:
        self._hub._write(bytes(data))

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        if self._hub._reader is not None:
            self._hub._reader = None

    async def wait_closed(self) -> None:
        return None
