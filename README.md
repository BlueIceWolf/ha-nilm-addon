# HA NILM Detector

<p align="center">
   <img src="ha-nilm-detector/logo.png" alt="HA NILM Detector Logo" width="180" />
</p>

Repository fuer den Home Assistant Add-on **HA NILM Detector**.

`v0.2.2` ist aktuell ein Beta-Stand: stabil genug fuer Tests, mit aktiver Weiterentwicklung.

## Features

- Lernt wiederkehrende Lastmuster aus einem einzigen Leistungssensor.
- Erkennt Lastzyklen und macht Geraete-Vorschlaege (z. B. `fridge_like`).
- Erlaubt Korrekturen in der Web-UI, damit spaetere Zuordnungen besser werden.
- Speichert Messwerte, Erkennungen und Muster robust in SQLite (`/data/nilm.sqlite3`).
- Bietet eine Ingress-Web-UI mit Live-Status, Verlauf und Pattern-Liste.
- MQTT-Ausgabe ist optional (`mqtt.enabled`).

## Schnellstart

1. Home Assistant -> Add-on Store -> Repositories.
2. Repository hinzufuegen:
    `https://github.com/BlueIceWolf/ha-nilm-addon`
3. Add-on **HA NILM Detector** installieren.
4. In den Add-on-Optionen mindestens setzen:

```yaml
power_source: home_assistant_rest
home_assistant:
   sensor_entity_id: sensor.dein_leistungssensor
```

5. Token in der Regel leer lassen:
    der Add-on nutzt automatisch `SUPERVISOR_TOKEN`.
6. Add-on starten und via **Open Web UI** pruefen.

## API Anbindung (wichtig)

- Interne URL: `http://supervisor/core/api/`
- Auth: `Authorization: Bearer <SUPERVISOR_TOKEN>`
- Falls dein Token mit `Bearer ` eingetragen ist, wird das Prefix intern bereinigt.

## Web-UI Statusanzeige

Oben rechts zeigt die UI jetzt live, was gerade passiert:

- `Lade Live-Daten...`
- `Warte auf erste Messwerte vom Sensor...`
- `Aktiv: <Wert> W (aktualisiert: ...)`
- `Warte auf API: ...` bei Fehlern

## Troubleshooting

- `HTTP 401` beim Start:
   `homeassistant_api: true` im Add-on pruefen und sicherstellen, dass `SUPERVISOR_TOKEN` verfuegbar ist.
- Web-UI zeigt keine Werte:
   `home_assistant.sensor_entity_id` pruefen und kontrollieren, ob der Sensor numerische Leistung liefert.
- Nach Updates wirken Aenderungen nicht:
   Add-on neu bauen/reinstallieren, damit das Image aktualisiert wird.

## Projektstruktur

- Add-on Ordner: `ha-nilm-detector/`
- Manifest: `ha-nilm-detector/config.yaml`
- Doku: `ha-nilm-detector/DOCS.md`
- Changelog: `ha-nilm-detector/CHANGELOG.md`
- Release Notes: `ha-nilm-detector/RELEASE.md`

## Mitarbeit

Issues und Pull Requests sind willkommen.
