# 🏠 HA NILM Detector

[![GitHub Actions](https://github.com/BlueIceWolf/ha-nilm-addon/workflows/Python%20application/badge.svg)](https://github.com/BlueIceWolf/ha-nilm-addon/actions)
[![Docker Build](https://github.com/BlueIceWolf/ha-nilm-addon/workflows/Docker%20Build/badge.svg)](https://github.com/BlueIceWolf/ha-nilm-addon/actions)

**Willkommen zu deinem intelligenten Energiemonitor!** 🎯

Dieses Home Assistant Add-on verwendet **Non-Intrusive Load Monitoring (NILM)**, um automatisch Haushaltsgeräte anhand ihrer Stromverbrauchsmuster zu erkennen und zu überwachen. Stell dir vor: Du schließt einfach einen Stromsensor an und das System lernt selbständig, welches Gerät wann läuft!

## 🚀 Schnellstart (3 Minuten)

1. **Repository hinzufügen**: Füge `https://github.com/BlueIceWolf/ha-nilm-addon` zu deinem Home Assistant Add-on Store hinzu
2. **Add-on installieren**: Suche nach "HA NILM Detector" und installiere es
3. **Konfigurieren**: Gib deine MQTT-Broker Details ein
4. **Starten**: Das Add-on beginnt automatisch, Gerätemuster zu erlernen

## ✨ Was macht dieses Add-on besonders?

### 🔍 **Intelligente Geräteerkennung**
- **Automatisches Lernen**: Analysiert Stromverbrauchsmuster und erkennt Geräte selbständig
- **Keine manuelle Konfiguration**: Einfach anschließen und loslegen
- **Anpassungsfähig**: Lernt aus realen Nutzungsdaten

### 📊 **Echtzeit-Überwachung**
- **Live-Monitoring**: Kontinuierliche Stromverbrauchsanalyse
- **Sofortige Benachrichtigungen**: Wird ein Gerät erkannt, weißt du sofort Bescheid
- **Historische Daten**: Verfolge Nutzungszeiten und -zyklen

### 🏠 **Nahtlose Home Assistant Integration**
- **MQTT Discovery**: Automatische Entdeckung in Home Assistant
- **Sensoren & Schalter**: Native HA-Entitäten für jedes erkannte Gerät
- **Dashboard-Integration**: Perfekt für Energy Dashboards

### 🔧 **Erweiterbar & Flexibel**
- **Neue Geräte**: Einfach neue Detektoren hinzufügen
- **Verschiedene Sensoren**: Unterstützt MQTT-basierte Stromsensoren
- **Modular**: Leicht anpassbar für spezielle Anforderungen

## 🔌 Unterstützte Geräte

Das System erkennt automatisch:
- 🧊 **Kühlschränke** (100-300W) - Typische Kompressormuster
- 🧺 **Waschmaschinen** (500-2000W) - Variable Lastprofile
- 🍽️ **Geschirrspüler** (1000-3000W) - Hochlast-Geräte
- 🔥 **Backöfen** (1500-4000W) - Kurze Hochlast-Phasen

**Und viele mehr!** Das System lernt kontinuierlich dazu.

## 🏗️ Wie funktioniert's?

```
📡 Stromsensor → 🔍 NILM-Analyse → 🤖 Auto-Erkennung → 📤 MQTT → 🏠 Home Assistant
```

1. **Daten sammeln**: Stromverbrauch wird kontinuierlich gemessen
2. **Muster erkennen**: Algorithmen identifizieren charakteristische Signaturen
3. **Geräte klassifizieren**: Anhand von Leistung, Dauer und Mustern
4. **Benachrichtigen**: Home Assistant erhält Updates via MQTT

## 🛠️ Entwicklung & Tests

### Lokale Tests

```bash
# Abhängigkeiten installieren
pip install -r ../../requirements.txt

# Basis-Test
python ../../test_local.py

# Realistische Simulation
python ../../test_realistic.py

# Adaptive Detektion testen
python ../../test_adaptive_detection.py
```

### Projekt-Struktur

```
ha-nilm-detector/
├── config.yaml          # Add-on Konfiguration
├── Dockerfile          # Container-Definition
├── run.sh             # Start-Script
├── build.yaml         # Build-Einstellungen
├── DOCS.md           # Detaillierte Dokumentation
├── translations/     # UI-Übersetzungen
└── app/              # Python-Anwendung
    ├── main.py       # Haupteinstiegspunkt
    ├── detectors/    # Erkennungs-Algorithmen
    │  ├── auto_detector.py    # 🆕 Automatische Erkennung
    │  ├── fridge.py           # Kühlschrank
    │  ├── inverter.py         # Wechselrichter-Geräte
    │  └── fridge_adaptive.py  # Adaptive Detektion
    ├── publishers/   # MQTT-Integration
    └── utils/        # Hilfsfunktionen
```

## 📈 Statistiken & Insights

Nach der Installation erhältst du:
- **Tägliche Laufzeiten** pro Gerät
- **Zyklus-Zähler** (z.B. wie oft der Kühlschrank angelaufen ist)
- **Leistungsprofile** für jedes erkannte Gerät
- **Verbrauchsanalysen** zur Energieoptimierung

## 🔧 Konfiguration

### MQTT-Broker
Stelle sicher, dass dein MQTT-Broker läuft (empfohlen: Mosquitto Add-on).

### Stromsensoren
Verbinde deine Stromsensoren (z.B. Shelly, Tasmota) und konfiguriere sie für MQTT-Publishing.

### Erweiterte Einstellungen
- **Lernphase**: 24 Stunden für optimale Erkennung
- **Sensibilität**: Anpassbar für verschiedene Gerätetypen
- **Filter**: Ignoriere kleine Lasten unter 50W

## 🤝 Beitragen

Das Projekt ist Open Source! Du kannst:
- Neue Geräte-Detektoren hinzufügen
- Verbesserungen an den Algorithmen vornehmen
- Zusätzliche Sensor-Unterstützung implementieren
- Tests und Dokumentation erweitern

## 📄 Lizenz

MIT License - siehe LICENSE-Datei für Details.

---

**Hinweis**: Dieses Add-on befindet sich in aktiver Entwicklung. Feedback und Verbesserungsvorschläge sind herzlich willkommen! 💡

**Erstellt mit ❤️ für die Home Assistant Community**

### Project Structure

```
ha-nilm-detector/
├── config.yaml          # Add-on configuration
├── Dockerfile          # Container definition
├── run.sh             # Startup script
├── build.yaml         # Build configuration
├── DOCS.md           # Documentation
├── translations/     # UI translations
└── app/              # Python application
    ├── main.py       # Entry point
    ├── detectors/    # Detection algorithms
    ├── publishers/   # MQTT integration
    └── utils/        # Utilities
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License - see LICENSE file for details