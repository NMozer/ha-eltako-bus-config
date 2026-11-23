"""Tests for protocol, transport and manager against a simulated bus."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from custom_components.eltako_bus_config import catalog
from custom_components.eltako_bus_config.manager import BackupStore, BusError, BusManager, BusyError
from custom_components.eltako_bus_config.protocol import (
    FrameReader,
    discovery_request,
    parse_frame,
    str_to_id,
)
from custom_components.eltako_bus_config.transport import BusTransport

from .simbus import SimBus, SimDevice

def test_frames_match_reference_library():
    """Byte-for-byte compatibility with eltako14bus (reverse engineered reference)."""
    em = pytest.importorskip("eltakobus.message")
    from custom_components.eltako_bus_config import protocol as p

    assert p.discovery_request(5).serialize() == em.EltakoDiscoveryRequest(5).serialize()
    assert p.memory_read_request(5, 12).serialize() == em.EltakoMemoryRequest(5, 12).serialize()
    assert p.bus_lock().serialize() == em.EltakoBusLock().serialize()
    assert p.bus_unlock().serialize() == em.EltakoBusUnlock().serialize()
    assert p.memory_select_request(9).serialize() == em.EltakoMessage(0xF2, 9).serialize()
    row = bytes(range(8))
    assert p.memory_write_request(17, row).serialize() == em.EltakoMessage(0xF4, 17, row).serialize()
    reply = em.EltakoDiscoveryReply(12, 4, 128, b"\x04\x01\x31\x00", False).serialize()
    parsed = p.parse_discovery_reply(p.parse_frame(reply))
    assert (parsed.address, parsed.size, parsed.memory_size, parsed.model, parsed.is_fam) == (
        12, 4, 128, b"\x04\x01\x31\x00", False)
    mem = em.EltakoMemoryResponse(33, row).serialize()
    assert p.is_memory_response(p.parse_frame(mem), 33) and p.parse_frame(mem).data == row
    rps = em.RPSMessage(b"\xfe\xd4\xe9\x47", 0x30, b"\x70").serialize()
    tel = p.parse_radio(p.parse_frame(rps))
    assert tel.sender == b"\xfe\xd4\xe9\x47" and tel.data == b"\x70" and tel.kind == "RPS"


def test_frame_reader_resyncs_after_garbage():
    good = discovery_request(7).serialize()
    reader = FrameReader()
    frames = reader.feed(b"\x00\xa5\x12" + good[:5])
    assert frames == []
    frames = reader.feed(good[5:] + b"\xa5\x5a\x00" + good)
    assert [f.address for f in frames] == [7, 7]
    assert parse_frame(good).org == 0xF0


def test_catalog_identifies_by_size():
    assert catalog.identify(b"\x04\x01\x11\x00", 4).key == "FSR14_4x"
    assert catalog.identify(b"\x04\x01\x11\x00", 1).key == "FSR14_1x"
    assert catalog.identify(b"\x04\x18\x11\x00", 4).key == "F4HK14"
    assert catalog.identify(b"\x99\x99\x00\x00", 1).key == "UNKNOWN"


def _setup(tmp_path: Path, **kw) -> tuple[SimBus, BusManager]:
    sim = SimBus(**kw)
    fsr_mem = [bytes(8)] * 128
    fsr_mem[12] = str_to_id("FE-D4-E9-47") + bytes((5, 3, 0b0001, 0))
    sim.add(SimDevice(1, 4, b"\x04\x01\x31\x00", fsr_mem))
    sim.add(SimDevice(5, 2, b"\x04\x06\x31\x00"))
    sim.add(SimDevice(7, 1, b"\x04\x04\x42\x00"))

    async def run(func, *args):
        return await asyncio.to_thread(func, *args)

    manager = BusManager(
        lambda: BusTransport(sim.connect, send_delay=0),
        BackupStore(tmp_path / "backups", run),
        scan_timeout=0.01,
        scan_retries=1,
    )
    return sim, manager


async def test_scan_reads_devices_and_memory(tmp_path):
    sim, manager = _setup(tmp_path)
    devices = await manager.scan(read_memory=True)
    by_addr = {d["address"]: d for d in devices}
    assert set(by_addr) == {1, 5, 7, 255}
    assert by_addr[1]["type"]["key"] == "FSR14_4x"
    assert by_addr[5]["type"]["key"] == "FSB14"
    assert by_addr[7]["type"]["key"] == "FUD14"
    assert by_addr[1]["memory"][12] == "fed4e94705030100"
    assert manager.base_id == "FF-A1-B2-80"
    assert manager.bus_locked_by_fam is True
    assert manager.echo is True
    assert sim.locked is False  # unlocked again afterwards
    # addresses 2-4 belong to the 4 channel FSR14 and must be skipped
    probed = {f.address for f in sim.requests if f.org == 0xF0}
    assert not probed & {2, 3, 4, 6}


async def test_scan_without_echo_and_without_fam(tmp_path):
    sim, manager = _setup(tmp_path, echo=False, fam=False)
    devices = await manager.scan(read_memory=False)
    assert {d["address"] for d in devices} == {1, 5, 7}
    assert manager.bus_locked_by_fam is False
    assert manager.echo is False


async def test_write_rows_verifies_and_backs_up(tmp_path):
    sim, manager = _setup(tmp_path)
    await manager.scan()
    new_row = "00 00 10 07 00 33 01 00"
    res = await manager.write_rows(1, {13: new_row, 12: "fed4e94705030100"})
    assert res["written_rows"] == [13]  # row 12 unchanged -> not written
    assert sim.devices[1].memory[13] == bytes.fromhex("0000100700330100")
    backups = await manager.backups.list()
    assert len(backups) == 1 and backups[0]["kind"] == "auto"
    auto = await manager.backups.get(backups[0]["id"])
    assert auto["devices"][0]["memory"][13] == "0000000000000000"


async def test_write_detects_failed_verification(tmp_path):
    sim, manager = _setup(tmp_path, drop_writes=True)
    await manager.scan()
    with pytest.raises(BusError, match="Verifikation"):
        await manager.write_rows(5, {20: "0102030405060708"})


async def test_write_rejects_bad_rows(tmp_path):
    _sim, manager = _setup(tmp_path)
    with pytest.raises(ValueError):
        await manager.write_rows(1, {12: "0102"})
    with pytest.raises(ValueError):
        await manager.write_rows(1, {500: "0102030405060708"})


async def test_backup_and_restore_roundtrip(tmp_path):
    sim, manager = _setup(tmp_path)
    created = await manager.create_backup("Test")
    assert created["devices"] == 3
    original = list(sim.devices[1].memory)
    # simulate someone changing the device afterwards
    await manager.write_rows(1, {12: "0000000000000000", 20: "1111111111111111"})
    data = await manager.backups.get(created["id"])
    diff = manager.diff_backup(data, [1])
    assert diff[0]["status"] == "ok" and {r["row"] for r in diff[0]["rows"]} == {12, 20}
    results = await manager.restore_backup(created["id"], [1])
    assert results[0]["status"] == "restored"
    assert sim.devices[1].memory == original


async def test_restore_refuses_type_mismatch(tmp_path):
    sim, manager = _setup(tmp_path)
    created = await manager.create_backup()
    sim.devices[7].model = b"\x04\x07\x10\x00"  # replaced by an FSG14
    results = await manager.restore_backup(created["id"], [7])
    assert results[0]["status"] == "type_mismatch"


async def test_import_rejects_foreign_files(tmp_path):
    _sim, manager = _setup(tmp_path)
    with pytest.raises(ValueError):
        await manager.import_backup({"foo": 1})


async def test_listen_captures_senders(tmp_path):
    sim, manager = _setup(tmp_path)

    async def inject():
        await asyncio.sleep(0.3)
        sim.inject_radio(0x05, b"\x70", bytes.fromhex("fed4e947"))
        sim.inject_radio(0x05, b"\x50", bytes.fromhex("fed4e947"))
        sim.inject_radio(0x07, bytes.fromhex("00000008"), bytes.fromhex("05123456"))
        sim.inject_radio(0x07, bytes.fromhex("10000000"), bytes.fromhex("0000000a"))

    task = asyncio.create_task(inject())
    senders = await manager.listen(1.2)
    await task
    by_id = {s["sender"]: s for s in senders}
    assert by_id["FE-D4-E9-47"]["count"] == 2 and by_id["FE-D4-E9-47"]["kind"] == "RPS"
    assert by_id["05-12-34-56"]["kind"] == "4BS" and not by_id["05-12-34-56"]["teach_in"]
    assert by_id["00-00-00-0A"]["bus_device"] and by_id["00-00-00-0A"]["teach_in"]


async def test_probe_and_identify(tmp_path):
    sim, manager = _setup(tmp_path)
    result = await manager.probe()
    assert result["fam_found"] and result["memory_read_ok"] and result["devices_answering"] == [1]
    await manager.identify(5)
    assert sim.identified == [5]


async def test_concurrent_operations_are_rejected(tmp_path):
    _sim, manager = _setup(tmp_path)
    first = asyncio.create_task(manager.scan())
    await asyncio.sleep(0.01)
    with pytest.raises(BusyError):
        await manager.read_device(1)
    await first


async def test_echo_filtered_even_if_probe_misses_it(tmp_path):
    """Seen on real hardware: FAM14 poll traffic hides the echo probe."""
    sim, manager = _setup(tmp_path, echo=True)
    manager._transport_factory = lambda: BusTransport(sim.connect, send_delay=0, echo_test=False)
    devices = await manager.scan(read_memory=False)
    assert {d["address"] for d in devices} == {1, 5, 7, 255}


def test_groups_follow_memory_size():
    dt = catalog.identify(b"\x04\x06\x52\x00", 2)  # FSB14 fw 5.2 reports 135 rows
    groups = catalog.groups_for(dt, 135)
    assert groups[-1].end == 135


def test_rocker_and_eep_decoding():
    from custom_components.eltako_bus_config.protocol import RadioTelegram

    sid = bytes.fromhex("fef4e77c")
    assert RadioTelegram(sid, 0x05, b"\x30", 0x30).rocker == (5, "oben")
    assert RadioTelegram(sid, 0x05, b"\x10", 0x30).rocker == (5, "unten")
    assert RadioTelegram(sid, 0x05, b"\x70", 0x30).rocker == (6, "oben")
    assert RadioTelegram(sid, 0x05, b"\x50", 0x30).rocker == (6, "unten")
    assert RadioTelegram(sid, 0x05, b"\x00", 0x20).rocker is None  # release
    assert RadioTelegram(sid, 0x05, b"\xe0", 0x20).window_handle
    # 4BS teach-in with EEP A5-02-05: DB3 = 0b000010_00, DB2 = 0b00101_000, LRN type bit set
    tel = RadioTelegram(sid, 0x07, bytes([0x08, 0x28, 0x0B, 0x80]), 0)
    assert tel.eep == "A5-02-05"


def _sender_store():
    from custom_components.eltako_bus_config.senders import SenderStore

    saved = {}

    async def load():
        return saved.get("data")

    store = SenderStore(load, lambda d: saved.__setitem__("data", d))
    return store, saved


async def test_listen_stores_named_senders_and_can_be_stopped(tmp_path):
    sim, manager = _setup(tmp_path)
    manager.senders, saved = _sender_store()

    async def inject_then_stop():
        await asyncio.sleep(0.3)
        sim.inject_radio(0x05, b"\x30", bytes.fromhex("fef4e77c"))
        sim.inject_radio(0x05, b"\x00", bytes.fromhex("fef4e77c"), status=0x20)
        sim.inject_radio(0x05, b"\x70", bytes.fromhex("fef4e77c"))
        sim.inject_radio(0x05, b"\x10", bytes.fromhex("0000b001"))
        await asyncio.sleep(0.2)
        assert manager.stop_listening()

    task = asyncio.create_task(inject_then_stop())
    started = asyncio.get_running_loop().time()
    await manager.listen(600)
    await task
    assert asyncio.get_running_loop().time() - started < 5  # stopped early
    by_id = {s["id"]: s for s in manager.senders.list()}
    assert by_id["FE-F4-E7-7C"]["kind"] == "rocker" and by_id["FE-F4-E7-7C"]["keys"] == [5, 6]
    assert by_id["00-00-B0-01"]["kind"] == "bus_sender"
    manager.senders.update("FE-F4-E7-7C", name="Taster Schlafzimmer")
    # persisted and reloadable
    from custom_components.eltako_bus_config.senders import SenderStore

    async def load():
        return saved["data"]

    again = SenderStore(load, lambda d: None)
    await again.async_load()
    assert again.senders["FE-F4-E7-7C"]["name"] == "Taster Schlafzimmer"
    assert manager.senders.clear_unnamed() == 1


async def test_scan_registers_senders_from_memory(tmp_path):
    _sim, manager = _setup(tmp_path)
    manager.senders, _ = _sender_store()
    await manager.scan()
    entry = manager.senders.senders["FE-D4-E9-47"]
    assert entry.get("from_memory") and entry["keys"] == [5]


def test_sender_type_detection_and_priority():
    from custom_components.eltako_bus_config.protocol import RadioTelegram
    from custom_components.eltako_bus_config.senders import SenderStore

    async def load():
        return None

    st = SenderStore(load, lambda d: None)
    sid = bytes.fromhex("fece5eae")
    e = st.observe(RadioTelegram(sid, 0x05, b"\x30", 0x30))
    assert (e["type"], e["type_source"]) == ("rocker_switch", "pattern")
    # memory says it is used as a window contact -> memory beats pattern
    st.add_known("FE-CE-5E-AE", function=16)
    assert (e["type"], e["type_source"]) == ("contact", "memory")
    # manual beats everything, and stays when new telegrams arrive
    st.update("FE-CE-5E-AE", sender_type="rocker_switch")
    st.observe(RadioTelegram(sid, 0x05, b"\x10", 0x30))
    assert (e["type"], e["type_source"]) == ("rocker_switch", "manual")
    # 4BS teach-in with EEP A5-07-01 -> motion detector
    m = st.observe(RadioTelegram(bytes.fromhex("05123456"), 0x07, bytes([0x1C, 0x08, 0x0B, 0x80]), 0))
    assert (m["type"], m["type_source"], m["eep"]) == ("motion", "eep", "A5-07-01")
    # HA bus sender
    h = st.add_known("00-00-B0-01", kind="bus_sender", function=31)
    assert h["type"] == "controller"


def test_function_lists_and_groups():
    fsb = catalog.device_type_info(catalog.identify(b"\x04\x06\x52\x00", 2), 135)
    assert fsb["functions_by_sender"]["controller"][0] == 31
    assert 1 in fsb["functions_by_sender"]["rocker_switch"]  # universal push button verified on FSB14
    fhk = catalog.device_type_info(catalog.identify(b"\x04\x18\x10\x00", 2), 128)
    assert fhk["group_by_function"]["61"] == 1 and fhk["group_by_function"]["67"] == 2
    assert catalog.sender_type_for_function(35) == "motion"


def test_single_button_numbering_matches_hardware():
    from custom_components.eltako_bus_config.protocol import RadioTelegram

    sid = bytes.fromhex("fece5eae")
    # measured on FSB14: left top -> key 1, right top -> key 3
    assert RadioTelegram(sid, 0x05, b"\x30", 0x30).button == 1
    assert RadioTelegram(sid, 0x05, b"\x70", 0x30).button == 3
    assert RadioTelegram(sid, 0x05, b"\x10", 0x30).button == 2
    assert RadioTelegram(sid, 0x05, b"\x50", 0x30).button == 4
    assert RadioTelegram(sid, 0x05, b"\x00", 0x20).button is None
