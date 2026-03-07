# HA NILM Add-on Repository

Repository fuer den Home Assistant Add-on **HA NILM Detector**.

## Status

`v0.2.2` ist als Beta-Stand gedacht: lauffaehig, mit aktiver Weiterentwicklung.

## Was der Add-on kann

- Lernt wiederkehrende Lastmuster aus einem einzelnen Leistungssensor.
- Macht Geraete-Vorschlaege anhand erkannter Zyklen (z. B. `fridge_like`).
- Erlaubt Korrekturen in der Web-UI, damit spaetere Zuordnungen besser werden.
- Speichert Messwerte, Erkennungen und Muster robust in SQLite.
- Bietet Ingress-Web-UI mit Live-Statistiken und Pattern-Ansicht.
- Verwendet MQTT + Home Assistant Discovery fuer Entitaeten.

## Schnellstart in Home Assistant

1. Add-on-Repository hinzufuegen:
   `https://github.com/BlueIceWolf/ha-nilm-addon`
2. Add-on **HA NILM Detector** installieren.
3. In den Add-on-Optionen setzen:
   `power_source: home_assistant_rest`
4. Optional `home_assistant.power_entity_id` leer lassen, dann versucht das Add-on Auto-Discovery.
5. `home_assistant.token` in der Regel leer lassen (Supervisor-Token wird automatisch genutzt).
6. Add-on starten und ueber **Open Web UI** Statistiken und Muster ansehen.

## Wichtige Dateien

- Add-on-Ordner: `ha-nilm-detector/`
- Add-on Manifest: `ha-nilm-detector/config.yaml`
- Detaillierte Dokumentation: `ha-nilm-detector/DOCS.md`
- Changelog: `ha-nilm-detector/CHANGELOG.md`
- Release-Notizen: `ha-nilm-detector/RELEASE.md`
- Beispieloptionen: `example_options.json`

## Hinweise

- Fuer große Lastspruenge und gute Erkennung ist ein stabiler Leistungssensor wichtig.
- Nach Updates in der Regel Add-on neu bauen/reinstallieren, damit alle Image-Aenderungen aktiv sind.

## Mitarbeit

Issues und Pull Requests sind willkommen.
