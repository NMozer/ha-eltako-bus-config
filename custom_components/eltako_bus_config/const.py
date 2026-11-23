"""Constants for the Bus-Konfigurator für Eltako integration."""

DOMAIN = "eltako_bus_config"

CONF_PORT = "port"
CONF_GATEWAY = "gateway"
CONF_BAUDRATE = "baudrate"
CONF_SCAN_TIMEOUT = "scan_timeout"

GATEWAY_FAM14 = "fam14"
GATEWAY_FGW14_USB = "fgw14usb"
GATEWAY_RS485 = "rs485"

GATEWAYS = {
    GATEWAY_FAM14: {"baudrate": 57600, "send_delay": 0.002},
    GATEWAY_FGW14_USB: {"baudrate": 57600, "send_delay": 0.012},
    GATEWAY_RS485: {"baudrate": 9600, "send_delay": 0.002},
}

DEFAULT_SCAN_TIMEOUT = 0.3

PANEL_URL = "eltako-bus-config"
PANEL_COMPONENT = "eltako-bus-config-panel"
STATIC_URL = "/eltako_bus_config_static"
PROGRESS_EVENT = "eltako_bus_config_progress"
STORAGE_KEY = "eltako_bus_config.devices"
STORAGE_VERSION = 1
VERSION = "0.5.0"
