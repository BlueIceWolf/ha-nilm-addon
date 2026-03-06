# 🏠 HA NILM Detector

[![GitHub Actions](https://github.com/BlueIceWolf/ha-nilm-addon/workflows/Python%20application/badge.svg)](https://github.com/BlueIceWolf/ha-nilm-addon/actions)
[![Docker Build](https://github.com/BlueIceWolf/ha-nilm-addon/workflows/Docker%20Build/badge.svg)](https://github.com/BlueIceWolf/ha-nilm-addon/actions)

**Hey!** 👋 Schön, dass du hier bist. Dieses smarte Add-on für Home Assistant erkennt automatisch deine Haushaltsgeräte anhand ihres Stromverbrauchs. Kein manuelles Konfigurieren mehr - einfach anschließen und los geht's!

## 🚀 Loslegen (3 Minuten)

1. **Repository hinzufügen**: `https://github.com/BlueIceWolf/ha-nilm-addon` in HA Add-on Store
2. **Installieren**: "HA NILM Detector" suchen und installieren
3. **Konfigurieren**: MQTT-Broker angeben
4. **Fertig**: Das System lernt automatisch deine Geräte kennen

## ✨ Warum ist das cool?

### 🤖 **Intelligente Erkennung**
Das Add-on analysiert Strommuster und erkennt Geräte wie:
- 🧊 Kühlschränke (erkennt Kompressor-Zyklen)
- 🧺 Waschmaschinen (verschiedene Programme)
- 🍽️ Geschirrspüler (verschiedene Modi)
- 🔥 Backöfen (kurze Hochlast-Phasen)

**Und es wird besser!** Mit jedem Tag lernt das System dazu.

### 📊 **Was du bekommst**
- **Live-Status**: Siehst sofort, welches Gerät läuft
- **Statistiken**: Laufzeiten, Zyklen, Energieverbrauch pro Tag
- **Home Assistant Integration**: Native Sensoren und Automatisierungen
- **Energie sparen**: Erkenne ineffiziente Geräte

### 🔧 **Technische Vorteile**
- **MQTT-basiert**: Funktioniert mit Shelly, Tasmota, etc.
- **Modular**: Neue Geräte einfach hinzufügen
- **Skalierbar**: Mehrere Stromkreise möglich

## 🗺️ **Roadmap & Entwicklung**

### ✅ **Jetzt verfügbar (v0.1.0)**
- Grundlegende NILM-Algorithmen
- Kühlschrank-Erkennung
- MQTT-Integration
- Home Assistant Add-on

### 🚧 **Nächste Schritte (v0.2.0 - April 2026)**
- **Verbesserte Algorithmen**: Bessere Erkennung für variable Geräte
- **Mehr Geräte**: Waschmaschine, Trockner, Mikrowelle
- **Web-Interface**: Einfache Konfiguration im Browser
- **Energy Dashboard**: Vorgefertigte HA-Dashboards

### 🎯 **Vision (v1.0.0 - Sommer 2026)**
- **Multi-Circuit Support**: Mehrere Stromkreise gleichzeitig
- **Cloud-Sync**: Geräteprofile teilen und verbessern
- **Predictive Analytics**: Vorhersagen für Wartung und Effizienz
- **Mobile App**: Direkte Kontrolle über Smartphone

### 🔮 **Zukunft (2027+)**
- **KI-gestützte Optimierung**: Maschinelles Lernen für perfekte Erkennung
- **Smart Home Integration**: Automatische Steuerung basierend auf Erkennungen
- **Energy Reports**: Monatliche Berichte und Tipps zum Stromsparen

## 🛠️ **Für Entwickler**

### Tests ausführen
```bash
# Abhängigkeiten installieren
pip install -r ../../requirements.txt

# Schnelltest
python ../../quick_test.py

# Umfassende Tests
python ../../test_local.py
```

### Neue Geräte hinzufügen
Schau dir `app/detectors/` an - dort kannst du einfach neue Detektoren hinzufügen!

## 📞 **Support & Community**

- **Issues**: Bug-Reports und Feature-Requests willkommen
- **Discussions**: Teile deine Erfahrungen und Ideen
- **Contributing**: Jeder Pull Request ist wertvoll!

## ⚖️ **Lizenz**

MIT License - frei verwendbar, modifizierbar und teilbar.

---

**Erstellt mit ❤️ für die Home Assistant Community**

*Dieses Add-on nutzt fortschrittliche Algorithmen, um deinen Energieverbrauch transparent zu machen. Spare Strom, schone die Umwelt und hab mehr Kontrolle über dein Zuhause!* 🌱⚡

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