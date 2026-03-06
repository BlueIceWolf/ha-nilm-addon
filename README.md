# HA NILM Add-on Repository

Dieses Repository enthält einen Home Assistant Add-on namens **HA NILM Detector**. Der eigentliche Add-on-Code befindet sich im Unterordner `ha-nilm-detector/`.

## Struktur

```
ha-nilm-addon/           # Repository-Wurzel
├── repository.yaml       # HA Add-on Repository Definition
├── ha-nilm-detector/    # Add-on selbst
│   ├── config.yaml
│   ├── Dockerfile
│   ├── README.md        # Ausführliche Add-on-Dokumentation
│   └── ...
└── tests/               # Entwicklungs- und Testdateien
```

Wenn du das Add-on in Home Assistant installieren möchtest, verwende einfach die Repository-URL:

```
https://github.com/BlueIceWolf/ha-nilm-addon
```

Mehr Informationen findest du im `ha-nilm-detector/README.md`.

## 📦 Was ist hier drin?

- Funktionierendes Home Assistant Add-on zur NILM-Erkennung
- Python-App im Unterordner mit Detektoren, Publishern und State-Engine
- Dockerfile und Build-Konfiguration zur Container-Erzeugung
- Tests und Simulationen zur lokalen Entwicklung
- CI-Workflows (Python-Tests + Docker-Build)
- Beispielkonfiguration und Dokumentation

## 🚧 Geplante Erweiterungen

Ich arbeite weiter an folgenden Punkten:

1. **Erweiterte Erkennung** – zusätzliche Gerätetypen (Waschmaschine, Trockner usw.)
2. **Automatische Sensor-Integration** – direkte Anbindung an MQTT-Stromsensoren
3. **Erweiterte Statistik** – mehr Kennzahlen und Visualisierungen in HA
4. **Web-Oberfläche** – Konfiguration direkt im Browser
5. **Multi‑Kreis-Unterstützung** – mehrere Stromkreise / Phasen

Diese Liste wird wachsen, sobald neue Ideen umgesetzt werden.

Viel Spaß beim Ausprobieren und Mitschrauben!