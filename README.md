# HA NILM Add-on Repository

ACHTUNG Läuft Aktuell Nicht

Dieses Repository enthält einen Home Assistant Add-on namens **HA NILM Detector**. Der eigentliche Add-on-Code befindet sich im Unterordner `ha-nilm-detector/`.

> Wichtiger Hinweis: Der Add-on-Start in Home Assistant ist aktuell noch nicht stabil/funktionsfähig. Bitte derzeit nur zu Testzwecken verwenden.

Wenn du das Add-on in Home Assistant installieren möchtest, verwende einfach die Repository-URL:

```
https://github.com/BlueIceWolf/ha-nilm-addon
```

Mehr Informationen findest du im `ha-nilm-detector/DOCS.md`.

## 📦 Was ist hier drin?

- Funktionierendes Home Assistant Add-on zur NILM-Erkennung
- Python-App im Unterordner mit Detektoren, Publishern und State-Engine
- Dockerfile und Build-Konfiguration zur Container-Erzeugung
- Tests und Simulationen zur lokalen Entwicklung
- CI-Workflows (Python-Tests + Docker-Build)
- Beispielkonfiguration und Dokumentation

## 🚧 Geplante Erweiterungen

Das Projekt entwickelt sich ständig weiter. Auf meinem Radar stehen aktuell:

1. **Erweiterte Erkennung** – weitere Gerätetypen wie Trockner, Mikrowelle, Klima
2. **Automatische Sensor-Integration** – Plug‑and‑play mit MQTT‑Stromsensoren (Shelly, ESPHome …)
3. **Erweiterte Statistik** – zusätzliche Kennzahlen, Verbrauchs‑Heatmaps und Visualisierungen in HA
4. **Web-Oberfläche** – eingebauter Konfigurator und Live‑View im Browser
5. **Multi‑Kreis‑/Phasen‑Support** – mehrere Stromkreise parallel auswerten
6. **KI/LLM‑Unterstützung** – 
   - lokal einsetzbare LLMs zur Erklärbarkeit der Erkennung ("Das ist wahrscheinlich ein Kühlschrank")
   - generative Vorschläge für Automationen basierend auf Nutzungsmustern
   - automatische Etikettierung neuer Geräte via Sprachmodell
   - Forschung in Richtung prädiktiver Wartung und Nutzungsvorhersage
7. **Edge‑AI-Experimente** – kleine neuronale Netze direkt im Container für Rohdaten‑Klassifikation
8. **Community‑Modelle** – teile anonymisierte Signaturen, damit Modelle im Hintergrund besser werden

> Hinweis: KI/LLM-Funktionen sind aktuell Prototypen und erfordern leistungsfähige Hardware oder lokale Modelle (z.B. LLaMA‑ähnliche) – ich teste hier verschiedene Ansätze.

Die Roadmap wächst mit euren Ideen und Pull‑Requests – beteilige dich gerne!

Viel Spaß beim Ausprobieren und Mitschrauben!
