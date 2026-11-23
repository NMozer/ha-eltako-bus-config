"""Home Assistant level tests: config flow, setup, panel, websocket API."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.components import frontend
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from custom_components.eltako_bus_config.const import DOMAIN, PANEL_URL
from custom_components.eltako_bus_config.protocol import str_to_id

from .simbus import SimBus, SimDevice


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def sim():
    bus = SimBus()
    mem = [bytes(8)] * 128
    mem[12] = str_to_id("FE-D4-E9-47") + bytes((5, 3, 1, 0))
    bus.add(SimDevice(1, 4, b"\x04\x01\x31\x00", mem))
    bus.add(SimDevice(5, 1, b"\x04\x04\x42\x00"))
    with patch(
        "custom_components.eltako_bus_config.serial_connector", lambda port, baud: bus.connect
    ), patch("custom_components.eltako_bus_config.config_flow.serial_connector", lambda port, baud: bus.connect), patch(
        "custom_components.eltako_bus_config.config_flow._list_ports", return_value=[]
    ):
        yield bus


async def test_config_flow(hass: HomeAssistant, sim):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.eltako_bus_config.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"port": "/dev/serial/by-id/usb-FAM14", "gateway": "fam14"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["baudrate"] == 57600


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DOMAIN,
        data={"port": "/dev/ttyUSB0", "gateway": "fam14", "baudrate": 57600},
        options={"scan_timeout": 0.1},
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, "http", {})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.scan_timeout = 0.01
    return entry


async def test_setup_registers_panel_and_ws(hass: HomeAssistant, hass_ws_client, sim):
    entry = await _setup(hass)
    assert PANEL_URL in hass.data[frontend.DATA_PANELS]

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": f"{DOMAIN}/info"})
    info = await ws.receive_json()
    assert info["success"] and info["result"]["gateway"] == "fam14"
    assert info["result"]["key_functions"]["51"].startswith("Schaltzustand")

    await ws.send_json({"id": 2, "type": f"{DOMAIN}/scan", "read_memory": True})
    res = await ws.receive_json()
    while res.get("type") != "result":
        res = await ws.receive_json()
    assert res["success"], res
    addrs = [d["address"] for d in res["result"]["devices"]]
    assert addrs == [1, 5, 255]

    await ws.send_json({"id": 3, "type": f"{DOMAIN}/backup/list"})
    before = len((await ws.receive_json())["result"]["backups"])

    await ws.send_json({"id": 31, "type": f"{DOMAIN}/device/write", "address": 1,
                        "rows": {"13": "05 12 34 56 00 33 02 00"}})
    res = await ws.receive_json()
    assert res["success"], res
    assert res["result"]["written_rows"] == [13]
    assert sim.devices[1].memory[13].hex() == "0512345600330200"

    await ws.send_json({"id": 40, "type": f"{DOMAIN}/backup/list"})
    res = await ws.receive_json()
    assert len(res["result"]["backups"]) == before + 1

    await ws.send_json({"id": 50, "type": f"{DOMAIN}/device/write", "address": 1, "rows": {"13": "zz"}})
    res = await ws.receive_json()
    assert not res["success"] and res["error"]["code"] == "invalid"

    await ws.send_json({"id": 60, "type": f"{DOMAIN}/senders/list"})
    res = await ws.receive_json()
    ids = {x["id"] for x in res["result"]["senders"]}
    assert "FE-D4-E9-47" in ids and "05-12-34-56" in ids  # registered from device memory
    await ws.send_json({"id": 61, "type": f"{DOMAIN}/senders/update", "sender_id": "FE-D4-E9-47", "name": "Flur"})
    res = await ws.receive_json()
    assert res["success"] and res["result"]["name"] == "Flur"
    await ws.send_json({"id": 62, "type": f"{DOMAIN}/listen/stop"})
    res = await ws.receive_json()
    assert res["success"] and res["result"]["stopped"] is False

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL not in hass.data[frontend.DATA_PANELS]


async def test_migrates_backups_and_sender_names_from_eltako_pct(hass: HomeAssistant, sim):
    import json
    from pathlib import Path

    config = Path(hass.config.config_dir)
    old_backups = config / "eltako_pct" / "backups"
    old_backups.mkdir(parents=True, exist_ok=True)
    (old_backups / "backup-old.json").write_text(json.dumps({"format": "eltako_pct_backup", "devices": []}))
    storage = config / ".storage"
    storage.mkdir(exist_ok=True)
    (storage / "eltako_pct.senders.OLDENTRY").write_text(json.dumps(
        {"version": 1, "key": "eltako_pct.senders.OLDENTRY",
         "data": {"senders": [{"id": "FE-CE-5E-AE", "name": "Testtaster", "kind": "rocker", "keys": [5, 6], "count": 4}]}}
    ))
    entry = await _setup(hass)
    manager = entry.runtime_data
    assert manager.senders.senders["FE-CE-5E-AE"]["name"] == "Testtaster"
    ids = [b["id"] for b in await manager.backups.list()]
    assert "backup-old" in ids
    # old-format backups stay usable
    data = await manager.backups.get("backup-old")
    assert manager.diff_backup(data) == []
