"""Bus-Konfigurator für Eltako – configure Eltako Series 14 bus devices from Home Assistant.

Covers the core functions of the Eltako PCT14 Windows tool: bus scan,
reading and writing device memory (ID tables and settings), backup and
restore. Device control stays with a separate control integration.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import shutil

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_BAUDRATE,
    CONF_GATEWAY,
    CONF_PORT,
    CONF_SCAN_TIMEOUT,
    DEFAULT_SCAN_TIMEOUT,
    DOMAIN,
    GATEWAYS,
    PANEL_COMPONENT,
    PANEL_URL,
    PROGRESS_EVENT,
    STATIC_URL,
    STORAGE_KEY,
    STORAGE_VERSION,
    VERSION,
)
from .manager import BackupStore, BusManager
from .senders import SenderStore
from .transport import BusTransport, serial_connector
from .websocket import async_register_websocket

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type EltakoPctConfigEntry = ConfigEntry[BusManager]

FRONTEND_DIR = Path(__file__).parent / "frontend"
PANEL_FILE = "eltako-bus-config-panel.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_register_websocket(hass)
    return True


def build_manager(hass: HomeAssistant, entry: ConfigEntry, store: Store) -> BusManager:
    gateway = entry.data[CONF_GATEWAY]
    gw = GATEWAYS[gateway]
    port = entry.data[CONF_PORT]
    baudrate = entry.options.get(CONF_BAUDRATE, entry.data.get(CONF_BAUDRATE, gw["baudrate"]))

    def transport_factory() -> BusTransport:
        return BusTransport(serial_connector(port, int(baudrate)), send_delay=gw["send_delay"])

    @callback
    def progress(event: dict) -> None:
        hass.bus.async_fire(PROGRESS_EVENT, event)

    manager: BusManager

    async def persist() -> None:
        store.async_delay_save(manager.export_cache, 2)

    sender_store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.senders.{entry.entry_id}")
    senders = SenderStore(sender_store.async_load, lambda data: sender_store.async_delay_save(lambda: data, 5))

    manager = BusManager(
        transport_factory,
        BackupStore(Path(hass.config.path(DOMAIN, "backups")), hass.async_add_executor_job),
        scan_timeout=float(entry.options.get(CONF_SCAN_TIMEOUT, DEFAULT_SCAN_TIMEOUT)),
        progress=progress,
        on_devices_changed=persist,
        senders=senders,
    )
    return manager


async def async_setup_entry(hass: HomeAssistant, entry: EltakoPctConfigEntry) -> bool:
    store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}")
    manager = build_manager(hass, entry, store)
    manager.import_cache(await store.async_load())
    await manager.senders.async_load()
    await _async_migrate_from_eltako_pct(hass, manager)
    manager.register_known_senders()
    entry.runtime_data = manager

    await _async_register_panel(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


OLD_DOMAIN = "eltako_pct"


async def _async_migrate_from_eltako_pct(hass: HomeAssistant, manager: BusManager) -> None:
    """Take over backups and sender names from the earlier integration name 'eltako_pct'."""
    config_dir = Path(hass.config.config_dir)

    def _collect() -> tuple[int, dict | None]:
        copied = 0
        old_backups = config_dir / OLD_DOMAIN / "backups"
        new_backups = config_dir / DOMAIN / "backups"
        if old_backups.is_dir():
            new_backups.mkdir(parents=True, exist_ok=True)
            for src in old_backups.glob("*.json"):
                dst = new_backups / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
                    copied += 1
        senders = None
        candidates = sorted((config_dir / ".storage").glob(f"{OLD_DOMAIN}.senders.*"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            try:
                senders = json.loads(candidates[0].read_text("utf-8")).get("data")
            except (OSError, ValueError):
                senders = None
        return copied, senders

    copied, old = await hass.async_add_executor_job(_collect)
    merged = 0
    if old and manager.senders:
        for entry in old.get("senders", []):
            sid = entry.get("id")
            if not sid:
                continue
            current = manager.senders.senders.get(sid)
            if current is None:
                manager.senders.senders[sid] = entry
                merged += 1
            elif entry.get("name") and not current.get("name"):
                current["name"] = entry["name"]
                merged += 1
        if merged:
            manager.senders.update(next(iter(manager.senders.senders)))  # persist
    if copied or merged:
        _LOGGER.info("Migrated from %s: %d backup(s), %d sender(s)", OLD_DOMAIN, copied, merged)


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_panel(hass: HomeAssistant) -> None:
    data = hass.data.setdefault(DOMAIN, {})
    if not data.get("static_registered"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
        )
        data["static_registered"] = True
    if PANEL_URL in hass.data.get(frontend.DATA_PANELS, {}):
        return
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_COMPONENT,
        frontend_url_path=PANEL_URL,
        module_url=f"{STATIC_URL}/{PANEL_FILE}?v={VERSION}",
        sidebar_title="Eltako Bus",
        sidebar_icon="mdi:tune-vertical-variant",
        require_admin=True,
        config={},
    )


async def async_unload_entry(hass: HomeAssistant, entry: EltakoPctConfigEntry) -> bool:
    if not hass.config_entries.async_loaded_entries(DOMAIN) or all(
        e.entry_id == entry.entry_id for e in hass.config_entries.async_loaded_entries(DOMAIN)
    ):
        frontend.async_remove_panel(hass, PANEL_URL)
    return True
