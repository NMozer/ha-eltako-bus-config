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
| Mehrere FAM14 / Projekte | Reiter **Anlagen**: eine Anlage je FAM14, PCT14-Export importieren, Projektdatei exportieren und importieren |
| Konfigurieren am Verteiler | **Laptop-Brücke**: Laptop per USB an den FAM14, Home Assistant im Browser öffnen, verbinden |

Die Gerätesteuerung (Licht, Rollläden, Heizung …) übernimmt weiterhin eine Steuer-Integration, zum Beispiel die [Eltako-Integration von grimmpp](https://github.com/grimmpp/home-assistant-eltako). Der Bus-Konfigurator ändert nur die Konfiguration der Geräte und ergänzt sie.

## Anschluss

Die Integration braucht eine serielle Verbindung zum Bus. Möglich sind:

* **FAM14 per Mini-USB (empfohlen).** Über diesen Weg arbeitet auch PCT14, und eo_man liest den Gerätespeicher ebenfalls nur so aus.
* **FGW14-USB (experimentell).** Eltako dokumentiert nicht, ob der FGW14-USB in Pos. 6 Speicher-Lese- und Schreibbefehle (ORG F0/F1/F2/F4) weiterreicht. Unter **Verbindung → Verbindung testen** siehst du, ob es klappt.
* **Direkter RS485-Adapter** am Bus (9600 Baud).

Eine Schnittstelle kann immer nur ein Programm nutzen. Nutzt deine Steuer-Integration bereits ein Gateway (z. B. FGW14-USB) oder einen Funkstick, schließe für den Bus-Konfigurator den FAM14 zusätzlich per Mini-USB an:

```
HA-Rechner ──USB──► Gateway der Steuer-Integration ──┐
           └─USB──► FAM14 (Mini-USB) ────────────────┴── RS485-Bus ── Aktoren
```

PCT14 und diese Integration dürfen nicht gleichzeitig auf den FAM14 zugreifen.

**Ohne festen Anschluss:** Bei der Einrichtung „Nur Laptop-Brücke“ wählen. Konfiguriert wird dann über einen Laptop am jeweiligen FAM14 (siehe unten).

## Mehrere FAM14 im Haus (Anlagen)

Jeder FAM14 bildet eine **Anlage**, erkannt an seiner Basis-ID – etwa je eine in der Unterverteilung und im Heizungsverteiler. Alle Anlagen liegen in **einer** Integration: Sendernamen und die Vergabe von Home-Assistant-Sender-IDs gelten hausweit.

* **Anlage wählen:** Auswahlfeld oben im Panel. Eine Anlage, die gerade nicht am Bus hängt, zeigt ihren gespeicherten Stand; Änderungen werden **vorgemerkt** und beim nächsten Anschluss geschrieben.
* **Schutz:** Vor jedem Lesen und Schreiben prüft die Integration die Basis-ID des angeschlossenen FAM14. Gehört er zu einer anderen Anlage, wird nichts geschrieben.
* **Neue Anlagen** entstehen beim Bus-Scan, beim Verbinden eines Laptops oder per PCT14-Import.
* **Projektdatei:** *Anlagen → Projekt exportieren* speichert alle Anlagen, Namen, Sender und vorgemerkten Änderungen in einer JSON-Datei; *Projekt importieren* führt sie wieder zusammen.

### Laptop-Brücke

Für Verteiler ohne festen Anschluss an den HA-Rechner:

1. Laptop per Mini-USB an den FAM14 stecken und Home Assistant **über HTTPS** im Browser öffnen (Chrome, Edge, Opera oder Firefox ab 151).
2. *Anlagen → Laptop verbinden* und den USB-Anschluss des FAM14 auswählen.
3. Die Integration liest die Basis-ID, öffnet die passende Anlage (oder legt sie an) und arbeitet wie mit einem fest angeschlossenen FAM14: scannen, lauschen, zuordnen, schreiben.

Der Browser reicht die Daten nur durch – Sicherungen, Namen und Zuordnungen landen direkt in Home Assistant. Web Serial ist nur auf HTTPS-Seiten verfügbar; `http://…:8123` genügt nicht.

### PCT14-Export importieren

*Anlagen → PCT14-Export importieren* legt aus einer PCT14-XML-Datei eine Anlage an (oder aktualisiert die mit gleicher Basis-ID): Geräte, Kanal- und Gerätebeschreibungen, Sendernamen sowie die Liste der Busadressen, deren Zustand der FAM14 per Funk meldet. Ist die Anlage schon vom Bus gelesen, bleibt der Busstand maßgeblich und es werden nur Namen ergänzt.

Die ID-Tabelle wird für den **FSB14** übernommen; die Zuordnung der PCT14-Einträge zu Speicherzeilen ist dort an echter Hardware geprüft. Bei anderen Gerätetypen werden die Einträge vorerst nur angezeigt. Einstellungszeilen (Laufzeiten usw.) enthält ein PCT14-Export nicht.

### Home Assistant per Funkstick

Statt eines USB-Gateways an jedem FAM14 kann Home Assistant alle Anlagen über **einen** Funkstick erreichen (z. B. FAM-USB oder USB300):

* *Anlagen → HA-Sender eintragen:* Basis-ID des Sticks eingeben und Kanäle wählen. Jeder Kanal bekommt die nächste freie Sender-ID (Basis-ID + 1, 2, 3 …) und wird mit der passenden Controller-Funktion in die ID-Tabelle eingetragen – ohne Einlernen am Drehschalter. Die Einträge werden je Anlage vorgemerkt und beim Anschluss geschrieben.
* Die **Rückmelde-IDs** jeder Anlage (Basis-ID des FAM14 + Busadresse) stehen unter *Anlagen*; sie braucht die Steuer-Integration für die Zustände.
* Ob der FAM14 Rückmeldungen per Funk sendet, hängt von seiner Betriebsart ab (Drehschalter, siehe Anleitung). Reichweite und Messwerte (z. B. Zähler) vor dem Umstieg prüfen.

### Funktest

*Verbindung → Funktest* legt ein Lerntelegramm (EEP A5-38-08) oder einen Ein-/Aus-Befehl mit frei wählbarer Sender-ID auf den Bus. Damit lässt sich prüfen, ob der FAM14 solche Telegramme in die Luft sendet – etwa mit einem Funkaktor im Lernmodus oder einem mithörenden Funkstick. Der Bus wird dafür nicht gesperrt.

## Installation

**Marketplace (ab Home Assistant 2026.11, empfohlen – mit automatischen Updates):**
1. *Einstellungen → Marketplace* öffnen → **Über Link hinzufügen** („Add from link“).
2. `https://github.com/NMozer/ha-eltako-bus-config` einfügen, Typ **Integration** (falls gefragt). Beim ersten Mal verlangt Home Assistant eine Verbindung zu GitHub (Code auf github.com eingeben).
3. „Bus-Konfigurator für Eltako Baureihe 14“ installieren und – wenn eine Reparaturmeldung dazu auffordert – Home Assistant neu starten.

Neue Versionen werden danach als Update angezeigt.

**Ältere Home-Assistant-Versionen mit HACS:** HACS → ⋮ → **Benutzerdefinierte Repositories** → obige Adresse, Typ **Integration**.

**Manuell:** Den Ordner `custom_components/eltako_bus_config` nach `<config>/custom_components/eltako_bus_config` kopieren und Home Assistant neu starten.

Danach: *Einstellungen → Geräte & Dienste → Integration hinzufügen → „Bus-Konfigurator für Eltako Baureihe 14“*. Wähle die Schnittstelle (am besten den Pfad unter `/dev/serial/by-id/…`) und als Gateway „FAM14“ – oder „Nur Laptop-Brücke“ ohne festen Anschluss. Das Panel erscheint nur für Administratoren in der Sidebar.

Voraussetzung: Home Assistant 2025.1 oder neuer.

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

**Kanäle benennen:** Im Lernmodus trägst du den Namen direkt in der Kanal-Kachel ein (z. B. „Wohnzimmer links“); ist dort ein benannter Home-Assistant-Sender eingelernt, bietet die Kachel dessen Namen zur Übernahme an. Die Namen erscheinen auch in der ID-Tabelle und bei „Eingelernt“.

**Schnellwahl:** Im Zuordnen-Dialog stehen die wichtigsten Funktionen als Knöpfe bereit – beim FSB14 z. B. Richtungstaster und Zentral Auf/Ab für Wippen, Universaltaster sowie Zentral Auf, Ab und Stopp für Einzeltasten; bei Schalt- und Dimmaktoren Zentral Ein/Aus.

Wandtaster lassen sich **als Wippe** (Richtungstaster, Taste 5/6) oder **als Einzeltasten** zuordnen. Speicherwerte der Einzeltasten: 1 = links oben, 2 = links unten, 3 = rechts oben, 4 = rechts unten (1 und 3 an realer Hardware bestätigt, 2 und 4 abgeleitet).

## Typischer Ablauf

1. **Sicherungen → Neue Sicherung.** Damit sicherst du den Ist-Stand des ganzen Busses.
2. **Geräte → Bus scannen.** Der Scan prüft alle 254 Adressen und dauert je nach Busgröße 1–3 Minuten.
3. Gerät auswählen → **ID-Tabelle** → „+ Eintrag“ oder „Bearbeiten“.
   * Für einen **Home-Assistant-Sender** (aus deiner Steuer-Integration) trägst du dessen Sender-ID ein. Das ist meist Basis-ID + n; das Panel markiert solche IDs. Als Funktion wählst du die passende „… vom Controller (GFVS)“-Funktion: 51 für FSR14, 31 für FSB14, 32 für FUD14, 65 für FHK14/FAE14.
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
* Getestet gegen einen simulierten Bus, byte-genau gegen die Referenzbibliothek `eltako14bus` und an realer Hardware (Scan, Lesen, Schreiben mit Kontrolle, Lauschen). Lege vor dem ersten Schreiben trotzdem eine Sicherung an.
* Lauschen funktioniert nur bei freiem Bus: Mit gesperrtem Bus gibt der FAM14 keine Funktelegramme an den USB-Port weiter.
* PCT14-Import: ID-Tabellen werden bisher nur beim FSB14 übernommen (an Hardware geprüft). Für weitere Gerätetypen genügt je ein PCT14-Export plus Bus-Scan derselben Anlage zum Abgleich.
* Ob der FAM14 Telegramme von Home Assistant (Funktest, Funkstick-Betrieb) in die Luft sendet bzw. Rückmeldungen funkt, hängt von seiner Betriebsart ab und ist vor dem Umstieg an der eigenen Anlage zu prüfen.

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
