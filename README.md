# HA NILM Detector – Home Assistant Add-on

Non-Intrusive Load Monitoring (NILM) für Home Assistant: Erkennt Haushaltsgeräte automatisch anhand von Stromverbrauchsmustern.

## Überblick

Das **HA NILM Detector** Add-on analysiert Leistungswerte aus Home Assistant und erkennt automatisch, welche Geräte gerade aktiv sind. Ohne zusätzliche Smart-Meter oder Einzelmessungen pro Gerät – auch „Non-Intrusive Load Monitoring" genannt.

### MVP-Features (Version 0.1.0)

- ✅ **Kühlschrank-Erkennung** auf einzelner Phase (z. B. L1)
- ✅ **Regelbasierte Mustererkennung** (robust und nachvollziehbar)
- ✅ **MQTT Discovery** für direkte Integration in Home Assistant
- ✅ **Automatische Sensoren**:
  - Binary Sensor: Gerät läuft / läuft nicht
  - Power Sensor: erkannte aktuelle Leistung
  - Daily Runtime: Laufzeit heute
  - Daily Cycles: Anzahl Zyklen heute
- ✅ **Modulare Architektur** – einfache Erweiterung für weitere Geräte
- ✅ **Sauberes Logging** für Debugging

### Geplante Features (zukünftig)

- Lernmodus für automatische Schwellwerte
- Weitere Detektoren (Waschmaschine, Geschirrspüler, Kaffeemaschine, Wasserkocher)
- JSON/SQLite Speicherung von Profilen
- InfluxDB/CSV Export
- Optional: NILMTK-Backend
- Erkennung aus Gesamtlast statt einzelner Phase

## Installation

### Voraussetzungen

- Home Assistant mit funktionierendem MQTT Broker
- Zugang zu Stromverbrauchsdaten (z. B. über Stromzähler mit Modbus/MQTT Export)

### Setup

1. **Repository hinzufügen**: Fügen Sie dieses Repository zu den Home Assistant Add-on Repositories hinzu
2. **Add-on installieren**: Wählen Sie „HA NILM Detector" und klicken Sie auf „Installieren"
3. **Konfigurieren**: Passen Sie die Optionen an (siehe Konfiguration)
4. **Starten**: Klicken Sie auf „Starten"

## Konfiguration

### Basis-Konfiguration

```yaml
debug: false                          # Debug-Logs aktivieren
update_interval_seconds: 5            # Messwert-Update Intervall

mqtt:
  broker: "homeassistant.local"       # MQTT Broker Adresse
  port: 1883                          # MQTT Port
  username: "mqtt_user"               # Optional
  password: "mqtt_password"           # Optional
  topic_prefix: "ha-nilm/"            # MQTT Topic Prefix für Status
  discovery_prefix: "homeassistant"   # MQTT Discovery Prefix
  discovery_enabled: true             # MQTT Discovery aktivieren

home_assistant:
  entity_id_prefix: "nilm"            # HA Entity ID Präfix

devices:
  kitchen_fridge:                     # Eindeutige Geräte-ID
    enabled: true
    power_min_w: 10                   # Minimale Leistung (Ausschaltpunkt)
    power_max_w: 500                  # Maximale Leistung (Sicherheit)
    min_runtime_seconds: 30           # Minimale Laufzeit pro Zyklus
    min_pause_seconds: 60             # Minimale Pause zwischen Zyklen
    startup_duration_seconds: 5       # Dauer der Einschaltspiize
```

### Geräte-spezifische Parameter

#### Kühlschrank (fridge)

- **power_min_w**: 10–20 W (Schwellwert zum Erkennen von Ein/Aus)
- **power_max_w**: 300–500 W (Maximum Normal, höher = Fehler)
- **min_runtime_seconds**: 30–300 s (typischerweise 60–120 s)
- **min_pause_seconds**: 60–3600 s (typisch 5–30 min)

**Beispiel für Fritzbox-Kühlschrank**:

```yaml
devices:
  kitchen_fridge:
    enabled: true
    power_min_w: 15
    power_max_w: 400
    min_runtime_seconds: 45
    min_pause_seconds: 120
    startup_duration_seconds: 5
```

## MQTT Discovery in Home Assistant

Das Add-on publiziert automatisch MQTT Discovery Messages für alle aktivierten Geräte. Die Sensoren erscheinen dann automatisch in Home Assistant:

- `binary_sensor.nilm_kitchen_fridge_state` – Zustand (On/Off)
- `sensor.nilm_kitchen_fridge_power` – Aktuelle Leistung [W]
- `sensor.nilm_kitchen_fridge_daily_runtime` – Laufzeit heute [s]
- `sensor.nilm_kitchen_fridge_daily_cycles` – Zyklen heute

### Raw MQTT Topics

```
ha-nilm/kitchen_fridge/state        # "ON" oder "OFF"
ha-nilm/kitchen_fridge/power        # "123.5" (Watt)
ha-nilm/kitchen_fridge/daily_runtime  # "3600.0" (Sekunden)
ha-nilm/kitchen_fridge/daily_cycles   # "24" (Anzahl Zyklen)
ha-nilm/kitchen_fridge/last_start   # ISO-8601 Timestamp
```

## Stromverbrauch-Eingabe

### MVP: Mock-Datenquelle (zum Testen)

Die aktuelle Version nutzt einen Mock-Generator. Für Tests können Sie die Leistung simulieren.

### Spätere Versionen: Integration mit Home Assistant

- **REST API**: Liest Stromzähler-Entitäten direkt
- **MQTT**: Abonniert MQTT-Topics von Stromzählern
- **Modbus RTU/TCP**: Direkte Kommunikation mit intelligenten Zählern

## Architektur

```
app/
├── main.py                # Einstiegspunkt, Hauptloop
├── config.py              # Konfigurationsverwaltung
├── models.py              # Datenklassen (PowerReading, DeviceState, etc.)
├── state_engine.py        # Zustandsverwaltung mit Hysterese
├── collector/
│   └── source.py          # Abstraktionen für Datenquellen
├── detectors/
│   └── fridge.py          # Kühlschrank-Mustererkennung
├── publishers/
│   └── mqtt.py            # MQTT Publisher mit Discovery
└── utils/
    └── logging.py         # Logging-Utilities
```

### Design-Prinzipien

1. **Modular**: Neue Detektoren/Quellen sind leicht hinzufügbar
2. **Regelbasiert**: Transparente, nachvollziehbare Logik
3. **Robust**: Hysterese und Mindestlaufzeiten  verhindern Flackern
4. **Erweiterbar**: ML/NILMTK können später als optionales Backend ergänzt werden

## Debugging

### Logs anschauen

Im Home Assistant: **Einstellungen → Allgemein → Protokolle → HA NILM Detector**

Oder im Terminal:

```bash
docker logs addon_ha-nilm-detector
```

### Debug-Modus aktivieren

In den Add-on Optionen:

```yaml
debug: true
```

Dies erzeugt detaillierte Logs für jeden Erkennungsschritt.

### Fehlerbehandlung

| Fehler | Ursache | Lösung |
|--------|--------|--------|
| `MQTT connection failed` | Broker nicht erreichbar | MQTT-Config/Broker prüfen |
| `No power readings received` | Datenquelle nicht verbunden | Datenquelle konfigurieren (später) |
| `Fridge stays on / off` | Schwellwerte nicht kalibriert | `power_min_w`, `power_max_w` anpassen |

## Weiterentwicklung

Geplante Roadmap:

1. **v0.2.0**: Weitere Geräte-Detektoren (Waschmaschine, Geschirrspüler)
2. **v0.3.0**: Home Assistant REST API als Datenquelle
3. **v0.4.0**: Lernmodus für automatische Kalibrierung
4. **v0.5.0**: Speicherung von Profilen in JSON
5. **v1.0.0**: Optional NILMTK Integration

## Support & Beiträge

Fragen, Bugs oder Verbesserungsvorschläge? Bitte öffnen Sie ein Issue!

## Lizenz

MIT License

---

**Version**: 0.1.0  
**Autor**: HA NILM Team  
**Repository**: https://github.com/...  
**Dokumentation**: Siehe [DOCS.md](DOCS.md)
