# 🗺️ Roadmap

Was funktioniert bereits, was ist noch in Arbeit und wo soll das Projekt hin.

---

## ✅ Läuft Bereits

**Was zuverlässig funktioniert und genutzt werden kann:**

- **Live Leistungsdaten**: REST API von Home Assistant auslesen funktioniert stabil
- **Zykluserkennung**: Erkennt zuverlässig Geräte-An/Aus Übergänge
- **Mustervergleich**: Findet ähnliche Zyklen im Muster-Speicher
- **Phasen-Handling**: L1/L2/L3 richtig unterscheiden (v0.6.0+)
- **Daten speichern**: Patterns persistent in SQLite ablegen
- **Web-UI**: Chart, Muster-Tabelle, Pattern-Visualisierung funktioniert
- **Manuelles Lernen**: Bereich im Chart markieren → Muster speichern
- **Zeitliche Muster**: Lernt typische Tageszeiten und Intervalle zwischen Zyklen

---

## ⚠️ Funktioniert, aber nicht Perfekt

**Features die grundsätzlich funktionieren, aber bei bestimmten Geräten Probleme machen:**

- **Variable Lasten**: Dinge wie Induktionsherd oder Staubsauger mit Stufenschalter werden oft zu viele Patterns
- **Kleine Geräte**: Unter ~20W kann die Grundlast zu laut werden → Muster gehen unter
- **Gleichzeitige Events**: Wenn 2 Geräte genau zur gleichen Zeit starten/stoppen, weiß das System nicht wem es zuordnen soll
- **Inverter-Geräte**: Moderne Wärmepumpen und Klimaanlagen mit variablem Kompressor sind schwierig
- **Pattern aufräumen**: Die nächtliche Automatik kann manchmal zu aggressive ähnliche Patterns zusammenfassen

---

## 🔄 In Arbeit / Geplant

**Was demnächst kommt oder schon angedacht ist:**

### Kurzfristig (nächste Versionen)
- Bessere Erkennung für variable Lasten (Induktionsherd, Staubsauger)
- Confidence-Score für jedes Pattern (wie sicher ist die Erkennung?)
- Device-Gruppen: Mehrere Patterns unter einem Gerätenamen zusammenfassen
- Täglicher Summary: Top Geräte, Trends, Anomalien

### Mittelfristig
- MQTT Integration für Home Assistant
- Vordefinierte Muster für Standard-Geräte (damit nicht jeder neu lernen muss)
- Warnung wenn Gerät ungewöhnlich läuft
- Kostenberechnung basierend auf Strompreisen

### Langfristig (Nice to Have)
- Natives Home Assistant Integration (Services, Automations)
- Benachrichtigungen wenn interessante Dinge passieren
- Export/Import von Patterns zwischen Systemen
- Community-Muster teilen (wer hat einen guten Waschmaschinen-Pattern?)

---

## 🐛 Bekannte Probleme

**Was manchmal nicht läuft wie es sollte:**

### Sollte dringend fix sein
- Chart "springt" manchmal bei schnellen Phasenwechseln
- Pattern-Merge kann manchmal unterschiedliche Geräte versehentlich zusammenfassen
- Manuelle Pattern-Erstellung kann durchhängen wenn der Zeitraum größer als 1h ist

### Sollte mittelfristig fix sein
- Suche findet manchmal Patterns nicht wenn sie da sein sollten
- Bei sehr langen Runtimes (>30 Tage) kann RAM ein bisschen wachsen
- Datumsumrechnung bei Zeitzonen-Wechsel ist manchmal komisch

### Ist so beabsichtigt / Hard Problem
- Cross-Phase Matching: Absichtlich ausgeschaltet um zu verhindern dass Geräte auf verschiedenen Phasen als Interferenz wirken
- Sehr kleine Geräte (<10W) sind physikalisch schwierig - das ist unter den NILM-Grundlagen einfach eine Grenze

---

## 📊 Wie Gut's bei Verschiedenen Geräten Funktioniert

| Gerät | Funktioniert? | Anmerkung |
|-------|---------------|----------|
| Kühlschrank | ✅ Super | Sehr stabile Muster, funktioniert immer |
| Gefrierschrank | ✅ Super | Genauso stabil wie Kühlschrank |
| Waschmaschine | ✅ Gut | Hat klare Phasen, lässt sich gut lernen |
| Geschirrspüler | ✅ Gut | Ähnlich wie Waschmaschine |
| Wasserkocher | ✅ Super | Einfaches An/Aus, sehr zuverlässig |
| Kaffeemaschine | ✅ Gut | Kurz und deutlich |
| Backofen | ⚠️ Mittelmäßig | Heizelement ist relativ konstant, aber Rauschen |
| Induktionsherd | ⚠️ Schwierig | Variable Leistung je nach Einstellung → zu viele Patterns |
| Staubsauger | ⚠️ Schwierig | Stufenschalter macht viele verschiedene Lasten |
| Wärmepumpe | ⚠️ Schwierig | Inverter-Kompressor ist variabel und komplex |
| TV/Computer | ⚠️ Schwierig | Standby + variable Last schwer zu unterscheiden |
| LED-Leuchte | ❌ Geht nicht | Zu kleine Last - unter dem Rausch |
| PV-Wechselrichter | ❌ Geht nicht | Erzeugt Energie statt zu verbrauchen (anderes Vorzeichen) |

---

## 🎯 Milestones bis Produktiv

Damit das Projekt irgendwann "produktiv-ready" ist sollte gelten:

- Mindestens 90% Zuverlässigkeit bei Standard-Geräten (Kühlschrank, Waschmaschine, Wasserkocher)
- Keine RAM-Leaks auch nach Wochen durchgehend laufen
- Home Assistant Integration so dass man Devices in Automations nutzen kann
- Eine Liste von Geräten die definitiv funktionieren vs. welche nicht
- Gute Dokumentation damit neue User nicht völlig verloren sind
- Ein paar Video-Guides zum Einrichten

**Aktuell (v0.6.0):** Etwa 40-50% davon erreicht. Der Core läuft, aber viel Polish und Edge-Case-Handling fehlt noch.

---

## 💭 Warum so und nicht anders?

**Warum benutzen wir EMA (Exponential Moving Average) statt Neutraining?**  
EMA passt Patterns schnell an neue Geräte/Änderungen an ohne viel Speicher zu verbrauchen. Komplett neutraining würde länger dauern.

**Warum SQLite statt PostgreSQL oder NoSQL?**  
SQLite hat keine externen Abhängigkeiten. Backup ist einfach: DB-Datei kopieren. Reicht für die Datenmengen die wir haben.

**Warum blockiert ihr Cross-Phase Pattern Matching?**  
Wenn ein Gerät manchmal L1 manchmal L2 benutzt, würde es als *ein* Pattern gelernt. Das ist aber schlecht wenn verschiedene Geräte auf verschiedenen Phasen sind - die würden sich dann gegenseitig stören. Besser: Zwei getrennte Pattern, User labelt beide manuell als "Kühlschrank".

---

Ganz Kurz: Das Projekt funktioniert für "normale" Geräte mit stabiler Leistung sehr gut. Für alles andere ist NILM ein Hard Problem wo niemand ne vollkommene Lösung hat. Realistische Erwartungen setzen und nicht entmutigen lassen wenn Induktionsherd nicht perfekt erkannt wird 😄

