# HA NILM Detector

<p align="center">
   <img src="ha-nilm-detector/logo.png" alt="HA NILM Detector Logo" width="180" />
</p>

Home Assistant Add-on fuer lokale, datenschutzfreundliche NILM-Erkennung
(Non-Intrusive Load Monitoring).

Aktueller Stand: `v0.2.10` (Beta, aktiv weiterentwickelt).

## Features

- 100% lokale Verarbeitung in Home Assistant (keine Cloud, kein externer Dienst).
- Lernt Lastmuster aus `l1/l2/l3` Leistungsphasen und verbessert Zuordnungen ueber Zeit.
- Ingress Web-UI mit Live-Status, Verlauf, Phasenkarten und Musterliste.
- Multi-Phasen-Chart mit ein-/ausblendbaren Linien: `Gesamt`, `L1`, `L2`, `L3`.
- Manuelles Lernen in der UI:
   - `Lernen jetzt ausfuehren`
   - `Bereich markieren` im Verlauf und direkt als Muster speichern
   - `DB leeren (Debug)` fuer Testphasen
- SQLite Persistenz (`/data/nilm.sqlite3`) fuer Messwerte, Muster und robuste Neustarts.

## Schnellstart

1. Home Assistant -> Add-on Store -> Repositories.
2. Repository hinzufuegen:
    `https://github.com/BlueIceWolf/ha-nilm-addon`
3. Add-on **HA NILM Detector** installieren.
4. In den Add-on-Optionen mindestens eine Phase setzen:

```yaml
home_assistant:
   phase_entities:
      l1: sensor.dein_l1_sensor
      l2: ""
      l3: ""
```

5. Add-on starten und via **Open Web UI** pruefen.

Hinweise:
- Es muss mindestens eine Phase (`l1`, `l2` oder `l3`) gesetzt sein.
- `home_assistant.token` kann in der Regel leer bleiben. Das Add-on nutzt automatisch `SUPERVISOR_TOKEN`.

## Aktuelle Minimal-Konfiguration

```yaml
log_level: info
update_interval_seconds: 5
home_assistant:
   url: http://supervisor/core/api
   phase_entities:
      l1: sensor.dein_l1_sensor
      l2: ""
      l3: ""
   token: ""
learning:
   enabled: true
   on_threshold_w: 50.0
   off_threshold_w: 25.0
storage:
   retention_days: 30  patterns_db_path: /config/nilm_patterns.sqlite3```

## Web-UI Workflows

- Status oben rechts zeigt live Lade-/Fehler-/Aktivzustand.
- Im Verlauf kannst du Phasen separat ein-/ausblenden.
- Mit `Bereich markieren` einen Zeitbereich ziehen, Label vergeben und als Muster speichern.
- In `Gelernte Muster` kannst du Labels korrigieren, damit spaetere Erkennung praeziser wird.

## Lokaler Datenschutz

- Daten bleiben auf deinem HA-System.
- Live-Rotationsdaten liegen standardmäßig in `/data/nilm.sqlite3`.
- Geraete-/Musterdaten liegen standardmäßig in `/config/nilm_patterns.sqlite3` (besser fuer Persistenz bei Add-on-Wechsel).
- Kein Upload von Messwerten in externe Services.
- Keine schweren Cloud/Deep-Learning Abhaengigkeiten im Add-on Runtime-Pfad.

## Troubleshooting

- `HTTP 401` beim Start:
   `homeassistant_api: true` im Add-on sowie Token-Verfuegbarkeit pruefen.
- Web-UI ohne Werte:
   `home_assistant.phase_entities.l1/l2/l3` pruefen (mindestens eine numerische Quelle).
- Nach Update keine Aenderung sichtbar:
   Add-on neu starten, Browser Hard-Reload (`Ctrl+F5`) und ggf. Add-on neu installieren.

## Projektstruktur

- Add-on Ordner: `ha-nilm-detector/`
- Manifest: `ha-nilm-detector/config.yaml`
- Add-on Doku: `ha-nilm-detector/DOCS.md`
- Changelog: `ha-nilm-detector/CHANGELOG.md`
- Release Notes: `ha-nilm-detector/RELEASE.md`

## Mitarbeit

Issues und Pull Requests sind willkommen.
