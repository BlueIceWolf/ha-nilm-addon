# HA NILM Detector

<p align="center">
  <img src="ha-nilm-detector/logo.png" alt="HA NILM Detector Logo" width="190">
</p>

<p align="center">
  <strong>Lokale Geräteerkennung aus Stromverbrauchsdaten für Home Assistant</strong><br>
  <em>NILM = Non-Intrusive Load Monitoring</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Beta">
  <img src="https://img.shields.io/badge/version-0.7.8-blue" alt="Version 0.7.8">
  <img src="https://img.shields.io/badge/Home%20Assistant-Add--on-41BDF5" alt="Home Assistant Add-on">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
</p>

> [!WARNING]
> HA NILM Detector ist ein experimentelles Beta-Projekt. Die Erkennung funktioniert bei klaren, wiederkehrenden Lastprofilen bereits gut, ist aber noch nicht für kritische Automatisierungen gedacht.

## Was macht das Add-on?

HA NILM Detector beobachtet einen oder mehrere Leistungssensoren aus Home Assistant und versucht daraus wiederkehrende Geräte- und Lastmuster zu erkennen.

Du brauchst dafür **keinen separaten Sensor an jedem Gerät**. Für den Einstieg reicht ein Leistungssensor auf einer Phase. Mit getrennten Sensoren für L1, L2 und L3 kann die Erkennung zusätzlich phasenbezogen arbeiten.

### Aktueller Stand in v0.7.8

- lokale Verarbeitung ohne Cloud-Zwang
- L1/L2/L3 einzeln nutzbar
- Event- und Zykluserkennung mit Pre-/Post-Roll
- per-Phase Pattern Learning
- stabile und provisorische Lernmuster
- Pattern-Matching nach Leistung, Dauer, Peak, Inrush und Kurvenform
- prototype-basiertes Matching physischer Geräte statt starrer Fingerprints
- fuzzy Merge ähnlicher Muster und Betriebsarten
- Schutz vor Switch-off-/negativen Delta-Artefakten beim Lernen
- automatische Reparatur alter fehlerhafter Geräte-/Pattern-Zuordnungen
- Confidence-, Segmentierungs- und Baseline-Qualitätsbewertung
- Web-UI über Home Assistant Ingress
- manuelle Labels und Korrekturen
- Debug-/Training-Log
- SQLite-Persistenz
- Shared-Pattern- und LLM-Review-Exports

Die ausführlichen Änderungen stehen in [RELEASE.md](ha-nilm-detector/RELEASE.md) und [CHANGELOG.md](ha-nilm-detector/CHANGELOG.md).

## Installation

1. Öffne in Home Assistant **Einstellungen → Add-ons → Add-on Store**.
2. Öffne oben rechts das Menü **Repositories**.
3. Füge dieses Repository hinzu:

```text
https://github.com/BlueIceWolf/ha-nilm-addon
```

4. Installiere **HA NILM Detector**.
5. Trage mindestens einen Leistungssensor ein.
6. Starte das Add-on und öffne die Weboberfläche.

## Minimale Konfiguration

Mindestens eine Phase muss gesetzt sein:

```yaml
home_assistant:
  phase_entities:
    l1: sensor.dein_l1_leistung
    l2: ""
    l3: ""
```

Für drei getrennte Phasen:

```yaml
home_assistant:
  phase_entities:
    l1: sensor.leistung_l1
    l2: sensor.leistung_l2
    l3: sensor.leistung_l3
```

Der Sensorzustand muss numerisch sein und die aktuelle Leistung in Watt liefern.

> [!TIP]
> Je sauberer und häufiger der Leistungssensor aktualisiert wird, desto besser kann das Add-on Start, Ende, Inrush und Kurvenform eines Ereignisses erfassen.

## Wie funktioniert das Lernen?

Vereinfacht läuft die Verarbeitung so:

```text
Home Assistant Leistungssensoren
          ↓
      Live-Messwerte
          ↓
 Event-/Zykluserkennung
          ↓
 Segmentierungsbewertung
          ↓
 Feature Extraction
 Leistung · Dauer · Rise/Fall · Plateau · Shape
          ↓
 Klassifikation / Pattern Matching
          ↓
 provisional oder stable pattern
          ↓
 Merge / Bestätigung / Benutzerlabel
          ↓
 Web-UI + lokale Datenbank
```

Muster mit schwächerer Segmentierung können zunächst als **provisional** gesammelt werden. Wiederholt sich ein plausibles Muster oft genug, kann es zu einem stabilen Pattern hochgestuft werden.

Seit **0.7.7/0.7.8** wird beim Lernen bevorzugt die baseline-korrigierte Leistungsänderung (`delta_avg_power_w`) verwendet. Ausschaltflanken und nicht-positive Delta-Ereignisse werden nicht als neue Verbraucher gelernt. Dadurch soll die Geräte-Registry stärker auf wiederkehrende physische Lasten konvergieren statt auf kurzzeitige Baseline-Artefakte.

## Welche Geräte funktionieren gut?

**Meist einfacher zu erkennen**

- Kühlschrank und Gefrierschrank
- Wasserkocher
- Kaffeemaschine
- klassische Heizlasten
- Pumpen oder Motoren mit wiederkehrendem Zyklus
- Geräte mit klarer Ein-/Aus-Leistung

**Schwieriger**

- Wärmepumpen und Klimaanlagen mit Inverter
- Induktionskochfelder
- Computer und Fernseher mit stark variabler Leistungsaufnahme
- sehr kleine Lasten
- mehrere Geräte, die nahezu gleichzeitig schalten

NILM ist keine direkte Gerätemessung. Zwei Geräte mit sehr ähnlichen Lastprofilen können deshalb verwechselt werden.


## Lernpipeline 2.0

Ab **0.7.0** arbeitet das Add-on nicht mehr nur mit einzelnen Heuristiken, sondern mit einer mehrstufigen lokalen Lernpipeline:

```text
Leistungssensor
      ↓
Adaptive Segmentierung
      ↓
Learning Filter v2
      ↓
Feature Vector v2
      ↓
Pattern + Shape + Temporal
      ↓
RandomForest Champion/Challenger
      ↓
Attention-Klassifikator
      ↓
Explainable Ensemble
      ↓
Drift Monitor
      ↓
Pattern Update / Provisional Learning
```

### Learning Filter v2

Nur technisch brauchbare Events dürfen das Modell verändern. Unvollständige Start-/Endbereiche, zu wenige Samples, instabile Baselines, schwache Segmentierung und wahrscheinliche Mehrgeräte-Überlagerungen werden blockiert oder nur provisorisch gelernt.

### Feature Vector v2

Jedes Event wird in einen einheitlichen Merkmalsvektor überführt. Darin stecken unter anderem Leistung, Peak, Laufzeit, Energie, Inrush, Varianz, Rampen, Substates, Lastfaktor, Baseline-Delta, Segmentierungsqualität, Waveform-Vollständigkeit, Overlap, Formmerkmale, Wiederholungszeit, Tageszeit und Phase.

### Champion / Challenger

Das lokale RandomForest-Modell testet mehrere Kandidaten per Cross-Validation. Ein Challenger wird nur übernommen, wenn seine Balanced Accuracy messbar besser ist als die des aktuellen Standardmodells.

### Drift Monitor

Wenn ein bekanntes Gerät sein Profil langsam verändert, wird es nicht sofort als neues Gerät behandelt. Bei Drift wird das bestehende Pattern vorsichtiger aktualisiert, damit Alterung, saisonale Änderungen oder veränderte Betriebsbedingungen nicht zu Pattern-Wildwuchs führen.

### Explainable Ensemble

Pattern-, Shape-, RandomForest-, Attention-, Temporal- und Rule-Scores werden gemeinsam bewertet. Starke Übereinstimmung erhöht das Vertrauen; widersprüchliche Modelle führen eher zu `unknown` oder einer vorsichtigen Entscheidung.

## Eingebaute KI-Klassifikation

Ab **0.7.0** läuft die zusätzliche KI-Bewertung vollständig im Add-on. Es wird **kein Ollama, kein externer KI-Server und keine Cloud-API** benötigt.

Die Erkennung kombiniert:

- Segmentierung und Waveform-Qualität
- Pattern- und Shape-Matching
- lokales RandomForest-ML
- einen eingebauten Attention-Klassifikator
- zeitliche Wiederholung und Phasenbindung

Der Attention-Klassifikator arbeitet ähnlich wie ein Query/Key/Value-Vergleich: Ein neues Event wird als Merkmalsvektor mit bereits gelernten Mustern verglichen. Ähnliche Muster erhalten per Softmax ein höheres Gewicht. Dadurch kann das System auch bei mehreren ähnlichen Kandidaten eine gewichtete Entscheidung treffen, ohne ein separates Sprachmodell zu benötigen.

Alles läuft offline im Add-on-Container.

## Web-UI

Die Weboberfläche wird über Home Assistant Ingress geöffnet und trennt den Workflow in mehrere Bereiche:

- **Live** – aktuelle Leistung und Verlauf
- **Events** – erkannte Lastwechsel und Zyklen
- **Geräte** – gruppierte und erkannte Muster
- **Lernen** – Pattern-Status, Labels und Lernentscheidungen
- **Debug** – Pipeline- und Trainingsinformationen

Gelernte Muster können manuell beschriftet werden. Diese Korrekturen helfen dabei, spätere Matches nachvollziehbarer zu machen.

## Speicherorte

Standardmäßig nutzt das Add-on:

```text
/data/ha_nilm_detector/
├── nilm_live.sqlite3
├── nilm_patterns.sqlite3
└── nilm.log
```

Die Daten bleiben lokal im Add-on-Speicher. Exportfunktionen werden nur aktiv vom Benutzer ausgelöst.

## Wichtige Optionen

Für den normalen Betrieb sind die Standardwerte vorgesehen. Relevante erweiterte Optionen sind unter anderem:

```yaml
language: de
log_level: info
update_interval_seconds: 5

learning:
  auto_pipeline_enabled: true
  auto_pipeline_interval_minutes: 30
  start_threshold_w: 30
  end_threshold_w: 12
  pre_roll_s: 20
  post_roll_s: 30
  pattern_match_threshold: 0.45
  segmentation_threshold: 0.40
  stable_segmentation_threshold: 0.70

storage:
  base_path: /data/ha_nilm_detector
  retention_days: 30
```

Ändere die Lernparameter nur gezielt. Zu aggressive Schwellwerte erzeugen schnell fragmentierte oder falsche Patterns.

## Troubleshooting

### Keine Messwerte

- Entity-ID auf Tippfehler prüfen
- Sensor in **Entwicklerwerkzeuge → Zustände** kontrollieren
- sicherstellen, dass der Sensor einen numerischen Watt-Wert liefert
- Add-on-Log prüfen

### Keine Patterns

- mehrere klare Schaltvorgänge des gleichen Geräts abwarten
- unter **Events** prüfen, ob überhaupt vollständige Ereignisse erkannt werden
- bei Bedarf `log_level: debug` setzen
- Segmentierungs- und Training-Log kontrollieren

### Zu viele ähnliche Patterns

Das kann bei variablen Lasten oder unvollständig erfassten Zyklen passieren. Ab **0.7.6** werden neue Muster gegen bestehende Geräte-Prototypen derselben Phase verglichen, statt eine physische Geräteidentität nur aus einem exakten Fingerprint abzuleiten. **0.7.7/0.7.8** filtern zusätzlich negative Delta-/Ausschalt-Artefakte und reparieren betroffene automatische Registry-Einträge beim Start.

Wenn trotzdem viele Einmal-Patterns entstehen, sind besonders **Events**, **Lernen** und der Debug-/Training-Log interessant.

### Web-UI wirkt nach Update alt

Browser einmal hart neu laden:

```text
Ctrl + Shift + R
```

## Entwicklung

Das eigentliche Home-Assistant-Add-on liegt in:

```text
ha-nilm-detector/
```

Wichtige Dateien:

```text
ha-nilm-detector/
├── app/                 Python-Anwendung
├── config.yaml          Add-on-Manifest und Optionen
├── Dockerfile
├── run.sh
├── DOCS.md              Add-on-Store-Dokumentation
├── CHANGELOG.md
└── RELEASE.md
```

Tests lokal:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest
pytest -q
```

Unter Windows:

```powershell
.venv\Scripts\activate
```

## Projektstatus

Aktuelle Version: **0.7.8 (BETA)**.

Die aktuelle Test-Suite umfasst **65 Tests**. Die letzten Änderungen härten insbesondere den Lernpfad gegen instabile Baselines, negative Delta-/Ausschalt-Artefakte und fehlerhafte Provisional-Testfälle ab. Das Projekt bleibt trotzdem Beta, weil reale Häuser, überlagerte Verbraucher und variable Lastprofile deutlich vielfältiger sind als synthetische Tests.

## Mitmachen

Issues, reproduzierbare Messbeispiele und Pull Requests sind willkommen. Besonders hilfreich sind Fälle, bei denen ein Event falsch segmentiert, ein Gerät falsch klassifiziert oder ein Pattern unnötig dupliziert wird.

## Lizenz

MIT License – siehe [LICENSE](LICENSE).
