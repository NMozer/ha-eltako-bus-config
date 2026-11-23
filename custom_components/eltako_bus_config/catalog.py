"""Knowledge about Eltako Series 14 devices and their memory layout.

Memory of a bus device is a list of 8 byte rows. Rows 0..7 (sometimes more)
contain device settings, the remaining rows form the ID table ("Funktions-
gruppen") with one taught-in sensor per row:

    AD DR ES S0 | KEY | FUNC | CH | VAL

  * AD DR ES S0  sender ID of the taught-in sensor / switch
  * KEY          which key / rocker side (5 = left, 6 = right, 0 = 4BS/GFVS)
  * FUNC         PCT14 key function number (see KEY_FUNCTIONS)
  * CH           channel bit mask (multi channel devices), ramp speed
                 (single channel dimmers) or DALI group (FDG14)
  * VAL          function dependent value (percent, run time, ...)

Layouts are taken from the eltako14bus library (LGPL-3.0) and verified
against eo_man. Unknown devices are still shown with their raw memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CH_BITMASK = "bitmask"
CH_VALUE = "value"
CH_DALI = "dali_group"


@dataclass(frozen=True)
class FunctionGroup:
    number: int
    start: int  # first row (inclusive)
    end: int  # last row (exclusive); clamped to memory size at runtime
    label: str


@dataclass(frozen=True)
class DeviceType:
    key: str
    name: str
    description: str
    type_ids: tuple[bytes, ...]
    size: int | None = None  # bus addresses (channels); None = any
    channel_mode: str = CH_BITMASK
    groups: tuple[FunctionGroup, ...] = ()
    row_notes: dict[int, str] = field(default_factory=dict)
    base_id_row: int | None = None


def _g(number: int, start: int, end: int, label: str) -> FunctionGroup:
    return FunctionGroup(number, start, end, label)


_FSR_GROUPS = (
    _g(1, 8, 12, "Funktionsgruppe 1 (Sonderfunktionen)"),
    _g(2, 12, 256, "Funktionsgruppe 2 (Taster, Sensoren, GFVS)"),
)
_FSR_NOTES = {2: "R0 R1 R2 R3 … – Zustand des Kanals nach Spannungswiederkehr wiederherstellen (bool je Kanal)"}

_DIMMER_GROUPS = (
    _g(1, 8, 9, "Funktionsgruppe 1 (Sonderfunktionen)"),
    _g(2, 9, 12, "Funktionsgruppe 2 (Sonderfunktionen)"),
    _g(3, 12, 256, "Funktionsgruppe 3 (Taster, Sensoren, GFVS)"),
)

_FHK_GROUPS_2 = (
    _g(1, 8, 10, "Funktionsgruppe 1 (Temperaturregler)"),
    _g(2, 10, 12, "Funktionsgruppe 2 (Temperatursensor)"),
    _g(3, 12, 14, "Funktionsgruppe 3 (Smart-Home-Software)"),
    _g(4, 14, 256, "Funktionsgruppe 4 (Taster, Kontakte)"),
)
_FHK_GROUPS_4 = (
    _g(1, 8, 12, "Funktionsgruppe 1 (Temperaturregler)"),
    _g(2, 12, 16, "Funktionsgruppe 2 (Temperatursensor)"),
    _g(3, 16, 20, "Funktionsgruppe 3 (Smart-Home-Software)"),
    _g(4, 20, 256, "Funktionsgruppe 4 (Taster, Kontakte)"),
)
_FHK_NOTES = {
    1: "Basis-ID",
    4: "-- RV -- -- … – Rückmeldung, Bit 1 = Kanal 1, Bit 2 = Kanal 2",
    5: "-- -- -- -- dt dt -- -- – Temperatur-Offset Kanal 1 und 2",
}

DEVICE_TYPES: tuple[DeviceType, ...] = (
    DeviceType("FAM14", "FAM14", "Funk-Antennenmodul / Busmaster",
               (b"\x07\xff", b"\x08\xff"), 1, groups=(), row_notes={1: "Basis-ID des FAM14"}, base_id_row=1),
    DeviceType("FGW14_USB", "FGW14-USB", "RS485-Bus-Gateway mit USB", (b"\x04\xfe",), 1),
    DeviceType("FTD14", "FTD14", "Telegramm-Duplikator", (b"\x04\xa0",), 1,
               groups=(_g(1, 8, 256, "Eingelernte Sender"),), row_notes={1: "Basis-ID"}, base_id_row=1),
    DeviceType("FSR14_4x", "FSR14-4x", "4-Kanal-Stromstoß-Schaltrelais", (b"\x04\x01",), 4,
               groups=_FSR_GROUPS, row_notes=_FSR_NOTES),
    DeviceType("FSR14_2x", "FSR14-2x", "2-Kanal-Stromstoß-Schaltrelais", (b"\x04\x02",), 2,
               groups=_FSR_GROUPS, row_notes=_FSR_NOTES),
    DeviceType("FSR14_1x", "FSR14-1x", "1-Kanal-Stromstoß-Schaltrelais", (b"\x04\x01",), 1,
               groups=_FSR_GROUPS, row_notes=_FSR_NOTES),
    DeviceType("FSR14M_2x", "FSR14M-2x", "2-Kanal-Schaltrelais mit Strommessung", (b"\x04\x0b",), 2,
               groups=_FSR_GROUPS, row_notes=_FSR_NOTES),
    DeviceType("F4SR14_LED", "F4SR14-LED", "4-Kanal-Schaltrelais für LED", (b"\x04\x09",), 4,
               groups=_FSR_GROUPS, row_notes=_FSR_NOTES),
    DeviceType("FSB14", "FSB14", "2-Kanal-Rollladenaktor", (b"\x04\x06", b"\x05\x06"), 2,
               groups=(_g(1, 16, 17, "Funktionsgruppe 1 (Sonderfunktionen)"),
                       _g(2, 17, 256, "Funktionsgruppe 2 (Taster, Sensoren, GFVS)")),
               row_notes={17: "Letztes Byte vermutlich Fahrzeit (00 bei Tastern)"}),
    DeviceType("FUD14", "FUD14", "Universal-Dimmschalter", (b"\x04\x04",), 1, CH_VALUE, _DIMMER_GROUPS),
    DeviceType("FUD14_800W", "FUD14/800W", "Universal-Dimmschalter 800 W", (b"\x04\x05",), 1, CH_VALUE, _DIMMER_GROUPS),
    DeviceType("FSG14_1_10V", "FSG14/1-10V", "Steuergerät 1–10 V", (b"\x04\x07",), 1, CH_VALUE, _DIMMER_GROUPS),
    DeviceType("FDG14", "FDG14", "DALI-Gateway", (b"\x04\x34",), None, CH_DALI,
               (_g(1, 14, 256, "Funktionsgruppe 1 (Taster, Sensoren, GFVS)"),),
               {2: "Lichtszene 1 – 16 Dimmwerte (0–100, 101 = Maske)", 4: "Lichtszene 2", 6: "Lichtszene 3",
                8: "Lichtszene 4"}),
    DeviceType("FD2G14", "FD2G14", "DALI-2-Gateway", (b"\x04\x82",), None, CH_DALI,
               (_g(1, 14, 256, "Funktionsgruppe 1 (Taster, Sensoren, GFVS)"),),
               {2: "Lichtszene 1 – 16 Dimmwerte (0–100, 101 = Maske)", 4: "Lichtszene 2", 6: "Lichtszene 3",
                8: "Lichtszene 4"}),
    DeviceType("FAE14SSR", "FAE14SSR", "Heiz-/Kühlaktor", (b"\x04\x16",), 2,
               groups=_FHK_GROUPS_2, row_notes=_FHK_NOTES),
    DeviceType("F4HK14", "F4HK14", "4-Kanal-Heiz-/Kühlrelais", (b"\x04\x18",), 4,
               groups=_FHK_GROUPS_4, row_notes=_FHK_NOTES),
    DeviceType("FHK14", "FHK14", "Heiz-/Kühlrelais", (b"\x04\x18",), 2,
               groups=_FHK_GROUPS_2, row_notes=_FHK_NOTES),
    DeviceType("FMZ14", "FMZ14", "Multifunktions-Zeitrelais", (b"\x04\x0e",), 1,
               groups=(_g(1, 8, 55, "Eingelernte Taster"),)),
    DeviceType("F3Z14D", "F3Z14D", "3-fach-Zähler", (b"\x04\x67",), 3),
    DeviceType("FWG14MS", "FWG14MS", "Wetterstation-Gateway", (b"\x04\x1a",), 1),
    DeviceType("FSU14", "FSU14", "Schaltuhr", (b"\x07\x14",), 8),
    DeviceType("FMSR14", "FMSR14", "Multifunktions-Sensorrelais", (b"\x05\x15",), 5),
    DeviceType("FWZ14_65A", "FWZ14-65A", "Stromzähler", (b"\x04\x66",), 1,
               row_notes={1: "Zählerstand (kWh)", 5: "Seriennummer S0 S1 S2 S3"}),
)

UNKNOWN = DeviceType("UNKNOWN", "Unbekannt", "Unbekanntes Gerät", ())


def identify(model: bytes, size: int) -> DeviceType:
    """Find the device type for a discovery reply (model bytes + bus size)."""
    type_id = bytes(model[:2])
    fallback = None
    for dt in DEVICE_TYPES:
        if type_id in dt.type_ids:
            if dt.size is None or dt.size == size:
                return dt
            fallback = fallback or dt
    return fallback or UNKNOWN


def groups_for(dt: DeviceType, memory_size: int) -> list[FunctionGroup]:
    result = []
    for g in dt.groups:
        end = min(g.end, memory_size)
        if g.start < end:
            result.append(FunctionGroup(g.number, g.start, end, g.label))
    return result


# --------------------------------------------------------------------------
# PCT14 key functions (numbers as used in device memory)
# --------------------------------------------------------------------------

KEY_FUNCTIONS: dict[int, str] = {
    0: "Keine Funktion",
    1: "Universaltaster",
    2: "Richtungstaster (oben = Ein)",
    3: "Richtungstaster (unten = Ein)",
    4: "Zentral Aus",
    5: "Zentral Ein",
    6: "Szenentaster",
    7: "Sequenzieller Szenentaster",
    8: "Lichtwecker",
    10: "Dimmwert in Prozent",
    11: "Treppenlichttaster",
    12: "Zentral Auf/Ab",
    14: "Zentral Auf/Ab mit dynamischer Priorität",
    16: "Fensterkontakt",
    17: "Fensterkontakt (Schließer)",
    18: "Fensterkontakt (Öffner)",
    19: "Zentral Auf/Ab mit statischer Priorität",
    21: "Zentral Aus mit statischer Priorität",
    22: "Zentral Ein mit statischer Priorität",
    23: "Universaltaster ES",
    24: "Universaltaster ER",
    25: "Fenstergriff FTKE",
    26: "Fenstergriff (Schließer)",
    27: "Fenstergriff (Öffner)",
    29: "4-fach-Testtaster",
    30: "4-fach-Taster",
    31: "Fahrbefehl mit Zeitwert vom Controller (GFVS)",
    32: "Dimmwert vom Controller (GFVS)",
    33: "FBH mit Helligkeitsauswertung",
    34: "FBH ohne Helligkeitsauswertung",
    35: "Bewegungsmelder EEP A5-07-01",
    36: "FAH60 mit Tageslichtauswertung",
    37: "FAH60 Dämmerungstaster",
    38: "FAH60 Dämmerungsdimmer",
    39: "FAH60 Rollladensteuerung",
    42: "Wetterstation FWG14MS",
    44: "FIH65B Konstantlichtregelung",
    47: "Zielhelligkeit-Speichertaster",
    48: "Wassersensor EEP A5-30-30",
    49: "Wassersensor RPS",
    50: "Rauchmelder",
    51: "Schaltzustand vom Controller (GFVS)",
    53: "Schlummerfunktion aktivieren",
    54: "FBH mit Helligkeitsauswertung nur beim Einschalten (Warmlicht)",
    60: "Rückmeldung verknüpfter Aktor",
    61: "Temperaturregler mit Sollwert",
    62: "Temperaturregler ohne Schiebeschalter",
    63: "Temperaturregler mit Schiebeschalter Sonne/Mond",
    64: "Temperaturregler EEP A5-10-06 (FTR55D)",
    65: "Temperatur-Sollwert vom Controller (GFVS)",
    66: "Temperaturregler EEP A5-02-05",
    67: "Feuchte-/Temperatursensor EEP A5-04-02",
    68: "Temperatursensor EEP A5-10-02",
    69: "Feuchte-/Temperatursensor FUTH EEP A5-10-12",
    70: "Temperatursensor EEP A5-10-03",
    71: "Temperatursensor EEP A5-10-03 (begrenzter Bereich)",
    77: "Zentral Ein mit Prioritätsverriegelung",
    78: "Zentral Aus mit Prioritätsverriegelung",
    80: "Richtungstaster für Sperre Wendeautomatik",
    82: "Zentral Auf",
    83: "Zentral Ab",
    84: "Zentral Stopp",
    98: "Richtungstaster Sperre Beschattungsszene 1",
    99: "Richtungstaster Sperre Beschattungsszene 2",
    100: "Richtungstaster Sperre Beschattungsszene 3",
    101: "Richtungstaster Sperre Beschattungsszene 4",
    102: "Richtungstaster für Sperre",
    103: "FAH60 Tageslichtauswertung nur Ausschalten",
    104: "FAH60 Tageslichtauswertung nur Einschalten",
    105: "Szenentaster",
    110: "Uhrzeit",
    120: "Fenstergriff EEP A5-14-09",
    121: "Fenstergriff EEP A5-14-0A",
    123: "Priorität aufheben",
    124: "Fenstergriff EEP A5-14-09 als Öffner",
    125: "Fenstergriff EEP A5-14-09 als Schließer",
    126: "Fenstergriff EEP A5-14-0A als Öffner",
    127: "Fenstergriff EEP A5-14-0A als Schließer",
    128: "Fahrbefehl mit Lauf- und Wendezeit",
    137: "Wärmepumpe (Kühlmodus)",
    139: "Feuchte-/Temperatursensor EEP A5-04-03",
    149: "Feuchte-/Temperatursensor FUTH mit Sollwert EEP A5-10-12 (BUTH)",
    156: "Vibrationssensor EEP A5-14-05",
    157: "Helligkeitssensor EEP A5-06-02 (Dämmerungsschalter)",
    158: "Helligkeitssensor EEP A5-06-03 (Dämmerungsschalter)",
    159: "Zentral Aus mit sofortiger Priorität",
    160: "Zentral Ein mit sofortiger Priorität",
    161: "Vibrationssensor EEP A5-14-05 mit Verzögerung",
    162: "Fenstersensor EEP A5-14-01",
    163: "Fenstersensor EEP A5-14-03",
}

KEY_LABELS: dict[int, str] = {
    0: "– (4BS / Controller)",
    5: "Wippe links",
    6: "Wippe rechts",
}


_FSR = ("FSR14_1x", "FSR14_2x", "FSR14_4x", "FSR14M_2x", "F4SR14_LED")
_DIM = ("FUD14", "FUD14_800W", "FSG14_1_10V", "FDG14", "FD2G14")
_HEAT = ("FAE14SSR", "FHK14", "F4HK14")

# Suggested key function when a sender of a given kind is assigned (always editable)
SUGGESTED_FUNCTION: dict[str, dict[str, int]] = {
    **{k: {"rocker": 2, "bus_sender": 51} for k in _FSR},
    **{k: {"rocker": 2, "bus_sender": 32} for k in _DIM},
    **{k: {"bus_sender": 65} for k in _HEAT},
    "FSB14": {"rocker": 2, "bus_sender": 31},
}

# Sensors announcing their EEP in the teach-in telegram
EEP_FUNCTION: dict[str, int] = {
    "A5-02-05": 66, "A5-04-02": 67, "A5-04-03": 139, "A5-06-02": 157, "A5-06-03": 158,
    "A5-07-01": 35, "A5-10-02": 68, "A5-10-03": 70, "A5-10-06": 64, "A5-10-12": 69,
    "A5-14-01": 162, "A5-14-03": 163, "A5-14-05": 156, "A5-14-09": 120, "A5-14-0A": 121,
}


def device_type_info(dt: DeviceType, memory_size: int) -> dict:
    """Serialisable description used by the frontend."""
    groups = groups_for(dt, memory_size)
    first_table_row = min((g.start for g in groups), default=memory_size)
    return {
        "key": dt.key,
        "name": dt.name,
        "description": dt.description,
        "channel_mode": dt.channel_mode,
        "groups": [
            {"number": g.number, "start": g.start, "end": g.end, "label": g.label} for g in groups
        ],
        "settings_rows": [0, first_table_row],
        "row_notes": {str(k): v for k, v in dt.row_notes.items()},
        "base_id_row": dt.base_id_row,
        "suggest": SUGGESTED_FUNCTION.get(dt.key, {}),
    }
