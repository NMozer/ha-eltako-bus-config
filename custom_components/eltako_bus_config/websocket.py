"""Websocket API used by the sidebar panel."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import functools
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from . import catalog
from .const import CONF_GATEWAY, CONF_PORT, DOMAIN
from .manager import BusError, BusManager, BusyError

Handler = Callable[[HomeAssistant, websocket_api.ActiveConnection, dict[str, Any], BusManager], Awaitable[Any]]


def _get_manager(hass: HomeAssistant) -> tuple[BusManager, Any] | None:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data, entry
    return None


def _with_manager(func: Handler):
    """Resolve the manager and translate errors into websocket errors."""

    @functools.wraps(func)
    async def wrapper(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
        found = _get_manager(hass)
        if found is None:
            connection.send_error(msg["id"], "not_configured", "Bus-Konfigurator für Eltako ist nicht eingerichtet")
            return
        manager, _entry = found
        try:
            result = await func(hass, connection, msg, manager)
        except BusyError as err:
            connection.send_error(msg["id"], "busy", str(err))
        except BusError as err:
            connection.send_error(msg["id"], "bus_error", str(err))
        except (ValueError, KeyError, FileNotFoundError) as err:
            connection.send_error(msg["id"], "invalid", str(err))
        else:
            connection.send_result(msg["id"], result)

    return wrapper


def _cmd(schema: dict, func: Handler):
    return websocket_api.require_admin(
        websocket_api.websocket_command(schema)(websocket_api.async_response(_with_manager(func)))
    )


async def _info(hass, connection, msg, manager: BusManager):
    _m, entry = _get_manager(hass)
    return {
        "port": entry.data.get(CONF_PORT) or "",
        "gateway": entry.data[CONF_GATEWAY],
        "state": manager.state(),
        "key_functions": {str(k): v for k, v in catalog.KEY_FUNCTIONS.items()},
        "key_labels": {str(k): v for k, v in catalog.KEY_LABELS.items()},
        "eep_functions": catalog.EEP_FUNCTION,
        "sender_types": catalog.SENDER_TYPES,
    }


async def _devices(hass, connection, msg, manager: BusManager):
    return {"state": manager.state(), "devices": [d.as_dict() for _, d in sorted(manager.devices.items())]}


async def _scan(hass, connection, msg, manager: BusManager):
    devices = await manager.scan(read_memory=msg["read_memory"])
    return {"state": manager.state(), "devices": devices}


async def _read(hass, connection, msg, manager: BusManager):
    return await manager.read_device(msg["address"])


async def _write(hass, connection, msg, manager: BusManager):
    rows = {int(k): v for k, v in msg["rows"].items()}
    return await manager.write_rows(msg["address"], rows)


async def _identify(hass, connection, msg, manager: BusManager):
    await manager.identify(msg["address"])
    return {}


async def _probe(hass, connection, msg, manager: BusManager):
    return await manager.probe()


async def _listen(hass, connection, msg, manager: BusManager):
    return {"senders": await manager.listen(msg["seconds"], lock_bus=msg["lock_bus"])}


async def _listen_stop(hass, connection, msg, manager: BusManager):
    return {"stopped": manager.stop_listening()}


def _channels(manager: BusManager) -> dict[str, str]:
    if manager.sites is not None and manager.sites.active:
        return manager.sites.channels(manager.sites.active)
    return dict(manager.senders.channels) if manager.senders else {}


async def _senders_list(hass, connection, msg, manager: BusManager):
    if not manager.senders:
        return {"senders": [], "channels": {}}
    return {"senders": manager.senders.list(), "channels": _channels(manager)}


async def _channel_rename(hass, connection, msg, manager: BusManager):
    if manager.sites is not None and manager.sites.active:
        return {"channels": manager.sites.rename_channel(manager.sites.active, msg["address"], msg.get("name", ""))}
    return {"channels": manager.senders.rename_channel(msg["address"], msg.get("name", ""))}


def _sites_payload(manager: BusManager) -> dict[str, Any]:
    sites = manager.sites
    return {
        "sites": sites.summary(manager.connected_id) if sites else [],
        "active": manager.active_site_id,
        "connected": manager.connected_id,
        "site": manager.site_details() if sites else {},
        "house": dict(sites.house) if sites else {},
        "state": manager.state(),
    }


async def _sites_list(hass, connection, msg, manager: BusManager):
    return _sites_payload(manager)


async def _sites_select(hass, connection, msg, manager: BusManager):
    manager.select_site(msg["site"])
    return _sites_payload(manager) | {"devices": [d.as_dict() for _, d in sorted(manager.devices.items())],
                                      "channels": _channels(manager)}


async def _sites_update(hass, connection, msg, manager: BusManager):
    manager.sites.update_meta(msg["site"], name=msg.get("name"), location=msg.get("location"))
    return _sites_payload(manager)


async def _sites_delete(hass, connection, msg, manager: BusManager):
    if msg["site"] == manager.active_site_id and manager.operation:
        raise ValueError("Während eines Buszugriffs kann die Anlage nicht gelöscht werden")
    manager.sites.delete(msg["site"])
    manager.load_site(manager.sites.active)
    return _sites_payload(manager)


async def _sites_pending(hass, connection, msg, manager: BusManager):
    manager.sites.set_pending(msg["site"], msg["pending"])
    return _sites_payload(manager)


async def _pct14_import(hass, connection, msg, manager: BusManager):
    result = manager.import_pct14(msg["xml"], msg.get("name"))
    return {"result": result} | _sites_payload(manager)


async def _project_export(hass, connection, msg, manager: BusManager):
    return manager.export_project()


async def _project_import(hass, connection, msg, manager: BusManager):
    result = manager.import_project(msg["data"])
    return {"result": result} | _sites_payload(manager)


async def _radio_send(hass, connection, msg, manager: BusManager):
    return await manager.send_radio(msg["sender_id"], msg["action"], eep=msg.get("eep", "A5-38-08"),
                                    db0=msg.get("db0"))


async def _sites_detect(hass, connection, msg, manager: BusManager):
    result = await manager.detect_site()
    return {"result": result, "devices": [d.as_dict() for _, d in sorted(manager.devices.items())],
            "channels": _channels(manager)} | _sites_payload(manager)


async def _ha_senders_targets(hass, connection, msg, manager: BusManager):
    stick = msg.get("stick_base_id") or (manager.sites.house.get("stick_base_id") if manager.sites else None)
    return {"targets": manager.ha_sender_targets(stick), "stick_base_id": stick}


async def _ha_senders_plan(hass, connection, msg, manager: BusManager):
    result = manager.plan_ha_senders(msg["stick_base_id"], msg["targets"])
    return {"result": result} | _sites_payload(manager)


async def _senders_update(hass, connection, msg, manager: BusManager):
    entry = manager.senders.update(msg["sender_id"], name=msg.get("name"), hidden=msg.get("hidden"),
                                   sender_type=msg.get("sender_type"))
    if msg.get("sender_type") == "":
        manager.register_known_senders()  # re-detect from device memory
    return entry


async def _senders_delete(hass, connection, msg, manager: BusManager):
    manager.senders.delete(msg["sender_id"])
    return {}


async def _senders_clear(hass, connection, msg, manager: BusManager):
    removed = manager.senders.clear_unnamed()
    manager.register_known_senders()
    return {"removed": removed}


async def _backup_list(hass, connection, msg, manager: BusManager):
    return {"backups": await manager.backups.list()}


async def _backup_create(hass, connection, msg, manager: BusManager):
    return await manager.create_backup(msg.get("name"))


async def _backup_get(hass, connection, msg, manager: BusManager):
    return await manager.backups.get(msg["backup_id"])


async def _backup_delete(hass, connection, msg, manager: BusManager):
    await manager.backups.delete(msg["backup_id"])
    return {}


async def _backup_import(hass, connection, msg, manager: BusManager):
    return {"id": await manager.import_backup(msg["data"], msg.get("name"))}


async def _backup_diff(hass, connection, msg, manager: BusManager):
    data = await manager.backups.get(msg["backup_id"])
    return {"devices": manager.diff_backup(data, msg.get("addresses"))}


async def _backup_restore(hass, connection, msg, manager: BusManager):
    return {"results": await manager.restore_backup(msg["backup_id"], msg["addresses"])}


_ADDRESS = vol.All(vol.Coerce(int), vol.Range(min=1, max=255))
_SENDER_ID = vol.Match(r"^[0-9A-F]{2}(-[0-9A-F]{2}){3}$")
_BACKUP_ID = vol.Match(r"^[A-Za-z0-9_\-]+$")
_SITE = vol.Match(r"^([0-9A-F]{2}(-[0-9A-F]{2}){3}|OHNE-FAM14)$")

COMMANDS = [
    ({vol.Required("type"): f"{DOMAIN}/info"}, _info),
    ({vol.Required("type"): f"{DOMAIN}/devices"}, _devices),
    ({vol.Required("type"): f"{DOMAIN}/scan", vol.Optional("read_memory", default=True): bool}, _scan),
    ({vol.Required("type"): f"{DOMAIN}/device/read", vol.Required("address"): _ADDRESS}, _read),
    (
        {
            vol.Required("type"): f"{DOMAIN}/device/write",
            vol.Required("address"): _ADDRESS,
            vol.Required("rows"): {vol.Coerce(str): str},
        },
        _write,
    ),
    ({vol.Required("type"): f"{DOMAIN}/device/identify", vol.Required("address"): _ADDRESS}, _identify),
    ({vol.Required("type"): f"{DOMAIN}/probe"}, _probe),
    (
        {
            vol.Required("type"): f"{DOMAIN}/listen",
            vol.Optional("seconds", default=20): vol.All(vol.Coerce(float), vol.Range(min=1, max=900)),
            vol.Optional("lock_bus", default=False): bool,
        },
        _listen,
    ),
    ({vol.Required("type"): f"{DOMAIN}/listen/stop"}, _listen_stop),
    ({vol.Required("type"): f"{DOMAIN}/senders/list"}, _senders_list),
    (
        {
            vol.Required("type"): f"{DOMAIN}/senders/update",
            vol.Required("sender_id"): _SENDER_ID,
            vol.Optional("name"): vol.All(str, vol.Length(max=80)),
            vol.Optional("hidden"): bool,
            vol.Optional("sender_type"): vol.Any("", vol.In(list(catalog.SENDER_TYPES))),
        },
        _senders_update,
    ),
    ({vol.Required("type"): f"{DOMAIN}/senders/delete", vol.Required("sender_id"): _SENDER_ID}, _senders_delete),
    ({vol.Required("type"): f"{DOMAIN}/senders/clear"}, _senders_clear),
    (
        {
            vol.Required("type"): f"{DOMAIN}/channels/rename",
            vol.Required("address"): _ADDRESS,
            vol.Optional("name", default=""): vol.All(str, vol.Length(max=80)),
        },
        _channel_rename,
    ),
    ({vol.Required("type"): f"{DOMAIN}/sites/list"}, _sites_list),
    ({vol.Required("type"): f"{DOMAIN}/sites/select", vol.Required("site"): _SITE}, _sites_select),
    (
        {
            vol.Required("type"): f"{DOMAIN}/sites/update",
            vol.Required("site"): _SITE,
            vol.Optional("name"): vol.All(str, vol.Length(max=80)),
            vol.Optional("location"): vol.All(str, vol.Length(max=80)),
        },
        _sites_update,
    ),
    ({vol.Required("type"): f"{DOMAIN}/sites/delete", vol.Required("site"): _SITE}, _sites_delete),
    ({vol.Required("type"): f"{DOMAIN}/sites/detect"}, _sites_detect),
    (
        {
            vol.Required("type"): f"{DOMAIN}/sites/pending",
            vol.Required("site"): _SITE,
            vol.Required("pending"): {vol.Coerce(str): {vol.Coerce(str): str}},
        },
        _sites_pending,
    ),
    (
        {vol.Required("type"): f"{DOMAIN}/pct14/import", vol.Required("xml"): str,
         vol.Optional("name"): vol.All(str, vol.Length(max=80))},
        _pct14_import,
    ),
    ({vol.Required("type"): f"{DOMAIN}/project/export"}, _project_export),
    ({vol.Required("type"): f"{DOMAIN}/project/import", vol.Required("data"): dict}, _project_import),
    (
        {
            vol.Required("type"): f"{DOMAIN}/radio/send",
            vol.Required("sender_id"): _SENDER_ID,
            vol.Required("action"): vol.In(["teach_in", "on", "off", "rps"]),
            vol.Optional("eep", default="A5-38-08"): str,
            vol.Optional("db0"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
        },
        _radio_send,
    ),
    ({vol.Required("type"): f"{DOMAIN}/ha_senders/targets", vol.Optional("stick_base_id"): _SENDER_ID},
     _ha_senders_targets),
    (
        {
            vol.Required("type"): f"{DOMAIN}/ha_senders/plan",
            vol.Required("stick_base_id"): _SENDER_ID,
            vol.Required("targets"): [
                {vol.Required("site"): _SITE, vol.Required("address"): _ADDRESS,
                 vol.Optional("bit", default=-1): vol.All(vol.Coerce(int), vol.Range(min=-1, max=16))}
            ],
        },
        _ha_senders_plan,
    ),
    ({vol.Required("type"): f"{DOMAIN}/backup/list"}, _backup_list),
    ({vol.Required("type"): f"{DOMAIN}/backup/create", vol.Optional("name"): str}, _backup_create),
    ({vol.Required("type"): f"{DOMAIN}/backup/get", vol.Required("backup_id"): _BACKUP_ID}, _backup_get),
    ({vol.Required("type"): f"{DOMAIN}/backup/delete", vol.Required("backup_id"): _BACKUP_ID}, _backup_delete),
    (
        {vol.Required("type"): f"{DOMAIN}/backup/import", vol.Required("data"): dict, vol.Optional("name"): str},
        _backup_import,
    ),
    (
        {
            vol.Required("type"): f"{DOMAIN}/backup/diff",
            vol.Required("backup_id"): _BACKUP_ID,
            vol.Optional("addresses"): [_ADDRESS],
        },
        _backup_diff,
    ),
    (
        {
            vol.Required("type"): f"{DOMAIN}/backup/restore",
            vol.Required("backup_id"): _BACKUP_ID,
            vol.Required("addresses"): [_ADDRESS],
        },
        _backup_restore,
    ),
]


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/bridge/attach", vol.Optional("label"): vol.All(str, vol.Length(max=120))}
)
@callback
def _ws_bridge_attach(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The panel offers the serial port of the computer it runs on (Web Serial)."""
    from . import get_bridge

    hub = get_bridge(hass)
    msg_id = msg["id"]

    def send(data: bytes) -> None:
        connection.send_message(websocket_api.event_message(msg_id, {"tx": data.hex()}))

    def replaced() -> None:
        connection.send_message(websocket_api.event_message(msg_id, {"detached": "replaced"}))

    connection.subscriptions[msg_id] = hub.attach(send, replaced, msg.get("label"))
    connection.send_result(msg_id)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/bridge/rx", vol.Required("data"): vol.Match(r"^([0-9a-fA-F]{2})*$")}
)
@callback
def _ws_bridge_rx(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Bytes received by the browser from the FAM14 (handled synchronously to keep their order)."""
    from . import get_bridge

    get_bridge(hass).feed(bytes.fromhex(msg["data"]))
    connection.send_result(msg["id"])


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    for schema, func in COMMANDS:
        websocket_api.async_register_command(hass, _cmd(schema, func))
    websocket_api.async_register_command(hass, _ws_bridge_attach)
    websocket_api.async_register_command(hass, _ws_bridge_rx)
