# Changelog

> ⚠️ **Hinweis**: Dieses Projekt ist experimentell (BETA) - Breaking Changes und Bugs können auftreten.

## 0.6.18 (BETA)

**Hybrid-AI Debug Panel im Dashboard**
- Neues Dashboard-Panel mit letzter Hybrid-Entscheidung: Quelle, Label, Confidence, Distanz, Prototype-/Shape-/Repeatability-Score
- Anzeige von ML-Ergebnissen inklusive Top-Kandidaten (falls ML aktiv/verfuegbar)
- Neuer API-Endpunkt: `/api/debug/hybrid-status`
- Storage speichert jetzt den letzten Hybrid-Entscheid inklusive Explain-Payload fuer UI-Debugging

## 0.6.17 (BETA)

**Hybrid-AI Architektur modular erweitert**
- Neue Lernmodule: `event_detection.py`, `pattern_matching.py`, `shape_similarity.py`, `substate_analysis.py`, `ml_classifier.py`, `online_learning.py`
- Event Detection verbessert: Hysterese + Gap-Merging jetzt über dedizierte Adaptive-Event-State-Machine
- Pattern Matching erweitert: Hybrid-Score aus Prototype-Matching, Shape-Similarity und Wiederholbarkeit
- Optionales lokales ML (RandomForest) integriert, mit `unknown`-Fallback bei Unsicherheit
- Erklärbare Entscheidungen in der Label-Vorhersage (`explain`-Payload mit Teil-Scores)
- Neue `learning`-Konfigoptionen für AI/ML/Shape/Online-Learning und Match-/Confidence-Schwellen
- Export erweitert um `pattern_dataset` für spätere Trainings- und Analyse-Pipelines

## 0.6.16 (BETA)

**Lernpipeline jetzt automatisch und manuell triggerbar**
- Neuer periodischer Auto-Lernlauf: Replay + Pattern-Merge wird zyklisch ausgefuehrt
- Manueller Trigger bleibt aktiv (Dashboard-Button), startet dieselbe Pipeline sofort
- Neue Optionen unter `learning`: `auto_pipeline_enabled` und `auto_pipeline_interval_minutes`
- Nightly-Lernlauf nutzt jetzt ebenfalls die gleiche aktive Pipeline statt nur statischer Merge-Pass

## 0.6.15 (BETA)

**Lernpipeline fuer echte Neuauswertung von Exportdaten**
- Neues Tool `nilm_pipeline.py` mit End-to-End Pipeline: Rohdaten -> Event Detection -> Clustering -> Pattern Update -> Bewertung
- Erkennt neue Events ueber Baseline/Threshold statt nur bestehende Patterns erneut zu exportieren
- Gruppiert Events nach Aehnlichkeit (Leistung, Dauer, Profilform) und merged passende Patterns
- Aktualisiert Pattern-Statistiken laufend (`seen_count`, Leistung, Dauer, Varianz, Profilkurve)
- Exportiert ML-freundliche Artefakte: `events_detected.json`, `patterns_updated.json`, `features.csv`, `dataset.jsonl`

## 0.6.14 (BETA)

**Test-Release für schnellen Praxistest**
- Version-Bump auf `0.6.14` fuer schnellen Rollout im Add-on Store
- Export/Import-Workflow bleibt aktiv fuer Diagnostik und Datenaustausch
- Neues CLI-Hilfstool `nilm_pattern_analyzer.py` zur strengeren Pattern-Bewertung von Export-Dateien

## 0.6.13 (BETA)

**Daten-Export/Import für Diagnostik und externe Analyse**
- Neue Buttons im Dashboard: `📥 Daten exportieren` und `📤 Daten importieren`
- Exportiert alle gelernte Muster und Messwerte als JSON-Datei für externe Analyse
- Ermöglicht Datenimport nach Modifikation (z.B. durch externe KI zum Tuning)
- Unterstützt Datenfreigabe mit KI-Tools zur Fehlersuche und Optimierung
- Export enthält: Alle Muster mit Signaturen, Phasenzuordnung, Lernstatistiken + historische Messwerte
- SQLite Batch-Write Optimierung: Reduziert DB-Transaktionen um ~90-95% für bessere Schreibperformance
- Bilingual: Buttons und Fehlermeldungen in DE/EN verfügbar

## 0.6.12 (BETA)

**Gelernte Geräte automatisch im Dashboard sichtbar**
- Repräsentative Mustergruppen werden jetzt als virtuelle Geräte im Live-Geräteblock angezeigt,
  auch wenn keine manuellen Detektoren konfiguriert sind.
- Gerätestatus wird aus aktueller Phasenleistung gegen gelernte Muster geschätzt (Confidence-Score).
- Namenskollisionen mit konfigurierten Geräten werden durch `(learned)`-Suffix gelöst.
- Schwache, unsichere oder sehr selten gelernte Muster werden gefiltert, um das Dashboard sauber zu halten.
- Damit ist das System nun wirklich selbstlernend: Muster erscheinen nicht nur in der Musterliste,
  sondern auch als aktive Geräteeinträge, die den aktuellen Verbrauch abbilden.

## 0.6.11 (BETA)

**UI Sprach-Hotfix**
- Auch die oberen Summary-Karten im Dashboard (`Gesamtleistung`, `Phase L1/L2/L3`, `Durchschnitt (24h)`, `Spitze (24h)`, `Messwerte (24h)`, `Gelernte Muster`) sind jetzt komplett an die DE/EN-Umschaltung angebunden.

## 0.6.10 (BETA)

**Speicherort wieder explizit unter `/addon_configs`**
- Standardpfade wurden wieder auf `/addon_configs/ha_nilm_detector/` umgestellt (`nilm_live.sqlite3`, `nilm_patterns.sqlite3`, `nilm.log`).
- Bestehende Daten aus frueheren `/data`-Versionen werden beim Start automatisch in den neuen Zielpfad uebernommen, wenn dort noch keine Datei liegt.
- Pattern-Recovery prueft jetzt sowohl `/addon_configs/...` als auch `/data/...`, damit Upgrades robust bleiben.

## 0.6.9 (BETA)

**UI Sprache DE/EN weiter vervollstaendigt**
- Weitere bisher harte DE-Texte in der Web-UI wurden auf echte i18n-Keys umgestellt (Dialoge, Meldungen, Tooltips, Modal-Statistik, Pattern-Aktionen).
- Button-Tooltips werden jetzt ebenfalls je nach Sprache gesetzt.

**Kompatibilitaet mit `/addon_configs` verbessert**
- Legacy-Ordner `/addon_configs/ha_nilm_detector` wird beim Start best-effort angelegt.
- Erleichtert Migration und manuelles Bereitstellen alter DB-Dateien fuer Recovery.

## 0.6.8 (BETA)

**Hotfix: gelernte Muster nach Update wiederherstellen**
- Beim Start wird jetzt automatisch ein Legacy-Recovery ausgefuehrt, wenn die aktuelle Pattern-DB leer ist.
- Recovery liest Muster aus alten Dateien unter `/addon_configs/ha_nilm_detector/` (`nilm_patterns.sqlite3` und Fallback `nilm_live.sqlite3`).
- Dadurch bleiben bestehende gelernte Muster auch nach Pfad-/Versionswechsel sichtbar statt "weg" zu wirken.

## 0.6.7 (BETA)

**Device-Gruppen umgesetzt**
- Patterns werden jetzt mit `device_group_key`/`device_group_size` angereichert und als Gruppe darstellbar.
- Vorschlagslogik votet gruppenbasiert statt nur pro Einzelpattern, wodurch Label-Fragmente reduziert werden.

**Variable Lasten besser gebuendelt**
- Lernpfad fuehrt jetzt `operating_modes` aktiv zusammen (Mode-Clustering beim Update eines Patterns).
- Neue Zyklen werden in bestehende Betriebsmodi gemergt oder als neuer Modus angehaengt statt sofort als komplett neues Geraet zu fragmentieren.

**Web-UI erweitert**
- Muster-Tabelle zeigt neue Spalte `Gruppe` inkl. Gruppengroesse.
- Neue Sortieroption `Gruppe ↓` fuer schnelle Cluster-Pruefung.

## 0.6.6 (BETA)

**Confidence-Score jetzt sichtbar**
- Muster-Tabelle zeigt jetzt einen klaren Confidence-Wert (0-100%) pro Pattern.
- Neue Sortieroption `Confidence ↓` in der Web-UI.
- Confidence wird aus Pattern-Qualitaet (`quality_score_avg`) und Pattern-Reife (`seen_count`) abgeleitet.

**Roadmap-Punkt abgeschlossen**
- Geplanter Punkt "sichtbarer Confidence-Score" wurde umgesetzt und in README/Roadmap dokumentiert.

## 0.6.5 (BETA)

**Musterbenennung und Erkennung verbessert**
- Muster-Vorschlaege bewerten jetzt zusaetzlich den inkrementellen Lastanstieg ("wie viel kommt zur Basis dazu"), nicht nur Durchschnitt/Peak.
- Distanzfunktion nutzt Peak-Zeitpunkt im Zyklus, um kurze Spike-Lasten besser von spaeten/plateauartigen Lasten zu unterscheiden.
- Vorschlags-Voting wurde um Laufzeit-Konsistenz und Spike-Konsistenz (`peak_to_avg_ratio`) erweitert, was Label-Collapse reduziert.

**Web-UI Sprache DE/EN**
- Neue Add-on Option `language` (`de`/`en`) fuer die Dashboard-Sprache.
- Dashboard besitzt jetzt einen Sprachumschalter (Deutsch/English) und merkt sich die Auswahl im Browser.

**Roadmap-Fortschritt sichtbar gemacht**
- README und Roadmap auf aktuellen Stand gebracht (Version, Erkennungs-Fokus, naechste Schritte).

## 0.6.4 (BETA)

**Persistenz nach Neustart repariert**
- Standard-Speicherpfade wurden auf `/data` umgestellt (`nilm_live.sqlite3`, `nilm_patterns.sqlite3`, `nilm.log`), damit gelernte Muster Add-on-Neustarts ueberleben.
- Automatische Legacy-Migration eingefuehrt: vorhandene Dateien aus `/addon_configs/ha_nilm_detector/` werden beim Start nach `/data` kopiert, falls dort noch keine Zieldateien existieren.
- SQLite-Neben-Dateien (`-wal`, `-shm`) werden bei der Migration mitgenommen, um Konsistenz von bestehenden Datenbanken zu erhalten.

## 0.6.3 (BETA)

**Self-Learning deutlich erweitert**
- Replay-Learning arbeitet jetzt phasenbasiert mit separaten Learnern pro Phase (wie der Live-Pfad) statt mit aggregierter Total-Leistung.
- Pattern-Matching nutzt zusaetzlich Kurvenform-Distanz aus gespeicherten `profile_points` fuer robustere Zuordnung.
- Niedrigqualitative Zyklen werden vor dem Lernen gefiltert, um Musterrauschen in der DB zu reduzieren.
- Adaptive Match-Toleranz: etablierte Muster (hoher `seen_count`) werden strenger gematcht, damit sie nicht durch Ausreisser driften.
- Neue qualitaetsgewichtete, zeitpriorisierte Prototype-Votes (inkl. `quality_score_avg`) fuer plausiblere Selbstklassifikation.

## 0.6.2 (BETA)

**Pattern-UI + Speicherung verbessert**
- Gelernte Muster speichern jetzt echte Profilpunkte (`profile_points_json`) statt nur aggregierter Kennwerte.
- Muster-Modal zeigt die Datenquelle explizit an: `Echte Messkurve` oder `Rekonstruierte Kurve (Legacy)`.
- Profil-Visualisierung robust gemacht (kein fehlerhafter Marker-Zugriff mehr bei gespeicherten Echtprofilen).
- Replay-, Live- und manuelle Bereichs-Lernpfade schreiben nun Profilpunkte in die Pattern-DB.

**Reliability-Update: Import + Mustererkennung stabilisiert**
- Replay- und Live-Learning uebergeben jetzt vollstaendige Zyklus-Features (`power_variance`, Rise/Fall-Rate, Duty-Cycle, Substates, Heating/Motor-Flags), damit Matching nicht mehr durch Fallback-Penalties entgleist.
- Zeitstempel aus HA-History und Replay werden konsistent auf naive UTC normalisiert, um stille Fehler bei Datetime-Arithmetik zu vermeiden.
- Beim Update bestehender Patterns werden jetzt auch erweiterte Feature-Spalten und Phase mitgepflegt, nicht nur Basiswerte (avg/peak/duration).
- Label-Vorschlaege filtern bei Single-Phase-Zyklen auf phasenkompatible Pattern, wodurch unplausible Vorschlaege deutlich seltener werden.
- Manuell aus dem Graphen angelegte Patterns speichern explizit die dominante Phase.

## 0.6.0 (BETA)

> ℹ️ **Version-Status**: Fundamentales Architektur-Redesign - noch nicht ausführlich getestet. Bei Problemen auf v0.5.2.1 zurückrollen.

**Architektur-Redesign: Per-Phase Pattern Learning**
- **Separate Pattern-Learner pro Phase**: Jede Phase (L1/L2/L3) hat nun eigenen Pattern-Tracker
- **Verhindert Interferenz**: Kühlschrank (L1, 150W) + Waschmaschine (L2, 800W) werden als 2 separate Patterns erkannt, nicht als 950W-Gerät
- **Phase-Attribution**: Patterns werden explizit L1/L2/L3 zugeordnet, UI zeigt Phase deutlich an
- **Conditional Initialization**: Pattern-Learner werden nur für konfigurierte Phasen erstellt (spart Ressourcen bei 1-Phasen-Systemen)
- **Phase-basiertes Matching**: Patterns werden nur mit Cycles der gleichen Phase verglichen
- Datenbank-Schema erweitert: Neue `phase` Spalte für eindeutige Zuordnung

**Bugfixes:**
- DateTime timezone-aware/naive Konflikt in manueller Pattern-Erstellung behoben (UI "Bereich markieren" funktioniert jetzt zuverlässig)

## 0.5.2.1

**Bugfix:**
- **Phase-Erkennung repariert**: Fehler in der Variablendefinition (active_phases, num_active_phases) behoben. Reader stürzte beim Lesen der Phasendaten ab.
- NameError bei `active_phases` in source.py Zeile 348 behoben

## 0.5.2

**Neue Features:**
- **Muster-Visualisierung**: Klick auf ein Muster zeigt die rekonstruierte Leistungskurve (Anstieg, Plateau, Abfall) in Modal-Dialog
- Zeigt alle Pattern-Eigenschaften: Durchschnittsleistung, Peak, Duration, Rise/Fall-Rate
- Kurve wird aus gespeicherten Pattern-Metriken rekonstruiert für visuellen Überblick

**Verbesserungen:**
- **Phasen-Erkennung verfeinert**: Echte 3-Phasen-Geräte werden jetzt nur erkannt wenn ALLE 3 Phasen gleich starke Leistung haben (>15-60% Balance), nicht wenn beliebige mehrere Phasen aktiv sind
- Verhindert Falschklassifikation: Einzelne Geräte auf verschiedenen Phasen (z.B. Kühlschrank L1 + Waschmaschine L2) sind jetzt korrekt als Single-Phase klassifiziert
- Leistungsverteilung statt absolute Wattgrenze als Erkennungskriterium

## 0.5.1

**Verbesserungen:**
- **Web-UI modernisiert**: Karten/Tabellen/Buttons optisch an aktuelles Home-Assistant-Design angenaehert (hell + dunkel konsistent, modernere Abstaende und Kontraste).
- **Task-Fortschritt stabilisiert**: Fehlende DOM-Elemente verursachen keinen `classList`-Fehler mehr; Fortschritt wird sauber eingeblendet, wenn vorhanden.
- **Konfigurations-UI entschlackt**: Add-on Optionen fokussieren auf `home_assistant.phase_entities.l1/l2/l3`; Lernen laeuft weiterhin automatisch ueber Defaultwerte.
- Doku aktualisiert (`README.md`, `DOCS.md`) und `example_options.json` auf Minimal-Setup reduziert.

## 0.5.0

**Neue Features:**
- **Aufgaben-Fortschrittsanzeige**: Oben in der UI zeigt aktive Aufgaben (Lernläufe, HA-Import) mit Prozentanzeige
- **Chart-Optimierung**: Diagramm flackert nicht mehr bei jedem Live-Daten-Update - nur noch neu zeichnen wenn sich Daten geändert haben
- requestAnimationFrame für smoothes Rendering

**Technische Verbesserungen:**
- Intelligente Redraw-Erkennung: Vergleich von Datenpunkt-Länge und letztem Timestamp
- Progressbar mit visueller Darstellung (0-100%)
- Task-Info wird bei jedem refresh() aktualisiert

## 0.4.4

**Bugfix:**
- Behoben: IndentationError in pattern_learner.py durch verwaiste Debug-Zeile (Container-Start schlägt nicht mehr fehl)

## 0.4.3

**Neue Features:**
- **Log-Rotation**: Log-Datei wird bei jedem Container-Start rotiert (nilm.log → nilm.log.1 → nilm.log.2 → nilm.log.3)
- Maximal 3 alte Log-Dateien werden behalten, ältere werden gelöscht
- Jeder Start beginnt mit einer leeren Log-Datei für bessere Übersicht
- Konfigurierbar über `log_file` und `max_log_backups` in config.yaml

**Konfiguration:**
- `log_file`: Pfad zur Log-Datei (default: `/addon_configs/ha_nilm_detector/nilm.log`)
- `max_log_backups`: Maximale Anzahl alter Logs (default: 3)

## 0.4.2

**Verbesserung:**
- **Synchrone Phasen-Erkennung**: Unterscheidet jetzt zwischen echten 3-Phasen-Geräten (alle Phasen steigen synchron an) und mehreren 1-Phasen-Geräten auf verschiedenen Phasen (zeitlich versetzte Anstiege).
- Prüft ob Phasen innerhalb von 10 Sekunden gemeinsam ansteigen → echtes 3-Phasen-Gerät
- Verhindert Fehlklassifikation wenn z.B. Mikrowelle (L1) und Wasserkocher (L2) gleichzeitig laufen

## 0.4.1

**Bugfix:**
- **Phase-Erkennung repariert**: SmartDeviceClassifier nutzt jetzt echte Phase-Informationen aus den Messdaten statt primitiver Heuristik (>5kW = 3-Phase). **Dies verbessert die automatische Erkennung von 1-Phasen-Geräten massiv!**
- `LearnedCycle` enthält jetzt `phase_mode` Feld, das automatisch aus PowerReadings extrahiert wird.

## 0.4.0

**Neue Features:**
- **Einzelne Muster löschen**: Jedes Muster hat jetzt einen "Löschen"-Button in der Tabelle
- **Separate Clear-Buttons**: "Live-Daten löschen" und "Muster löschen" getrennt (statt generischem "DB leeren")
- Bessere Kontrolle über was gelöscht wird - Muster bleiben beim Löschen von Live-Daten erhalten

**Backend:**
- `DELETE /api/patterns/{id}/delete` endpoint für einzelnes Muster löschen
- `POST /api/debug/clear-readings` endpoint nur Live-Readings löschen
- `POST /api/debug/clear-patterns` endpoint nur Patterns löschen

## 0.3.6

- **Fixed timezone-aware datetime subtraction error**: Normalize all parsed datetimes to naive before calculations in list_patterns().
- This was preventing patterns from being displayed in UI (list_patterns failed silently with exception).
- Pattern table is now visible after learning runs complete.

## 0.3.5

- **Fixed pattern recognition failure**: Manual pattern creation now saves reliably (cursor.lastrowid moved inside transaction).
- **Fixed missing learned features in pattern matching**: Added rise_rate_w_per_s, fall_rate_w_per_s, num_substates, has_heating_pattern, has_motor_pattern columns to pattern comparison (these were causing fallback penalties that blocked pattern detection).
- Pattern learner now correctly recognizes patterns with sufficient data points due to proper feature column retrieval from database.

## 0.3.4

- Fixed `Lernen jetzt ausführen` API robustness: endpoint now always returns valid JSON on failures.
- Hardened learning replay against malformed/non-numeric phase values (skip bad points instead of aborting run).
- Improved frontend error handling for manual learning with clearer diagnostics on invalid server responses.

## 0.3.3

- Fixed import reconstruction to reduce artificial downward spikes by carrying forward per-phase values while rebuilding total power timeline.
- Improved manual learning replay robustness for historical data (`debounce_samples=1`, `noise_filter_window=1`) to detect cycles more reliably.
- Added chart time-window navigation in Web UI: selectable window (`1h/3h/6h/12h/24h`) plus `Älter` / `Neuer` scrolling.
- Extended series API and storage access with `offset` pagination support for browsing older points.

## 0.3.2

- Fixed manual `Lernen jetzt ausführen` to replay recent stored readings and actually learn new cycles before merge.
- Added learning result metrics in Web UI response (`cycles_detected`, `points_processed`) for better transparency.
- Improved HA history import by skipping non-positive values (`<= 0W`) to avoid synthetic 0W artifacts.
- Added import feedback in Web UI showing skipped non-positive sample count.

## 0.3.1

- Added Web UI action `HA Verlauf importieren` to import recorder history from Home Assistant sensors into local NILM readings.
- Added backend endpoint `POST /api/debug/import-history` for controlled history backfill (1-168h).
- Switched default live DB path to persistent addon config storage: `/addon_configs/ha_nilm_detector/nilm_live.sqlite3`.
- Added `storage.db_path` to addon options/schema for explicit live DB location control.
- Improved update resilience so historical data survives addon updates more reliably.

## 0.3.0

**Große Feature-Verbesserungen**:
- 🎯 **Adaptive Schwellwerte**: Automatische Anpassung der On/Off-Thresholds an wechselnde Baselines (10W → 50W transparent handled)
  - Baseline-Tracking via Median der letzten 60 Idle-Samples
  - Dynamische Schwellwerte: on = baseline + 30W, off = baseline + 10W
  - 20W Hysteresis-Gap verhindert Oszillation

- 🔇 **Rauschfilterung**: Median-Filter (Window=3) für stabile Zykluserkennung
  - 500W Spikes werden von echter 100W-Last getrennt
  - Verhindert Falsch-Trigger durch transiente Störungen

- ⏱️ **Debouncing**: Erfordert 2 aufeinanderfolgende Samples für Zustandswechsel
  - Eliminiert Falsch-Zyklen bei oszillierenden Signalen (45W↔15W)
  - Verhindert "Flackern" in der Geräteerkennung

- ⏰ **Temporale Muster-Verfolgung**: Lernt zeitliche Verhaltensmuster
  - Typisches Intervall zwischen Zyklen (z.B. Kühlschrank alle 30min)
  - Durchschnittliche Tageszeit (z.B. Waschmaschine um 18:00)
  - Speichert letzte 10 Intervalle für Anomalie-Erkennung

- 🌙 **Web UI Verbesserungen**:
  - **Dark Mode** - Nachtmodus mit einem Klick umschaltbar
  - **Muster-Suche** - Filter nach Label, Typ, ID
  - **Flexible Sortierung** - Nach Häufigkeit, Leistung, Dauer, Stabilität, Intervall oder ID
  - **Temporale Spalten** - Zeigt typisches Intervall und durchschnittliche Uhrzeit
  - **Interactive Tooltips** - Hover über Intervall/Uhrzeit für Details

**Technische Verbesserungen**:
- min_cycle_seconds von 20s → 5s reduziert (Mikrowelle/Toaster jetzt erkennbar)
- Noise filter window von 5 → 3 optimiert (schnellere Response)
- SQLite-Schema erweitert: `typical_interval_s`, `avg_hour_of_day`, `last_intervals_json`, `hour_distribution_json`
- Bug-Fixes: Circular imports, deque slicing, type hints

**Validierung**:
- Comprehensive test suite mit 6 Szenarien
- Alle Tests bestehen (adaptive thresholds, noise filtering, debouncing, multi-device, temporal patterns, mode detection)

## 0.2.11

- Updated patterns database path to `/addon_configs/ha_nilm_detector/nilm_patterns.sqlite3` (recommended HA addon config location).

## 0.2.10

- Added separated storage model: live rotation DB and dedicated patterns/devices DB.
- Added `storage.patterns_db_path` option (default `/addon_configs/ha_nilm_detector/nilm_patterns.sqlite3`) to keep learned patterns outside `/data`.
- Added one-time migration of existing learned patterns from live DB into dedicated patterns DB.
- Updated runtime wiring to use dedicated patterns DB for labeling, matching, nightly merge, and manual pattern creation.

## 0.2.9

- Fixed phase history rendering in chart by reading `L1/L2/L3` values from stored reading metadata.
- Improved phase timeline consistency between live payload and historical series.
- Updated root `README.md` to match current add-on version and workflow.

## 0.2.8

- Added multi-phase chart rendering with L1/L2/L3 toggles (show/hide per phase).
- Added interactive range selection in Web UI to manually mark timeline segments.
- Added manual pattern creation endpoint from selected range (`/api/patterns/create-from-range`).
- Added advanced lightweight NILM features (ramp, variance, duty cycle, substates) for better local pattern matching.
- Improved heuristic device-type suggestions with shape-based, privacy-preserving local features.

## 0.2.7

- Added manual "Jetzt ausführen" (Run Now) button in Web UI for immediate learning pass testing.
- Added "DB leeren (Debug)" button for database flush during development/testing.
- Improved test-phase workflow with on-demand learning execution.
- Enhanced Web UI with actionable controls for pattern development.

## 0.2.6

- Removed `power_source` from add-on options and schema (HA REST is now fixed runtime source).
- Removed mock power source fallback from runtime wiring.
- Kept MQTT backend support while leaving it hidden from visible add-on configuration.
- Improved visible Web UI text with proper German umlauts.

## 0.2.5

- Drastically simplified configuration: removed all unnecessary options from config.yaml.
- Added multi-phase UI support: L1/L2/L3 phase power display in Web UI.
- Removed devices_json option (configure devices via auto-discovery instead).
- Removed deprecated MQTT, web, processing, confidence config sections (use sensible defaults).
- Cleaner, more focused configuration with only essential fields.
- Extract and display individual phase power values from live readings.
- Simplified table headers and pattern display for better readability.


## 0.2.4

- Removed deprecated configuration fields: `power_phase`, `sensor_name`, `sensor_entity_id`, `power_entity_id`.
- Simplified Home Assistant configuration to only use `phase_entities` (L1/L2/L3 support).
- Removed legacy fallback code and default `devices_json` example (configure in Web UI instead).
- Cleaner multi-phase architecture preparation with at least one phase required.

## 0.2.3

- Fixed Web UI loading state handling and added clearer live status messages.
- Added top-right status details about current activity, waiting reason, and live power value.
- Improved root README presentation with logo and updated onboarding/troubleshooting sections.

## 0.2.2

- Added dedicated Home Assistant supervisor API client module (`app/ha_client.py`) using `requests`.
- Added robust entity read helpers: `get_entity_state`, `get_all_states`, `get_multiple_entities`.
- Added optional entity-reader startup mode in `app/main.py` with 5-second polling and sample entities.
- Improved token handling for supervisor API access (`SUPERVISOR_TOKEN` normalization, optional `HASSIO_TOKEN` fallback).
- Updated add-on branding assets (`logo.png`, `icon.png`).

## 0.2.1

- Fixed Web UI JSON loading under Home Assistant ingress (relative API paths + safer JSON parsing).
- Added explicit sensor selection options: `home_assistant.sensor_entity_id` and `home_assistant.sensor_name`.
- Made MQTT output truly optional via `mqtt.enabled` (analysis can run without MQTT connection).

## 0.2.0

- Added autonomous pattern learning from one power sensor using cycle detection.
- Persisted learned signatures in SQLite and update recurring matches over time.
- Added suggestion list and correction API/workflow (`/api/patterns`, label endpoint).
- Added `learning.*` options to tune start/stop thresholds and minimum cycle duration.
- Kept web UI and HA auto-connect improvements from the previous release work.

## 0.1.8

- Added direct Home Assistant power sensor ingestion via REST (`power_source: home_assistant_rest`).
- Added configurable sensor mapping (`home_assistant.power_entity_id`, URL, token fallback via `SUPERVISOR_TOKEN`).
- Added built-in SQLite storage for readings and detections (`/data/nilm.sqlite3` by default).
- Added detector warm-start from stored readings so adaptive learning survives restarts.
- Hardened SQLite durability for abrupt restarts (`WAL`, `synchronous=FULL`, integrity check, corruption quarantine/recreate).

## 0.1.7

- Added proper Home Assistant add-on UI configuration entries for MQTT, processing, confidence, logging, and update interval.
- Added `devices_json` UI option and parser support for device definitions.
- Clarified in docs that MQTT Discovery works without a separate custom HA integration.

## 0.1.6

- Added configurable `log_level` support for detailed troubleshooting logs.
- Improved runtime error logging in startup, detector execution, and MQTT publishing.
- Removed invalid HTTP health check from the Docker image.
- Fixed container package path so `/app/main.py` can import the `app` package correctly.

## 0.1.5

- Ensured `/app/main.py` exists in the image at runtime.
- Installed Python dependencies before application start.
- Improved Docker copy layout for add-on startup reliability.
