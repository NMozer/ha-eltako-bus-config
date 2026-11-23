"""Asynchronous serial transport for the Eltako RS485 bus."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
import contextlib
import logging
import time

from .protocol import Frame, FrameReader, is_timeout

_LOGGER = logging.getLogger(__name__)

ECHO_PROBE = b"\xff\x00\xff" * 5  # cannot be part of a valid ESP2 frame

Connector = Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]
Listener = Callable[[Frame], None]


class TransportError(Exception):
    """Raised when the serial connection is not usable."""


def serial_connector(port: str, baudrate: int) -> Connector:
    async def _connect():
        import serial_asyncio_fast  # imported lazily: only needed on real hardware

        return await serial_asyncio_fast.open_serial_connection(url=port, baudrate=baudrate)

    return _connect


class BusTransport:
    """Frame oriented request/response access to the bus.

    Only one exchange can run at a time. All received frames are also handed
    to registered listeners (used for the "capture sender" function).
    """

    def __init__(self, connector: Connector, *, send_delay: float = 0.01, echo_test: bool = True) -> None:
        self._connector = connector
        self._send_delay = send_delay
        self._echo_test_enabled = echo_test
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._rx_task: asyncio.Task | None = None
        self._frames = FrameReader()
        self._queue: asyncio.Queue[Frame] = asyncio.Queue()
        self._exchange_lock = asyncio.Lock()
        self._listeners: list[Listener] = []
        self._pending_echo: deque[tuple[float, bytes]] = deque()
        self.suppress_echo = False
        self.frames_received = 0
        self.frames_sent = 0

    # ------------------------------------------------------------------ setup
    @property
    def is_open(self) -> bool:
        return self._writer is not None

    async def open(self) -> None:
        if self.is_open:
            return
        try:
            self._reader, self._writer = await self._connector()
        except Exception as err:  # serial exceptions are not a common base class
            raise TransportError(f"Serielle Schnittstelle kann nicht geöffnet werden: {err}") from err
        if self._echo_test_enabled:
            self.suppress_echo = await self._detect_echo()
            _LOGGER.debug("Echo detection: %s", self.suppress_echo)
        self._rx_task = asyncio.create_task(self._rx_loop(), name="eltako_bus_config_rx")

    async def close(self) -> None:
        if self._rx_task:
            self._rx_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._rx_task
            self._rx_task = None
        if self._writer:
            with contextlib.suppress(Exception):
                self._writer.close()
                await self._writer.wait_closed()
        self._reader = self._writer = None

    async def _detect_echo(self) -> bool:
        assert self._reader and self._writer
        self._writer.write(ECHO_PROBE)
        await self._writer.drain()
        buf = b""
        deadline = time.monotonic() + 0.4
        while time.monotonic() < deadline:
            try:
                chunk = await asyncio.wait_for(self._reader.read(256), timeout=max(0.01, deadline - time.monotonic()))
            except TimeoutError:
                break
            if not chunk:
                break
            buf += chunk
            if ECHO_PROBE in buf:
                rest = buf.split(ECHO_PROBE, 1)[1]
                self._feed(rest)
                return True
        self._feed(buf)
        _LOGGER.debug("Echo probe: received %d bytes, no echo", len(buf))
        return False

    # -------------------------------------------------------------- receiving
    def add_listener(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def _remove() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(listener)

        return _remove

    async def _rx_loop(self) -> None:
        assert self._reader
        while True:
            chunk = await self._reader.read(256)
            if not chunk:
                _LOGGER.warning("Serial connection closed by peer")
                self._writer = None
                return
            self._feed(chunk)

    def _feed(self, chunk: bytes) -> None:
        for frame in self._frames.feed(chunk):
            if self._is_echo(frame):
                continue
            self.frames_received += 1
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("RX %s", frame.serialize().hex(" "))
            self._queue.put_nowait(frame)
            for listener in list(self._listeners):
                try:
                    listener(frame)
                except Exception:  # pragma: no cover - defensive
                    _LOGGER.exception("Listener failed")

    def _is_echo(self, frame: Frame) -> bool:
        if not frame.is_request:
            return False  # devices only answer with responses; requests seen on RX are our own echo
        now = time.monotonic()
        while self._pending_echo and self._pending_echo[0][0] < now - 2:
            self._pending_echo.popleft()
        raw = frame.serialize()
        for i, (_, sent) in enumerate(self._pending_echo):
            if sent == raw:
                for _ in range(i + 1):
                    self._pending_echo.popleft()
                return True
        return False

    # ---------------------------------------------------------------- sending
    async def send(self, frame: Frame) -> None:
        if not self._writer:
            raise TransportError("Keine Verbindung zum Bus")
        raw = frame.serialize()
        self._pending_echo.append((time.monotonic(), raw))
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("TX %s", raw.hex(" "))
        self._writer.write(raw)
        await self._writer.drain()
        self.frames_sent += 1
        if self._send_delay:
            await asyncio.sleep(self._send_delay)

    async def exchange(
        self,
        frame: Frame,
        match: Callable[[Frame], bool],
        *,
        timeout: float = 1.0,
        retries: int = 3,
    ) -> Frame | None:
        """Send ``frame`` and wait for a frame satisfying ``match``.

        Returns None if no matching answer arrived after all retries. A bus
        timeout telegram (ORG F8) counts as a failed attempt.
        """
        async with self._exchange_lock:
            for _attempt in range(max(1, retries)):
                while not self._queue.empty():
                    self._queue.get_nowait()
                await self.send(frame)
                deadline = time.monotonic() + timeout
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        answer = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                    except TimeoutError:
                        break
                    if match(answer):
                        return answer
                    if is_timeout(answer):
                        break
            _LOGGER.debug("No matching answer for %s after %d attempt(s)", frame.serialize().hex(" "), max(1, retries))
            return None
