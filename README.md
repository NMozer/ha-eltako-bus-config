<img src="custom_components/eltako_bus_config/brand/logo.png" alt="Bus-Konfigurator – Baureihe 14" height="96">

# Bus-Konfigurator für Eltako Baureihe 14 (Home Assistant)

[![Marketplace / HACS Custom](https://img.shields.io/badge/Marketplace%20%2F%20HACS-Custom-41BDF5.svg)](https://github.com/NMozer/ha-eltako-bus-config)

Eine Home-Assistant-Integration zum Konfigurieren von Eltako-Reiheneinbaugeräten der Baureihe 14 – eine Alternative zur Windows-Software PCT14 für deren Kernfunktionen. Bedient wird sie über ein eigenes Seitenpanel („Eltako Bus“ in der Sidebar):

| Aufgabe (wie in PCT14) | Im Bus-Konfigurator |
|---|---|
| Geräteliste aktualisieren | **Bus scannen** / **Nur Liste** |
| Gerätespeicher auslesen | automatisch beim Scan oder **Neu auslesen** je Gerät |
| ID-Tabelle bearbeiten (Taster/Sensoren eintragen) | Reiter **ID-Tabelle**: Sender-ID, Taste, Funktion (alle PCT14-Funktionsnummern mit Klartext), Kanäle, Wert |
| ID-Erkennung (auf den Bus hören) | Reiter **Einlernen**: Lauschen über den FAM14, erkannte Taster bleiben gespeichert und lassen sich benennen; Wippe links/rechts wird erkannt |
| Sender Kanälen zuordnen | Reiter **Einlernen**: Taster-Chip per **Drag & Drop** auf einen Kanal ziehen oder per **Dropdown** wählen – Funktion wird vorgeschlagen, alle Änderungen auf einmal schreiben |
| Geräteeinstellungen | Reiter **Einstellungen** (Zeilen 0–7, bekannte Bedeutungen annotiert) und **Rohspeicher** |
| Gerät identifizieren | **Blinken** |
| Projekt sichern / zurückspielen | Reiter **Sicherungen**: anlegen, herunterladen (JSON), importieren, vergleichen, wiederherstellen |

Die Gerätesteuerung (Licht, Rollläden, Heizung …) bleibt bei der [Eltako-Integration von grimmpp](https://github.com/grimmpp/home-assistant-eltako). Beide Integrationen ergänzen sich.

## Hardware

```
HA-Rechner ──USB──► FGW14-USB ──┐
           └─USB──► FAM14 ──────┴── RS485-Bus ── FSR14, FSB14, FUD14 …
                    (Mini-USB)
```

* **FAM14 per Mini-USB (empfohlen).** Über diesen Weg arbeitet auch PCT14, und eo_man liest den Gerätespeicher ebenfalls nur so aus. Schließe also zusätzlich zum FGW14-USB den FAM14 per Mini-USB an den HA-Rechner an. Die grimmpp-Integration nutzt weiter den FGW14-USB, diese Integration den FAM14. So belegen sie unterschiedliche Schnittstellen.
* **FGW14-USB (experimentell).** Eltako dokumentiert nicht, ob der FGW14-USB in Pos. 6 Speicher-Lese- und Schreibbefehle (ORG F0/F1/F2/F4) weiterreicht. Unter **Verbindung → Verbindung testen** siehst du, ob es bei dir klappt. Beide Integrationen dürfen sich nicht dieselbe Schnittstelle teilen.
* **Direkter RS485-Adapter** am Bus (9600 Baud) wird ebenfalls angeboten.

PCT14 und diese Integration dürfen nicht gleichzeitig auf den FAM14 zugreifen.

## Installation

**Marketplace (ab Home Assistant 2026.11, empfohlen – mit automatischen Updates):**
1. *Einstellungen → Marketplace* öffnen → **Über Link hinzufügen** („Add from link“).
2. `https://github.com/NMozer/ha-eltako-bus-config` einfügen, Typ **Integration** (falls gefragt). Beim ersten Mal verlangt Home Assistant eine Verbindung zu GitHub (Code auf github.com eingeben).
3. „Bus-Konfigurator für Eltako Baureihe 14“ installieren und – wenn eine Reparaturmeldung dazu auffordert – Home Assistant neu starten.

Neue Versionen werden danach als Update angezeigt.

**Ältere Home-Assistant-Versionen mit HACS:** HACS → ⋮ → **Benutzerdefinierte Repositories** → obige Adresse, Typ **Integration**.

**Manuell:** Den Ordner `custom_components/eltako_bus_config` nach `<config>/custom_components/eltako_bus_config` kopieren und Home Assistant neu starten.

Danach: *Einstellungen → Geräte & Dienste → Integration hinzufügen → „Bus-Konfigurator für Eltako Baureihe 14“*. Wähle die Schnittstelle (am besten den Pfad unter `/dev/serial/by-id/…`) und als Gateway „FAM14“. Das Panel erscheint nur für Administratoren in der Sidebar.

Voraussetzung: Home Assistant 2025.1 oder neuer.

**Umstieg vom früheren Namen „Eltako PCT“ (`eltako_pct`):** Neue Integration einrichten, dann die alte unter *Geräte & Dienste* löschen und den Ordner `custom_components/eltako_pct` entfernen. Sicherungen und vergebene Sendernamen übernimmt die neue Integration beim ersten Start automatisch.

## Lernmodus (Einlernen)

1. **Einlernen → Lauschen starten.** Der Bus bleibt dabei frei – der FAM14 gibt Funktelegramme nur im normalen Betrieb an seinen USB-Port weiter (bei gesperrtem Bus kommt nichts an).
2. Taster nacheinander drücken – jeder erscheint links als Karte (aufleuchtend), mit erkannter Wippe. Namen direkt in der Karte eintragen.
3. Den Chip „Wippe links/rechts“ auf einen Kanal rechts ziehen (oder im Kanal „+ Sender zuordnen…“ wählen). Ist derselbe Taster auf diesem Gerät schon eingetragen, wird nur der Kanal ergänzt – wie in PCT14.
4. **Auf Geräte schreiben** – jedes Gerät wird gesichert, geschrieben und geprüft.

Sender aus den ID-Tabellen werden automatisch übernommen, sodass auch bereits eingelernte Taster benannt werden können.

### DALI-Gateway (FDG14 / FD2G14)

Im Lernmodus bekommt jede **DALI-Gruppe** (0–15) eine eigene, benennbare Kachel, dazu eine Kachel **Alle Gruppen (Broadcast)**. Ungenutzte Gruppen sind ausgeblendet („Alle 16 DALI-Gruppen zeigen“). Unter *Geräte → FDG14 → Lichtszenen* lassen sich die Dimmwerte der vier Lichtszenen je Gruppe einstellen (0–100 %, leer = Gruppe bleibt unverändert). Speicherlayout laut Referenzbibliothek (`eltako14bus`): Gruppenbyte 0–15, 16 = Broadcast; Szenen in den Zeilen 2–9. **An echter DALI-Hardware noch nicht geprüft.**

### Sendertypen und Einzeltasten

Jeder Sender bekommt einen Typ (Wandtaster, Fenstergriff, Kontakt, Bewegungsmelder, Helligkeits-, Temperatur-/Feuchtesensor, Raumregler, Wetterstation, Wasser-/Rauchmelder, Controller/Home Assistant). Erkannt wird er – in dieser Rangfolge – von dir gewählt › aus dem Lerntelegramm (EEP) › aus der Funktion im Gerätespeicher › aus dem Telegrammmuster. Beim Zuordnen schlägt die Integration nur passende Funktionen vor („Alle Funktionen“ bleibt wählbar) und legt den Eintrag in der richtigen Funktionsgruppe ab (z. B. Raumregler/Sensor/Kontakt beim FHK14).

**Kanäle benennen:** Im Lernmodus trägst du den Namen direkt in der Kanal-Kachel ein (z. B. „Kinderzimmer West“); ist dort ein benannter Home-Assistant-Sender eingelernt, bietet die Kachel dessen Namen zur Übernahme an. Die Namen erscheinen auch in der ID-Tabelle und bei „Eingelernt“.

**Schnellwahl:** Im Zuordnen-Dialog stehen die wichtigsten Funktionen als Knöpfe bereit – beim FSB14 z. B. Richtungstaster und Zentral Auf/Ab für Wippen, Universaltaster sowie Zentral Auf, Ab und Stopp für Einzeltasten; bei Schalt- und Dimmaktoren Zentral Ein/Aus.

Wandtaster lassen sich **als Wippe** (Richtungstaster, Taste 5/6) oder **als Einzeltasten** zuordnen. Speicherwerte der Einzeltasten: 1 = links oben, 2 = links unten, 3 = rechts oben, 4 = rechts unten (1 und 3 an einem FSB14 gemessen).

## Typischer Ablauf

1. **Sicherungen → Neue Sicherung.** Damit sicherst du den Ist-Stand des ganzen Busses.
2. **Geräte → Bus scannen.** Der Scan prüft alle 254 Adressen und dauert je nach Busgröße 1–3 Minuten.
3. Gerät auswählen → **ID-Tabelle** → „+ Eintrag“ oder „Bearbeiten“.
   * Für einen **Home-Assistant-Sender** (grimmpp) trägst du dessen Sender-ID ein. Das ist meist Basis-ID + n; das Panel markiert solche IDs. Als Funktion wählst du die passende „… vom Controller (GFVS)“-Funktion: 51 für FSR14, 31 für FSB14, 32 für FUD14, 65 für FHK14/FAE14.
   * Für einen **Wandtaster** klickst du auf „Sender erfassen“, drückst den Taster und übernimmst die ID – oder du nutzt gleich den **Lernmodus**.
4. Unten auf **Auf Gerät schreiben**. Die Integration
   * sperrt den Bus,
   * liest den kompletten Gerätespeicher und legt eine **automatische Sicherung** an,
   * schreibt nur die geänderten Zeilen und liest jede Zeile zur **Kontrolle** zurück.

## Sicherungsformat

`<config>/eltako_bus_config/backups/*.json`, zum Beispiel:

```json
{
  "format": "eltako_bus_config_backup", "version": 1, "name": "Vor Umbau Küche",
  "base_id": "FF-A1-B2-80",
  "devices": [{"address": 1, "size": 4, "memory_size": 128, "model": "04013100",
               "type_key": "FSR14_4x", "memory": ["0000…", "…"]}]
}
```

Beim Wiederherstellen prüft die Integration für jedes Gerät, ob Adresse, Gerätetyp und Speichergröße noch passen. Geschrieben werden nur abweichende Zeilen. Ein ausgetauschtes Gerät gleichen Typs an derselben Adresse lässt sich so vollständig neu bespielen.

## Grenzen (ehrlich)

* **Geräteeinstellungen** (Zeilen 0–7 wie Verzögerungen oder Betriebsarten) sind herstellerspezifisch und nicht öffentlich dokumentiert. Sie erscheinen als Hex-Zeilen; nur die bekannten Felder sind beschriftet. Für Änderungen dort ist eine PCT14-Sicherung als Vorlage am sichersten.
* **Busadressen vergeben** (Drehschalter Pos. 10 / „Adresse vergeben“) ist noch nicht eingebaut.
* Unterstützte Gerätetypen mit ID-Tabelle: FSR14-1x/2x/4x, FSR14M-2x, F4SR14-LED, FSB14, FUD14, FUD14/800W, FSG14/1-10V, FDG14, FD2G14, FAE14SSR, FHK14, F4HK14, FMZ14, FTD14. Andere Geräte (FSU14, FMSR14, F3Z14D, FWZ14 …) werden erkannt und als Rohspeicher angezeigt.
* Getestet gegen einen simulierten Bus, byte-genau gegen die Referenzbibliothek `eltako14bus` und an einer echten Anlage (FAM14, 2× FSB14, FWZ14-65A). Lege vor dem ersten Schreiben trotzdem eine Sicherung an.
* Lauschen funktioniert nur bei freiem Bus: Mit gesperrtem Bus gibt der FAM14 keine Funktelegramme an den USB-Port weiter.

## Entwicklung

```bash
pip install pytest-homeassistant-custom-component pyserial-asyncio-fast
pip install eltako14bus   # optional: Byte-Vergleich mit der Referenzimplementierung
pytest
```

`tests/simbus.py` simuliert FAM14 und Aktoren (Bussperre, Discovery, Speicher lesen und schreiben, Funktelegramme, Echo).

## Dank

Das Busprotokoll und die Speicherlayouts stammen aus dem Reverse Engineering von [eltako14bus](https://github.com/grimmpp/eltako14bus) (Christian Amsüss, Energy Harvesting Solutions, Philipp Grimm). Ergänzt wurden sie durch [eo_man](https://github.com/grimmpp/enocean-device-manager). Diese Integration enthält keinen Code aus diesen Projekten, sondern eine eigene asynchrone Implementierung. „Eltako“ und „PCT14“ sind Marken der Eltako GmbH und werden hier nur verwendet, um anzugeben, mit welchen Geräten diese Software zusammenarbeitet. Dieses Projekt ist kein Produkt von Eltako und steht in keiner Verbindung zur Eltako GmbH.

## Logo

Eigenes Motiv (Reiheneinbaugeräte auf der Hutschiene mit Drehschalter, Funk und Busleitung); es verwendet keine Marken, Logos oder Farben von Eltako. Quelldateien in `docs/brand-src/`. Home Assistant zeigt es ab Version 2026.3 automatisch an (`custom_components/eltako_bus_config/brand/`).

## Lizenz

MIT – siehe [LICENSE](LICENSE).
