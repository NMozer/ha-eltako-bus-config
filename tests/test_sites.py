"""Installations (several FAM14), PCT14 import, project file, HA sender assistant, radio telegrams."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from custom_components.eltako_bus_config import pct14
from custom_components.eltako_bus_config.manager import BackupStore, BusError, BusManager
from custom_components.eltako_bus_config.protocol import (
    central_switch_data,
    parse_frame,
    radio_4bs_request,
    str_to_id,
    teach_in_4bs_data,
)
from custom_components.eltako_bus_config.senders import SenderStore
from custom_components.eltako_bus_config.sites import NO_FAM, SiteStore
from custom_components.eltako_bus_config.transport import BusTransport

from .simbus import SimBus, SimDevice

SAMPLE = (Path(__file__).parent / "fixtures" / "pct14_sample.xml").read_text("utf-8")


def _memory_store():
    data: dict = {}

    async def load():
        return data.get("v")

    def save(v):
        data["v"] = v

    return load, save, data


def _manager(tmp_path: Path, sim: SimBus | None = None) -> tuple[BusManager, SiteStore, SenderStore]:
    sim = sim or SimBus()

    async def run(func, *args):
        return await asyncio.to_thread(func, *args)

    sl, ss, _ = _memory_store()
    nl, ns, _ = _memory_store()
    sites, senders = SiteStore(sl, ss), SenderStore(nl, ns)
    manager = BusManager(
        lambda: BusTransport(sim.connect, send_delay=0),
        BackupStore(tmp_path / "backups", run),
        scan_timeout=0.01,
        scan_retries=1,
        senders=senders,
        sites=sites,
    )
    return manager, sites, senders


def test_pct14_parse_and_fsb14_rows():
    parsed = pct14.parse(SAMPLE)
    assert parsed["base_id"] == "FF-12-34-80"
    assert parsed["operating_mode"] == 5
    assert [f["address"] for f in parsed["feedback"]] == [1, 2, 3, 4, 5]
    fsb = parsed["devices"][0]
    assert (fsb["address"], fsb["size"], fsb["memory_size"], fsb["model"]) == (1, 2, 135, "04065200")
    assert fsb["entries"][0]["id"] == "FE-12-34-56"  # entry_id is little endian
    assert fsb["channels"] == {1: "Nord links", 2: "Nord rechts"}
    memory, ok = pct14.device_memory(fsb)
    assert ok
    # verified on hardware: row = 16 (first ID row of the FSB14) + entry number - 1
    assert memory[17] == "fe12345605020300"
    assert memory[22] == "0000b001001f0100"
    assert memory[16] == "00" * 8 and memory[0] is None  # settings are not part of the export
    _mem, ok = pct14.device_memory(parsed["devices"][2])  # FWZ14: no ID table mapping
    assert not ok


@pytest.mark.parametrize("bad", ["<foo/>", "kein xml", "<!DOCTYPE x [<!ENTITY a 'b'>]><exchange/>",
                                 "<exchange><rootdevice/></exchange>"])
def test_pct14_rejects_bad_files(bad):
    with pytest.raises(pct14.Pct14Error):
        pct14.parse(bad)


async def test_import_pct14_creates_installation(tmp_path):
    manager, sites, senders = _manager(tmp_path)
    result = manager.import_pct14(SAMPLE)
    assert result["created"] and result["site"] == "FF-12-34-80"
    assert result["mapped"] == ["FSB14 Adr. 1", "FSB14 Adr. 3"] and result["unmapped"] == ["FWZ14-65A Adr. 5"]
    site = sites.sites["FF-12-34-80"]
    assert site["name"] == "Verteiler Test" and site["source"] == "pct14"
    assert site["channels"] == {"1": "Nord links", "2": "Nord rechts"}
    assert site["device_names"] == {"1": "Rollladen Nord"}
    assert [f["id"] for f in sites.feedback_ids(site)] == ["FF-12-34-81", "FF-12-34-82", "FF-12-34-83",
                                                           "FF-12-34-84", "FF-12-34-85"]
    assert sites.active == "FF-12-34-80"
    assert set(manager.devices) == {1, 3, 5}
    assert senders.senders["FE-12-34-56"]["name"] == "Taster Flur"
    assert "00-00-B0-03" in senders.senders
    # importing again updates, it does not duplicate
    again = manager.import_pct14(SAMPLE, name="UV OG")
    assert not again["created"] and len(sites.sites) == 1 and site["name"] == "UV OG"


async def test_scan_creates_installation_per_fam(tmp_path):
    sim = SimBus()
    sim.add(SimDevice(1, 2, b"\x04\x06\x31\x00", [bytes(8)] * 135))
    manager, sites, _ = _manager(tmp_path, sim)
    manager.import_pct14(SAMPLE)  # another FAM14 (FF-12-34-80)
    await manager.scan()
    assert sites.active == "FF-A1-B2-80" == manager.connected_id
    assert set(sites.sites) == {"FF-12-34-80", "FF-A1-B2-80"}
    assert len(sites.sites["FF-A1-B2-80"]["devices"]) == 2  # FAM + FSB14

    # the imported installation can be viewed, but not written while another FAM14 is connected
    manager.select_site("FF-12-34-80")
    assert set(manager.devices) == {1, 3, 5}
    with pytest.raises(BusError, match="FF-A1-B2-80"):
        await manager.write_rows(1, {17: "00" * 8})
    assert sim.devices[1].memory[17] == bytes(8)

    manager.select_site("FF-A1-B2-80")
    sites.merge_pending("FF-A1-B2-80", 1, {17: "fe12345605020100"})
    await manager.write_rows(1, {17: "fe12345605020100"})
    assert sim.devices[1].memory[17] == bytes.fromhex("fe12345605020100")
    assert sites.sites["FF-A1-B2-80"]["pending"] == {}  # written changes are no longer planned


async def test_bus_without_fam_is_its_own_installation(tmp_path):
    sim = SimBus(fam=False)
    sim.add(SimDevice(4, 1, b"\x04\x04\x42\x00"))
    manager, sites, _ = _manager(tmp_path, sim)
    await manager.scan(read_memory=False)
    assert sites.active == NO_FAM and set(sites.sites) == {NO_FAM}


async def test_ha_sender_assistant_plans_house_wide_ids(tmp_path):
    manager, sites, senders = _manager(tmp_path)
    manager.import_pct14(SAMPLE)
    res = manager.plan_ha_senders("FF-AA-80-00", [
        {"site": "FF-12-34-80", "address": 1, "bit": 0},
        {"site": "FF-12-34-80", "address": 1, "bit": 1},
        {"site": "FF-12-34-80", "address": 5, "bit": -1},
    ])
    ids = [a["sender_id"] for a in res["assigned"]]
    assert ids == ["FF-AA-80-01", "FF-AA-80-02"]
    assert res["skipped"][0]["address"] == 5
    pending = sites.sites["FF-12-34-80"]["pending"]["1"]
    # first free rows of function group 2 (rows 17-19 and 22-23 are used)
    assert pending == {"20": "ffaa8001001f0100", "21": "ffaa8002001f0200"}
    assert senders.senders["FF-AA-80-01"]["name"] == "HA: Nord links"
    assert senders.senders["FF-AA-80-01"]["type"] == "controller"
    assert sites.house["stick_base_id"] == "FF-AA-80-00"
    # a second run continues with the next free ID and the next free row
    res = manager.plan_ha_senders("FF-AA-80-00", [{"site": "FF-12-34-80", "address": 3, "bit": 0}])
    assert res["assigned"][0]["sender_id"] == "FF-AA-80-03"
    assert sites.sites["FF-12-34-80"]["pending"]["3"] == {"18": "ffaa8003001f0100"}
    with pytest.raises(ValueError):
        manager.plan_ha_senders("FF-AA-80-05", [])


async def test_project_roundtrip(tmp_path):
    manager, sites, senders = _manager(tmp_path)
    manager.import_pct14(SAMPLE, name="UV OG")
    sites.rename_channel("FF-12-34-80", 3, "Süd")
    project = manager.export_project()
    assert project["format"] == "eltako_bus_config_project"

    other, other_sites, other_senders = _manager(tmp_path)
    result = other.import_project(project)
    assert result == {"created": 1, "updated": 0, "senders": len(senders.senders)}
    site = other_sites.sites["FF-12-34-80"]
    assert site["name"] == "UV OG" and site["channels"]["3"] == "Süd"
    assert other_sites.active == "FF-12-34-80" and set(other.devices) == {1, 3, 5}
    assert other_senders.senders["FE-12-34-56"]["name"] == "Taster Flur"
    with pytest.raises(ValueError):
        other.import_project({"format": "something else"})


def test_radio_telegrams_match_reference_library():
    em = pytest.importorskip("eltakobus.message")
    sender = str_to_id("FF-AA-80-01")
    teach = radio_4bs_request(sender, teach_in_4bs_data("A5-38-08"))
    assert teach_in_4bs_data("A5-38-08") == bytes.fromhex("e0400d80")
    assert teach.serialize() == em.Regular4BSMessage(sender, 0, teach_in_4bs_data("A5-38-08"), True).serialize()
    on = radio_4bs_request(sender, central_switch_data(True))
    assert on.serialize() == em.Regular4BSMessage(sender, 0, bytes.fromhex("01000009"), True).serialize()


async def test_send_radio_puts_telegram_on_unlocked_bus(tmp_path):
    sim = SimBus()
    manager, _sites, _ = _manager(tmp_path, sim)
    res = await manager.send_radio("FF-AA-80-01", "teach_in")
    assert res["frame"] == "a5 5a 6b 07 e0 40 0d 80 ff aa 80 01 00 49"
    sent = [f for f in sim.requests if f.org == 0x07]
    assert len(sent) == 1 and sent[0].hseq == 3
    assert not any(f.org == 0xFF for f in sim.requests)  # bus stays unlocked
    assert parse_frame(bytes.fromhex(res["frame"].replace(" ", ""))).data[4:] == str_to_id("FF-AA-80-01")


async def test_laptop_bridge_relays_the_bus(tmp_path):
    """The browser relays bytes; scan, site detection and writes work as over a serial port."""
    from custom_components.eltako_bus_config.bridge import BridgeHub

    sim = SimBus(echo=False)
    sim.add(SimDevice(1, 2, b"\x04\x06\x31\x00", [bytes(8)] * 135))
    hub = BridgeHub()

    class _BrowserSide:  # what the panel does: bytes from the FAM14 go to bridge/rx
        feed_data = staticmethod(hub.feed)

    sim.reader = _BrowserSide()
    loop = asyncio.get_running_loop()
    replaced: list[bool] = []
    detach = hub.attach(lambda data: loop.call_soon(sim.handle, data), lambda: replaced.append(True), "Laptop")

    async def run(func, *args):
        return await asyncio.to_thread(func, *args)

    sl, ss, _ = _memory_store()
    sites = SiteStore(sl, ss)
    manager = BusManager(lambda: BusTransport(hub.connect, send_delay=0), BackupStore(tmp_path / "b", run),
                         scan_timeout=0.05, scan_retries=1, sites=sites, bridge=hub)
    assert manager.state()["bridge"] is True
    result = await manager.detect_site()
    assert result == {"site": "FF-A1-B2-80", "created": True} and sites.active == "FF-A1-B2-80"
    await manager.scan()
    assert set(manager.devices) == {1, 255}
    await manager.write_rows(1, {17: "fe12345605020100"})
    assert sim.devices[1].memory[17] == bytes.fromhex("fe12345605020100")
    assert hub.bytes_in and hub.bytes_out

    # a second browser takes over, the first is told so
    hub.attach(lambda data: None, lambda: None)
    assert replaced == [True]
    detach()  # stale detach of the first browser must not remove the second
    assert hub.attached


async def test_ha_sender_targets_list_channels_of_all_installations(tmp_path):
    manager, sites, _ = _manager(tmp_path)
    manager.import_pct14(SAMPLE)
    targets = manager.ha_sender_targets("FF-AA-80-00")
    fsb = [t for t in targets if t["address"] == 1]
    assert [(t["bit"], t["label"], t["existing"]) for t in fsb] == [
        (0, "Nord links", ["00-00-B0-01"]), (1, "Nord rechts", ["00-00-B0-02"])]
    assert all(t["known"] for t in targets)
    assert {t["address"] for t in targets} == {1, 3}  # the meter has no ID table
