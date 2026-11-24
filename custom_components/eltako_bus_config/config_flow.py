"""Config flow for Bus-Konfigurator für Eltako."""

from __future__ import annotations

import os
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_BAUDRATE,
    CONF_GATEWAY,
    CONF_PORT,
    CONF_SCAN_TIMEOUT,
    DEFAULT_SCAN_TIMEOUT,
    DOMAIN,
    GATEWAY_BRIDGE,
    GATEWAY_FAM14,
    GATEWAYS,
)
from .transport import BusTransport, TransportError, serial_connector


def _list_ports() -> list[SelectOptionDict]:
    """List serial ports, preferring stable /dev/serial/by-id paths."""
    import serial.tools.list_ports

    options: list[SelectOptionDict] = []
    by_id = "/dev/serial/by-id"
    stable: dict[str, str] = {}
    if os.path.isdir(by_id):
        for name in sorted(os.listdir(by_id)):
            path = os.path.join(by_id, name)
            stable[os.path.realpath(path)] = path
    for port in serial.tools.list_ports.comports():
        path = stable.get(os.path.realpath(port.device), port.device)
        label = f"{path} – {port.description}" if port.description and port.description != "n/a" else path
        if port.manufacturer:
            label += f" ({port.manufacturer})"
        options.append(SelectOptionDict(value=path, label=label))
    return options


async def _test_port(port: str, baudrate: int) -> None:
    transport = BusTransport(serial_connector(port, baudrate), echo_test=False)
    try:
        await transport.open()
    finally:
        await transport.close()


class EltakoPctConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            gateway = user_input[CONF_GATEWAY]
            baudrate = GATEWAYS[gateway]["baudrate"]
            port = (user_input.get(CONF_PORT) or "").strip()
            if gateway == GATEWAY_BRIDGE:
                port = ""
            elif not port:
                errors[CONF_PORT] = "port_required"
            else:
                try:
                    await _test_port(port, baudrate)
                except TransportError:
                    errors["base"] = "cannot_connect"
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                title = "Laptop-Brücke" if not port else port.rsplit("/", 1)[-1]
                return self.async_create_entry(
                    title=f"Bus-Konfigurator für Eltako ({title})",
                    data={CONF_PORT: port, CONF_GATEWAY: gateway, CONF_BAUDRATE: baudrate},
                )

        ports = await self.hass.async_add_executor_job(_list_ports)
        schema = vol.Schema(
            {
                vol.Optional(CONF_PORT): SelectSelector(
                    SelectSelectorConfig(options=ports, custom_value=True, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(CONF_GATEWAY, default=GATEWAY_FAM14): SelectSelector(
                    SelectSelectorConfig(
                        options=list(GATEWAYS), translation_key="gateway", mode=SelectSelectorMode.LIST
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EltakoPctOptionsFlow()


class EltakoPctOptionsFlow(OptionsFlow):
    """Advanced options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        entry = self.config_entry
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BAUDRATE, default=entry.options.get(CONF_BAUDRATE, entry.data.get(CONF_BAUDRATE, 57600))
                ): vol.In([9600, 19200, 57600, 115200]),
                vol.Required(
                    CONF_SCAN_TIMEOUT, default=entry.options.get(CONF_SCAN_TIMEOUT, DEFAULT_SCAN_TIMEOUT)
                ): NumberSelector(
                    NumberSelectorConfig(min=0.1, max=2.0, step=0.05, unit_of_measurement="s",
                                         mode=NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
