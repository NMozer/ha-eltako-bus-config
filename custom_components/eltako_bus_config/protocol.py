"""ESP2 / Eltako Series 14 bus protocol primitives.

Pure functions without I/O so they can be unit tested. The telegram layout
follows the reverse engineering work of the eltako14bus library
(Christian Amsüss / Energy Harvesting Solutions, LGPL-3.0) and the ESP2
specification:

    A5 5A | HSEQ/LEN | ORG | DATA(8) | ADDR | CHECKSUM

Every frame is exactly 14 bytes. HSEQ is in the upper three bits of byte 2,
LEN (always 11) in the lower five bits. Eltako bus control telegrams use
HSEQ 5 (TCT, request) and HSEQ 4 (RMT, response).
"""

from __future__ import annotations

from dataclasses import dataclass

SYNC = b"\xa5\x5a"
FRAME_LEN = 14

HSEQ_RRT = 0  # received radio telegram
HSEQ_TRT = 3  # transmit radio telegram
HSEQ_RMT = 4  # receive message telegram (bus response)
HSEQ_TCT = 5  # transmit control telegram (bus request)

ORG_RPS = 0x05
ORG_1BS = 0x06
ORG_4BS = 0x07
ORG_DISCOVERY = 0xF0
ORG_MEM_READ = 0xF1
ORG_MEM_SELECT = 0xF2
ORG_MEM_WRITE = 0xF4
ORG_TIMEOUT = 0xF8
ORG_POLL = 0xFC
ORG_IDENTIFY = 0xFD
ORG_POLL_FORCED = 0xFE
ORG_LOCK = 0xFF

FAM_ADDRESS = 255
ZERO8 = b"\x00" * 8


class FrameError(ValueError):
    """Raised for malformed frames."""


@dataclass(frozen=True)
class Frame:
    """A parsed 14 byte ESP2 frame."""

    hseq: int
    org: int
    data: bytes  # 8 bytes
    address: int  # last body byte (bus address / row / status)

    @property
    def body(self) -> bytes:
        return bytes(((self.hseq << 5) | 11, self.org, *self.data, self.address))

    def serialize(self) -> bytes:
        body = self.body
        return SYNC + body + bytes((sum(body) & 0xFF,))

    @property
    def is_request(self) -> bool:
        return self.hseq == HSEQ_TCT

    @property
    def is_response(self) -> bool:
        return self.hseq == HSEQ_RMT

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<Frame hseq={self.hseq} org={self.org:02x} "
            f"data={self.data.hex(' ')} addr={self.address:02x}>"
        )


def parse_frame(raw: bytes) -> Frame:
    if len(raw) != FRAME_LEN:
        raise FrameError("invalid length")
    if raw[:2] != SYNC:
        raise FrameError("no sync bytes")
    body = raw[2:13]
    if sum(body) & 0xFF != raw[13]:
        raise FrameError("checksum mismatch")
    if body[0] & 0x1F != 11:
        raise FrameError("unexpected length field")
    return Frame(hseq=body[0] >> 5, org=body[1], data=bytes(body[2:10]), address=body[10])


class FrameReader:
    """Incremental frame synchroniser for a byte stream."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self.dropped_bytes = 0

    def feed(self, data: bytes) -> list[Frame]:
        self._buf.extend(data)
        frames: list[Frame] = []
        while True:
            idx = self._buf.find(SYNC)
            if idx < 0:
                # keep a trailing 0xA5 which might be the start of a sync
                keep = 1 if self._buf[-1:] == b"\xa5" else 0
                self.dropped_bytes += len(self._buf) - keep
                del self._buf[: len(self._buf) - keep]
                break
            if idx:
                self.dropped_bytes += idx
                del self._buf[:idx]
            if len(self._buf) < FRAME_LEN:
                break
            raw = bytes(self._buf[:FRAME_LEN])
            try:
                frames.append(parse_frame(raw))
            except FrameError:
                # resync one byte further
                self.dropped_bytes += 1
                del self._buf[:1]
                continue
            del self._buf[:FRAME_LEN]
        return frames


# --------------------------------------------------------------------------
# Request builders
# --------------------------------------------------------------------------

def control(org: int, address: int, data: bytes = ZERO8) -> Frame:
    return Frame(HSEQ_TCT, org, bytes(data), address)


def bus_lock() -> Frame:
    return control(ORG_LOCK, 0xFF)


def bus_unlock() -> Frame:
    return control(ORG_LOCK, 0x00)


def discovery_request(address: int) -> Frame:
    return control(ORG_DISCOVERY, address)


def memory_read_request(address: int, row: int) -> Frame:
    return control(ORG_MEM_READ, address, bytes(7) + bytes((row,)))


def memory_select_request(address: int) -> Frame:
    return control(ORG_MEM_SELECT, address)


def memory_write_request(row: int, value: bytes) -> Frame:
    if len(value) != 8:
        raise ValueError("memory rows are exactly 8 bytes")
    # Note: for F4 the address byte carries the row, data the row content
    return control(ORG_MEM_WRITE, row, value)


def identify_request(address: int) -> Frame:
    return control(ORG_IDENTIFY, address)


# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DiscoveryReply:
    address: int
    size: int
    memory_size: int
    model: bytes  # 4 bytes, [0:2] type id, [2:4] version nibbles
    is_fam: bool

    @property
    def version(self) -> str:
        hi, lo = self.model[2], self.model[3]
        return f"{hi >> 4}.{hi & 0xF}.{lo >> 4}.{lo & 0xF}"


def parse_discovery_reply(frame: Frame) -> DiscoveryReply | None:
    if frame.org != ORG_DISCOVERY or not frame.is_response or frame.address != 0:
        return None
    classifier = frame.data[3]
    double_size = False
    if classifier == 0x00:
        is_fam = True
    elif classifier in (0x08, 0x0C):
        is_fam = False
    elif classifier == 0x0E:  # seen on FDG14: announces half its bus size
        is_fam = False
        double_size = True
    else:
        return None
    size = frame.data[1] * (2 if double_size else 1)
    return DiscoveryReply(
        address=frame.data[0],
        size=size,
        memory_size=frame.data[2],
        model=bytes(frame.data[4:8]),
        is_fam=is_fam,
    )


def is_memory_response(frame: Frame, row: int) -> bool:
    return frame.org == ORG_MEM_READ and frame.is_response and frame.address == row


def is_org_response(frame: Frame, org: int) -> bool:
    return frame.org == org and frame.is_response


def is_timeout(frame: Frame) -> bool:
    return frame.org == ORG_TIMEOUT and frame.is_response


@dataclass(frozen=True)
class RadioTelegram:
    """A sensor telegram as seen on the bus (RPS / 1BS / 4BS)."""

    sender: bytes
    org: int
    data: bytes
    status: int

    @property
    def kind(self) -> str:
        return {ORG_RPS: "RPS", ORG_1BS: "1BS", ORG_4BS: "4BS"}.get(self.org, "?")

    @property
    def is_teach_in(self) -> bool:
        # 4BS teach-in: LRN bit (DB0.3) cleared; 1BS: DB0.3 cleared
        if self.org == ORG_4BS:
            return not (self.data[3] & 0x08)
        if self.org == ORG_1BS:
            return not (self.data[0] & 0x08)
        return False

    @property
    def rocker(self) -> tuple[int, str] | None:
        """For RPS rocker switches (F6-02-xx): (memory key byte, direction).

        Status bit NU (0x10) set means "N-message": DB0 bits 7..5 carry the
        rocker action (0 = AI, 1 = AO, 2 = BI, 3 = BO; O = top) and bit 4 = pressed.
        Rocker A is stored as key 5 (left), rocker B as key 6 (right).
        Releases (U-messages) and multi-button presses return None.
        """
        if self.org != ORG_RPS or not (self.status & 0x10) or not (self.data[0] & 0x10):
            return None
        action = self.data[0] >> 5
        if action > 3:
            return None
        key = 5 if action in (0, 1) else 6
        # Eltako convention: 0x30 = left top, 0x10 = left bottom, 0x70 = right top, 0x50 = right bottom
        direction = "oben" if action in (1, 3) else "unten"
        return key, direction

    @property
    def button(self) -> int | None:
        """Single button as stored in an ID table key byte (PCT14 'Einzeltaste').

        Verified on hardware (FSB14, universal push button): left top = 1, right top = 3.
        Left bottom = 2 and right bottom = 4 follow the same numbering.
        """
        rocker = self.rocker
        if rocker is None:
            return None
        key, direction = rocker
        return (1 if key == 5 else 3) + (0 if direction == "oben" else 1)

    @property
    def window_handle(self) -> bool:
        """F6-10-00 window handle: T21 set, NU cleared, typical values C0/E0/F0/D0."""
        return self.org == ORG_RPS and not (self.status & 0x10) and self.data[0] in (0xC0, 0xD0, 0xE0, 0xF0)

    @property
    def eep(self) -> str | None:
        """EEP announced in a 4BS teach-in telegram with EEP information (LRN type bit DB0.7)."""
        if self.org == ORG_4BS and self.is_teach_in and self.data[3] & 0x80:
            func = self.data[0] >> 2
            typ = ((self.data[0] & 0x03) << 5) | (self.data[1] >> 3)
            return f"A5-{func:02X}-{typ:02X}"
        if self.org == ORG_1BS:
            return "D5-00-01"
        return None


def parse_radio(frame: Frame) -> RadioTelegram | None:
    """Parse an incoming radio telegram (RRT / wrapped bus telegrams).

    Layout of data for radio telegrams: DB3 DB2 DB1 DB0 ID3 ID2 ID1 ID0,
    and the trailing body byte is the status byte.
    """
    if frame.org not in (ORG_RPS, ORG_1BS, ORG_4BS):
        return None
    if frame.hseq not in (HSEQ_RRT, HSEQ_TRT, HSEQ_RMT):
        return None
    sender = bytes(frame.data[4:8])
    if frame.org == ORG_4BS:
        data = bytes(frame.data[0:4])
    else:
        data = bytes(frame.data[0:1])
    return RadioTelegram(sender=sender, org=frame.org, data=data, status=frame.address)


# --------------------------------------------------------------------------
# Outgoing radio telegrams (sent on the bus with HSEQ TRT; the FAM14 decides
# whether it transmits them over the air)
# --------------------------------------------------------------------------

MANUFACTURER_ELTAKO = 0x00D

# EEPs for which a teach-in telegram can be generated: EEP -> (FUNC, TYPE)
TEACH_IN_EEPS: dict[str, tuple[int, int]] = {
    "A5-38-08": (0x38, 0x08),  # central command (switching / dimming / blinds commands)
    "A5-3F-7F": (0x3F, 0x7F),  # universal (Eltako blinds actuators)
}


def teach_in_4bs_data(eep: str, manufacturer: int = MANUFACTURER_ELTAKO) -> bytes:
    """DB3..DB0 of a 4BS teach-in telegram with EEP information (LRN type 1, LRN bit 0)."""
    func, typ = TEACH_IN_EEPS[eep]
    return bytes((
        (func << 2) | (typ >> 5),
        ((typ & 0x1F) << 3) | ((manufacturer >> 8) & 0x07),
        manufacturer & 0xFF,
        0x80,
    ))


def central_switch_data(on: bool) -> bytes:
    """A5-38-08 command 1 (switching): DB3=1, DB0 = LRN bit set + switching state."""
    return bytes((0x01, 0x00, 0x00, 0x09 if on else 0x08))


def radio_4bs_request(sender: bytes, data: bytes, status: int = 0x00) -> Frame:
    if len(sender) != 4 or len(data) != 4:
        raise ValueError("4BS braucht 4 Datenbytes und eine 4-Byte-Sender-ID")
    return Frame(hseq=HSEQ_TRT, org=ORG_4BS, data=bytes(data) + bytes(sender), address=status & 0xFF)


def radio_rps_request(sender: bytes, db0: int, status: int = 0x30) -> Frame:
    if len(sender) != 4:
        raise ValueError("Sender-ID braucht 4 Byte")
    return Frame(hseq=HSEQ_TRT, org=ORG_RPS, data=bytes((db0 & 0xFF, 0, 0, 0)) + bytes(sender), address=status & 0xFF)


def id_add(base: bytes, offset: int) -> bytes:
    return ((int.from_bytes(base, "big") + offset) & 0xFFFFFFFF).to_bytes(4, "big")


def id_to_str(b: bytes) -> str:
    return "-".join(f"{x:02X}" for x in b)


def str_to_id(s: str) -> bytes:
    cleaned = s.replace("-", "").replace(":", "").replace(" ", "")
    if len(cleaned) != 8:
        raise ValueError(f"Ungültige ID: {s!r}")
    return bytes.fromhex(cleaned)
