# 🗺️ HA NILM Detector - Roadmap

Status der Features und geplante Entwicklung für das experimentelle NILM-Projekt.

---

## ✅ Implemented & Working

**Stabile Features die zuverlässig funktionieren:**

### Core NILM
- ✅ Live Power Reading (REST API Integration)
- ✅ Adaptive Cycle Detection mit Noise-Filtering
- ✅ Feature Extraction (peak, duration, rise/fall rate)
- ✅ Pattern Matching mit Multi-Dimensional Distance
- ✅ EMA-basiertes Pattern Learning/Updating

### Phase Detection
- ✅ Multi-Phase Power Distribution Ratio
- ✅ 3-Phase vs. Single-Phase Classifications
- ✅ Per-Phase Pattern Learning (v0.6.0)
- ✅ Phase-based Pattern Filtering

### Web UI
- ✅ Live Power Chart mit Canvas-Rendering
- ✅ Pattern-Visualisierung (Power Curves)
- ✅ Dark Mode
- ✅ Pattern-Tabelle mit Sorting
- ✅ Manual Pattern Creation via Chart-Bereich-Markierung
- ✅ Pattern Labeling & Description

### Data Storage
- ✅ SQLite Pattern Database
- ✅ SQLite Reading Log
- ✅ Pattern Persistence
- ✅ Temporal Patterns (intervals, hour distribution)

---

## ⚠️ Partially Working / Experimental

**Features die funktionieren, aber nicht optimal:**

### Pattern Learning
- ⚠️ **Multi-Modal Detection** - Unterscheidet Betriebsmodi, aber nicht immer zuverlässig
- ⚠️ **Variable Load Recognition** - Geräte mit schwankender Leistung werden oft zu fragmented
- ⚠️ **Small Load Detection** - Geräte <20W können von Grundlast überlagert werden
- ⚠️ **Nightly Merge** - Kann zu aggressive Duplikate entfernen

### Phase Detection
- ⚠️ **Inverter Devices** - Modern Wärmepumpen/Klimaanlage mit Inverter-Kompressor sind schwierig
- ⚠️ **Simultaneous Events** - Wenn 2+ Geräte exakt gleichzeitig starten/stoppen kann Zuweisung fehlschlagen

### UI
- ⚠️ **Chart Performance** - Bei sehr langen Zeiträumen (>7 Tage) kann Live-Update langsam werden
- ⚠️ **Pattern Filtering** - Search/Filter können manchmal keine Ergebnisse finden obwohl Patterns existieren

---

## 🔄 In Progress / Planned Next

**Werden derzeit entwickelt oder sind nächste Priorität:**

### v0.7.0 (Geplant)
- 🔄 **Improved Variable Load Handling** - Bessere Erkennung für Induktionsherd, Staubsauger mit Stufen
- 🔄 **Pattern Confidence Scoring** - Jedes Pattern erhält Confidence-Score basierend auf Konsistenz
- 🔄 **Device Groups** - Manual grouping von Patterns zu Devices (z.B. "Wohnzimmer" = mehrere Patterns)
- 🔄 **Nightly Report** - Täglicher Summary: Top Devices, Trends, Anomalien

### v0.8.0 (Geplant)
- 📋 **MQTT Discovery** - Automatische Integration mit Home Assistant MQTT Discovery
- 📋 **Appliance Library** - Vordefinierte Pattern für Standard-Geräte (Kühlschrank, Waschmaschine, etc.)
- 📋 **Anomaly Detection** - Warnt wenn Gerät ungewöhnliches Verhalten zeigt
- 📋 **Energy Cost Estimation** - Kostenanalyse basierend auf Energiepreisen

### v0.9.0+ (Langfristig)
- 🎯 **Home Assistant Integration** - Native HA Services & Automations
- 🎯 **Notifications** - HA Notifications für erkannte Geräte
- 🎯 **Machine Learning** - Optional: TensorFlow-basiertes Pattern Learning (für erfahrene User)
- 🎯 **Export/Import** - Patterns zwischen Instanzen austauschen
- 🎯 **Appliance Database** - Community-geteilte Pattern-Библиотека

---

## ❌ Known Issues & Limitations

**Bugs die bekannt/geplant sind für Fix:**

### High Priority (Sollten baldfix)
- 🐛 **Chart Flicker** - Bei sehr schnellem Phasenwechsel kann Chart "springen"
- 🐛 **Pattern Merge Bug** - Manchmal werden unterschiedliche Geräte versehentlich gemergt
- 🐛 **Manual Pattern Slow** - Pattern-Creation via UI kann bei >1h Zeitraum sehr langsam werden

### Medium Priority (Sollten mittelfristig fix)
- 🐛 **Search Not Finding Patterns** - Filter-Funktion übersieht manchmal Patterns
- 🐛 **Memory Leak** - Bei sehr langen Runtimes (>30 Tage) kann RAM leicht wachsen
- 🐛 **Timezone Issues** - Manchmal Probleme bei Datumsumrechnung über Zeitzonen hinweg

### Low Priority / By Design
- 🚫 **Cross-Phase Pattern Matching** - Absichtlich deaktiviert um Interferenz zu verhindern (kann in Config aktiviert werden)
- 🚫 **Very Low Power Detection** - <10W Geräte sind physikal schwierig (zu nah an Grundlast-Rauschen)

---

## 📊 Feature Matrix

| Feature | Status | Zuverlässigkeit | Anmerkung |
|---------|--------|-----------------|-----------|
| **Kühlschrank Pattern** | ✅ | 95% | Sehr stabil, funktioniert fastest immer |
| **Waschmaschine Pattern** | ✅ | 85% | Gute Phasen-Struktur, funktioniert gut |
| **Wasserkocher Detection** | ✅ | 90% | Einfaches On/Off, sehr zuverlässig |
| **Induktionsherd** | ⚠️ | 40% | Variable Leistung -> fragmented Patterns |
| **Staubsauger (variabel)** | ⚠️ | 35% | Stufen-basierte Leistung ist schwierig |
| **TV/Computer** | ⚠️ | 50% | Standby + variable Last schwierig |
| **Wärmepumpe (Inverter)** | ⚠️ | 30% | Moderne Inverter-Kompressoren komplex |
| **LED-Leuchte** | ❌ | 5% | <10W ist unter Rausch-Schwelle |
| **PV-Wechselrichter** | ❌ | 0% | Erzeugt Energie statt zu verbrauchen |

---

## 🤔 Design Decisions

### Warum kein Cross-Phase Matching?
- If Kühlschrank manchmal L1 manchmal L2 nutzt → würde als ein Pattern gemacht
- Aber besser: 2 separate Patterns, User kann manuell labeln als "Kühlschrank"
- Verhindert Interferenz bei geteiltem Gerät zwischen Phasen

### Warum EMA statt vollständiger Retraining?
- EMA (Exponential Moving Average) ist speichereffizient
- Älteren Patterns weniger Gewicht → neue Geräte lernt schnell
- Alternative (Full Re-Train) würde exponentiell länger dauern

### Warum SQLite statt anderen DB?
- Keine externe Abhängigkeit ("Batteries included")
- ACID-Garantien für Pattern Persistence
- Easy Backup (einfach DB-Dateien kopieren)

---

## 🎯 Success Criteria für "Production Ready"

Für v1.0.0 (Production) sollten diese Bedingungen erfüllt sein:

- ✅ Mindestens 90% Zuverlässigkeit für Standard-Geräte (Kühlschrank, Waschmaschine, Wasserkocher)
- ✅ Keine Memory-Leaks über 30+ Tage Betrieb
- ✅ MQTT Discovery Integration funktioniert
- ✅ Home Assistant native Integration
- ✅ Umfangreiche Test-Suite mit bekannten Betriebsmittel-Patterns
- ✅ Community-getestete Appliance Library (50+ Geräte)
- ✅ Dokumentation: DOCS.md + TROUBLESHOOTING + Video-Guides

**Aktueller Status (v0.6.0):** 🚧 BETA - Etwa 40% von Production-Ready

---

## 📞 Contributing to Roadmap

Du hast Ideen was prioritär sein sollte?

1. **Feature Request** - GitHub Issue mit `[feature-request]` Tag
2. **Bug Report** - GitHub Issue mit `[bug]` Tag und Logs
3. **Pull Request** - Direkt Code beitragen (siehe CONTRIBUTING.md)

**Bitte:** Sei realistisch - wenn etwas variable Leistung hat (z.B. Induktionsherd) ist das ein Hard Problem in NILM. Ein PR der 100% Zuverlässigkeit verspricht ist unrealistisch.

---

Last Updated: März 2026  
Next Review: Nach v0.7.0 Release
