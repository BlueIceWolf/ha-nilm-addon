# Changelog

> ⚠️ **Hinweis**: Dieses Projekt ist experimentell (BETA) - Breaking Changes und Bugs können auftreten.

## 0.6.38 (BETA)

## 0.6.39 (BETA)

**Segmentierungsqualitaet und Lern-Gating weiter gehaertet: weniger falsche Shape-Scores, sichere Kandidatenlabels bei Teilzyklen und sauberere Lernfreigabe**

- Shape-Matching korrigiert:
  - explizite `shape_signature` wird wieder genutzt, auch wenn Metadaten dazu noch fehlen
  - fehlende/ungueltige Shape-Signaturen erzeugen keine kuenstlich positive Shape-Confidence mehr
- Segmentierungsbewertung erweitert:
  - `segmentation_confidence` und `waveform_completeness_score` fliessen jetzt explizit in Entscheidungen ein
  - Baseline-Sichtbarkeit vor/nach dem Event wird bewertet und als Penalty/Meta gespeichert
- Labeling fuer unvollstaendige Zyklen abgesichert:
  - Teilzyklen werden konsequenter auf `compressor_candidate`, `motor_candidate`, `pump_candidate` oder `fridge_candidate` heruntergestuft
  - schwache Segmentierung darf keine zu optimistischen Endlabels mehr erzeugen
- Lernen/Persistenz gehaertet:
  - schwache Segmentierung blockiert Pattern-Lernen gezielt statt verrauschte Daten in stabile Muster zu uebernehmen
  - Profil-basierte Vollzyklen aus Tests/Imports bleiben trotzdem lernfaehig, wenn Start und Ende Baseline sichtbar zeigen
- Segmentierungsabschluss verbessert:
  - Mid-Cycle-Starts koennen nach Post-Roll sauber finalisiert werden
  - reine Kurzspikes werden weiterhin als Rauschen verworfen
- Neue/erweiterte Regressionen fuer:
  - Mid-Cycle `truncated_start`
  - fehlende `shape_signature`
  - Startup-only-Kompressorzyklen
  - vollständige Waveform-Signaturen und Lern-Gates

**Segmentierungs-Hotfix fuer Vollzyklen: bessere Event-Grenzen, weniger Truncation und sauberere Lernsignaturen**

- Event-Erkennung auf explizite Zustaende umgestellt: `IDLE -> PRE_EVENT -> ACTIVE -> ENDING`
- Start-Erkennung erweitert:
  - Rolling-Baseline statt nur impliziter statischer Grenze
  - Delta-Trigger und zusaetzlicher Derivative-Trigger fuer fruehere Inrush-Erfassung
  - Pre-Roll wird bei Start robuster uebernommen
- End-Erkennung verbessert:
  - Event endet erst nach stabiler Rueckkehr nahe Baseline ueber konfigurierbare Hold-Time
  - kurze Dips fuehren nicht mehr sofort zu einem Event-Ende
  - Post-Roll wird sauber gesammelt, bevor finalisiert wird
- Truncation-Logik geschaerft:
  - echte harte Inrush-Starts aus dem Idle werden nicht mehr faelschlich als `truncated_start` markiert
  - `shape_signature` wird fuer truncierte Events nicht als vollwertige Lernbasis verwendet
- Neue Segmentierungs-Regressionen fuer:
  - Motorstart mit Inrush
  - Kompressorzyklus
  - Kurzspike
  - verrauschtes Signal
  - Mehrstufenlast

## 0.6.37 (BETA)

**NILM-Lernpfad deutlich erweitert: bessere Segmentierung, feinere Unknown-Klassen und reichhaltigere Review-Daten fuer den HA-Test**

- Event-Segmentierung verbessert:
  - Rolling-Baseline fuer stabileren Start
  - konfigurierbare End-Hold-Logik und Stabilization-Grace
  - Pre-Roll/Post-Roll-Erfassung inkl. Truncation-Flags
- Klassifikation in Stufen ausgebaut:
  - neue Derived Features wie `inrush_ratio`, `plateau_stability`, `startup_sharpness`, `shape_tail_slope`
  - `shape_signature` wird jetzt aktiv fuer Shape-Matching genutzt
  - feinere Unknown-Labels statt pauschalem `unknown_electronics`
- Persistenz und Review erweitert:
  - Events und Learned Patterns speichern jetzt Kandidaten, Confidence-Aufteilung, Segmentierungsinfos und Waveform-Kontext
  - Exporte/Kontextansichten enthalten mehr Debug- und Review-Daten
- Dedup robuster gemacht:
  - explizite Duplicate-Toleranzen fuer Power, Dauer, Inrush und Shape
- Neue Regressionstests:
  - `test_event_segmentation_refactor.py`
  - `test_learning_refactor_classification.py`

## 0.6.36 (BETA)

**Kollaborative Musterfreigabe testweise aktiviert: Shared Pack + LLM-Review + UI-Exportflaechen**

- Neue datensparsame Community-Exporte:
  - `export_shared_pattern_pack()` fuer freiwillig teilbare Pattern-Packs
  - keine Roh-Readings, keine Event-Historie, keine Kommentare, keine exakten Pattern-Zeitstempel
  - freie User-Labels werden fuer den oeffentlichen Export auf sichere Typen reduziert
- Neues Entwickler-/LLM-Analysebundle:
  - `export_llm_review_bundle()` mit kompakten Pattern-Features, Event-Summaries, `classification_log` und `training_log`
  - gedacht fuer Offline-Analyse und ChatGPT-/LLM-gestuetzte Verbesserung der Erkennung
- Web-UI erweitert:
  - neue Buttons fuer `Shared Pack` und `LLM Review`
  - bestehende JSON-Exportlogik auf gemeinsamen Download-Helfer vereinheitlicht
  - Build-Info wird jetzt korrekt in die HTML-Seite injiziert
- Deterministische Erstklassifikation geschaerft:
  - nur noch konkrete High-Confidence-Geraetetypen bei markanten Signaturen
  - ambivalente Lasten bleiben `unknown` und werden nicht mehr zu groben Sammelkategorien gezwungen
- Neue Tests:
  - `test_shared_exports.py`
  - `test_pattern_first_level_classification.py`

## 0.6.35 (BETA)

**Pipeline-Stabilisierung abgeschlossen: modulare Lernstufen + bessere Inspektion + Roundtrip-Haertung**

- Lernpipeline in explizite Stufen ausgelagert (`prepare -> match -> dedup-decision`) in neuem Modul `app/learning/pipeline_stages.py`
- `learn_cycle_pattern` nutzt jetzt diese deterministischen Stage-Helper fuer bessere Lesbarkeit und Testbarkeit
- Dedup-Schwellwerte zentralisiert (`dedup_update_similarity`, `dedup_merge_similarity`) statt verstreuter Literale
- Pattern-Kontext-API liefert jetzt auch segmentierte `event_phases` pro Event
- UI-Kontextchart hebt Inrush/Steady/Shutdown visuell hervor und zeigt Phasen-Dauern in den Muster-Stats
- Import/Export gehaertet:
  - Export enthaelt jetzt Schema-Metadaten
  - Import uebernimmt mehr Pattern-/Device-/Event-Felder fuer robusteren Roundtrip
  - Timestamp-Repair wird nach Import erzwungen ausgefuehrt
- Neue Tests:
  - `test_learning_pipeline_stages.py`
  - `test_persistence_roundtrip.py`
  - erweiterter Dedup-Test fuer "gleiches Geraet, leicht anderer Inrush"

## 0.6.32 (BETA)

## 0.6.34 (BETA)

**Phase-1 Hybrid-ML gestartet + Build-/Debug-Transparenz erweitert**

- Hybrid-Fusion im Lernpfad auf Phase-1-Gewichte umgestellt:
  - Boosting `45%`, Shape `35%`, Prototype `20%`
  - Explizite `decision_reason` fuer jede finale Entscheidung
- Local ML auf Boosting-first umgestellt (mit sicherem Fallback):
  - `HistGradientBoostingClassifier` als Primaermodell
  - `RandomForest` als Fallback bei Edge-Umgebungen
  - Trainingsdaten priorisieren bestaetigte/User-gelabelte Muster
- Persistente Hybrid-Metriken erweitert:
  - `events`: `prototype_score`, `dtw_score`, `hybrid_score`, `decision_reason`
  - `training_log`: `prototype_score`, `shape_score`, `ml_score`, `final_score`, `decision_reason`, `agreement_flag`
- Web-UI/Debug erweitert:
  - Build-Info sichtbar (Version + Git-Commit)
  - Hybrid-Panel zeigt `decision_reason`
  - Neue KPI-Karten: `Boosting/Shape Agreement` und `ML Override Rate`

## 0.6.32 (BETA)

**Hotfix: Add-on Buildfehler (PEP 668 / externally-managed-environment) behoben**

- Dockerfile installiert jetzt alle Runtime-Abhaengigkeiten ausschliesslich via `apk`
- `pip install`-Schritt im Image-Build entfernt (vermeidet PEP-668 Fehler in Alpine System-Python)
- `py3-requests` und `py3-paho-mqtt` werden ebenfalls per `apk` installiert
- Default fuer `ARG BUILD_FROM` gesetzt, wodurch die Build-Warnung zu leerem Base-Image reduziert wird

## 0.6.33 (BETA)

**Muster-Qualitaet & Detail-Debugging verbessert (Dedup + Kontextansicht + Touch-Fix)**

- Lernpfad um robuste Dedup-Entscheidung vor Insert erweitert:
  - Similarity-Scoring (Shape/Duration/Delta/Peak-Inrush)
  - Schwellwerte: `>=0.92 update_existing`, `0.85..0.92 merge_mode`, sonst `create_new`
  - Session-Guard verhindert Doppel-Lernen derselben Kurve im selben Lauf
- Datenmodell erweitert fuer Dedup/Debug:
  - `learned_patterns`: `curve_hash`, `shape_signature`, `avg_*`, `occurrence_count`, `device_group_id`, `mode_key`
  - `events`/`training_log`: dedup-Felder (`dedup_result`, `matched_pattern_id`, `similarity_score`, `dedup_reason`)
- Neue Muster-Kontext-API:
  - `GET /api/patterns/<id>/context?pre=2&post=2`
  - Liefert Event-Meta, Kontextfenster, Rohsamples, Start/End-Marker, Baseline
- Pattern-Modal in der UI erweitert:
  - Kontextansicht mit Vor-/Nachlauf (2s/5s/10s), Event-Hervorhebung, Start/End-Linien
  - Zoom via Mausrad, Hover-Infos (Zeit/Leistung), Umschaltung `Mit Kontext`/`Nur Muster`
- Touch/Mobile-Usability verbessert:
  - Zuverlaessige Musterauswahl per `pointerup`
  - Expliziter `Details`-Button pro Musterzeile fuer Handy/Tablet
- Neue Tests:
  - `test_pattern_dedup.py`
  - `test_pattern_context.py`

## 0.6.31 (BETA)

**Hotfix: numpy/scipy/sklearn Importfehler beim Add-on-Start behoben**

- `run.sh` nutzt jetzt bevorzugt `/usr/bin/python3` (Alpine-System-Python), falls verfügbar
- Runtime-Guard prüft `import numpy` vor App-Start
- Falls Pakete fehlen: schneller `apk`-Recovery-Pfad (`py3-numpy`, `py3-scipy`, `py3-scikit-learn`)
- Fallback: einmaliger `pip`-Install nur wenn `apk` nicht ausreicht
- Versionsbump auf `0.6.31`, damit Home Assistant sicher ein neues Image baut/zieht

## 0.6.30 (BETA)

**Pipeline-/Debug-Refactor abgeschlossen: bessere Nachvollziehbarkeit und robustere Lernbasis**

- Neue Core-Komponente: per-Phase `NILMPipeline` im Main-Loop aktiv integriert
- Main-Loop nutzt jetzt pro konfigurierter Phase eine dedizierte Pipeline inkl. Stage-Result-Tracking
- Neues Overlap-Modul (`app/core/overlap.py`): zweistufige Event-Zerlegung (`detect_strong` -> `subtract` -> `detect_weak`)
- `overlap_score` und `overlap_events_count` werden bei Klassifikation/Persistenz in den Cycle-Payload übernommen
- Neues Trainings-Audit-Log: Tabelle `training_log` mit API-Zugriff
- Neue API-Endpunkte:
  - `GET /api/training-log`
  - `GET /api/debug/pipeline-buffer`
- Web-UI als 5-Tab-Dashboard reorganisiert (`LIVE`, `EVENTS`, `GERÄTE`, `LERNEN`, `DEBUG`) mit separaten Refresh-Workflows
- Debug-Tab zeigt jetzt Pipeline-Puffer + Klassifikationslog + strukturierten Confidence-Breakdown
- Typing-/Escape-Hotfixes: Optional-Strings im Storage und JS-RegEx-Sequenzen bereinigt
- Laufzeittest/Smoke-Test durchgeführt:
  - API-Tests für neue Endpunkte erfolgreich
  - Voller lokaler E2E-Start außerhalb HA erwartbar am `supervisor`-Host gescheitert (Umgebungsabhängig)

## 0.6.29 (BETA)

**Update-Speed verbessert: keine schweren Source-Builds mehr fuer Scientific-Dependencies**

- Add-on-Dockerfile nutzt jetzt durchgaengig vorkompilierte Alpine-Pakete: `py3-numpy`, `py3-scipy`, `py3-scikit-learn`
- Compiler-/Build-Toolchain (`gcc`, `g++`, `musl-dev`, `python3-dev`) aus dem Add-on-Image entfernt
- `ha-nilm-detector/requirements.txt` entschlackt: nur noch leichte pip-Abhaengigkeiten (`paho-mqtt`, `requests`)
- Ziel: deutlich schnellere Update-/Install-Zeiten, speziell auf ARM (Raspberry Pi)
- Tests weiterhin gruen: `11 passed`

## 0.6.28 (BETA)

**Machine Learning aktiviert: RandomForest-Klassifikator lernt von deinen Labels**

**Inrush/Runtime-Datenmodell erweitert (Baseline, Event-Phasen, Device-Cycles)**

- ML-System `LocalMLClassifier` aktiviert mit scikit-learn RandomForest (80 Estimators)
- Standardmäßig an: `ml_enabled=true` in config.yaml und app/config.py
- scikit-learn>=1.0 hinzugefügt zu Abhängigkeiten (both requirements.txt-Dateien)
- **Wie es funktioniert:**
  - System sammelt alle bestätigten Labels deiner Muster
  - RandomForest trainiert sich automatisch, sobald ≥8 Samples mit ≥2 Klassen vorhanden
  - Neue Zyklen werden durch 3er-Hybrid klassifiziert: Prototype-Matching + Shape-Similarity + **ML-Vorhersage**
  - Confidence-Score wird aus allen 3 Quellen kombiniert → höhere Genauigkeit
- Intelligente Fallbacks: Wenn ML unsicher (<0.55 confidence) → nutzt regelbasierte Klassifikation
- Features für ML: avg_power, peak_power, duration, energy, power_variance, rise/fall rates, duty_cycle, num_substates, boolesche Pattern-Flags
- ML-Score sichtbar im Web-UI unter "Hybrid AI Debug" → "ML" Feld zeigt top-3 Vorhersagen
- `learned_patterns` und `events` speichern zusätzlich Baseline/Delta-Kennwerte (`baseline_before`, `baseline_after`, `delta_avg`, `delta_peak`, `delta_energy`)
- Neue Tabelle `event_phases`: segmentierte Zyklus-Phasen (`baseline`, `inrush`, `steady_run/modulated_run`, `shutdown`, `cooldown`)
- Neue Tabelle `device_cycles`: aggregierte Gerätezyklus-Typen mit Inrush-/Run-Dauern und Leistungsprofil
- Neue API-Endpunkte: `GET /api/event-phases` und `GET /api/device-cycles`
- `GET /api/devices` enthält jetzt `device_subclass`, `baseline_range_min_w`, `baseline_range_max_w`
- `GET /api/events` enthält jetzt Baseline/Delta-Felder pro Event
- Tests weiterhin grün: `11 passed`

## 0.6.26 (BETA)

**NILM-Wissensbasis erweitert: Events, Devices, Entscheidungslog und Label-Historie**

- Neue persistente Tabellen: `devices`, `events`, `pattern_features`, `classification_log`, `user_labels`, `pattern_history`
- `learned_patterns` erweitert um Device-Linking und Shape/Fingerprint-Felder (`device_id`, `candidate_name`, `shape_vector_json`, `prototype_hash`)
- Explizite `patterns`-Mirror-Tabelle als getrennte Pattern-Ebene eingeführt (parallel zu `learned_patterns`)
- Idempotente Startup-Backfills mit Migrationsmarkern: alte Pattern werden in normalisierte Tabellen und Patterns-Mirror überführt
- Lern-/Klassifikationspfad schreibt jetzt zusätzlich:
  - Event-Records (`events`)
  - nachvollziehbare Entscheidungsprotokolle (`classification_log`)
  - versionierte Feature-Snapshots (`pattern_features`)
  - Pattern-Verlauf (`pattern_history`)
  - User-Label-Änderungen (`user_labels`)
- Neue Web-API-Endpunkte:
  - `GET /api/devices`
  - `GET /api/events`
  - `GET /api/classification-log`
  - `GET /api/user-labels`
  - `GET /api/debug/export-training-jsonl`
  - `GET /api/debug/export-features-csv`
- Storage-Config vereinheitlicht mit `PRIMARY_STORAGE_PATH` und `LEGACY_STORAGE_PATHS`
- Tests weiterhin grün: `10 passed`

## 0.6.25 (BETA)

**Robuste Datenpersistenz: kein stiller Datenverlust nach Restart oder Update**

- **Legacy-Tabelle `patterns` migriert**: Ältere DBs mit `patterns` statt `learned_patterns` werden jetzt vollständig in das neue Schema übernommen statt übersprungen
- **Storage-Pfad-Konstanten**: `LEGACY_PATTERNS_CANDIDATES` und `LEGACY_LIVE_CANDIDATES` zentral definiert – keine verstreuten Hardcoded-Pfade mehr
- **Migrations-Marker**: Neue `migration_events`-Tabelle in Live- und Pattern-DB verhindert Doppel-Import bei jedem Neustart
- **Deduplication via `INSERT OR IGNORE`**: Recovery-Inserts überschreiben keine vorhandenen Daten
- **Verbesserte Startup-Diagnostik**: Primärer Storage-Pfad, Legacy-DB-Dateigrössen, Zeilen-Zähler für `learned_patterns` UND `patterns` in allen DBs
- **Live-Recovery mit Marker**: `_maybe_recover_live_from_legacy_files` schreibt ebenfalls Migration-Event, verhindert Re-Import

## 0.6.21 (BETA)

## 0.6.24 (BETA)

**Klassifikations- und Feature-Qualitaet deutlich verbessert**
- Feature-Extraction liefert jetzt robustere echte Zyklus-Features statt flacher Fallback-Werte:
  Rise/Fall-Edge-Raten, Plateau/Substate-Segmentierung und `step_count`
- Deterministische First-Level-Regeln vor ML/Smart-Classifier:
  `heater`, `motor`, `electronics`, `long_running` (sonst `unknown`)
- Replay-Edge-Fallback nutzt jetzt ebenfalls echte `CycleFeatures.extract(...)` statt Dummy-Features
- Frequency-basierte Label-Verfeinerung in der Pattern-Aktualisierung (`fridge`/`pump`/`manual_device` Regeln)
- `step_count` durchgaengig in Schema/Pattern-Updates/Pattern-Insert und manueller Bereichserstellung persistiert
- Erweiterte Klassifikations-Logs mit Regelgrund und Schluessel-Features fuer Debugging

## 0.6.21 (BETA)

**Persistenz-, Migration- und Warmstart-Stabilisierung**
- Speicherpfade zentralisiert (Standard jetzt unter `/data/ha_nilm_detector`) inkl. neuer Option `storage.base_path`
- Legacy-Dateimigration robuster: migriert auch wenn Ziel-Datei bereits existiert aber leer ist
- SQLite Startup-Diagnose erweitert: Dateiexistenz, Dateigroesse, Tabellenliste, Row-Counts und `PRAGMA user_version`
- Migrationen robust gemacht: `learned_patterns`-Migration prueft Tabellenexistenz und loggt erwartete Faelle als Info statt Warnfehler
- Warmstart repariert: diagnostischer Ladepfad mit SQL-Transparenz und Fallback auf letzte Werte ausserhalb des Zeitfensters
- Shutdown-Reihenfolge gehaertet: erst Flush/Commit/Close fuer Storage, dann restliche Dienste

## 0.6.22 (BETA)

**Lernlauf erkennt Zyklen robuster bei schwieriger Historie**
- Neuer Replay-Fallback: Wenn adaptive Replay-Paesse 0 Zyklen liefern, wird eine edge-basierte Segmentierung ausgefuehrt
- Segmentierung nutzt Baseline + Delta-On/Off inkl. Sparse-Gap-Handling fuer Recorder-Historie
- Verhindert den Fall `Messpunkte > 0` aber `Zyklen gelernt: 0` in vielen Praxis-Szenarien

## 0.6.23 (BETA)

**Hybrid-Debug: unbekanntes Label mit plausibler Konfidenz**
- Fix fuer inkonsistente Ausgabe `label=unknown` bei sehr hoher Konfidenz
- `unknown` wird jetzt auf niedrige Konfidenz begrenzt und als expliziter Fallback (`fallback_unknown_label`) markiert
- Debug-Explain-Payload bleibt erhalten (inkl. optionalem ML-Block)

## 0.6.20 (BETA)

**Datenpersistenz-Hotfix nach Updates**
- Startup-Recovery fuer Live-Daten ergaenzt: `power_readings` und `detections` werden aus Legacy-DBs wiederhergestellt, wenn die aktuelle Live-DB leer ist
- Schuetzt gegen Update-Szenarien, in denen eine leere Ziel-DB existiert und reine Dateimigration deshalb nicht greift
- Verhindert, dass Verlauf nach Update "verschwunden" wirkt, obwohl Daten in alten Pfaden noch vorhanden sind

## 0.6.19 (BETA)

**Manueller Lernlauf robuster bei importierten Verlaufsdaten**
- Manueller Lernlauf nutzt jetzt 48h Replay-Fenster statt 24h
- Replay fuehrt einen Fallback-Pass ohne Baseline-Priming aus, falls im ersten Pass keine Zyklen gefunden werden
- Verbessert Erkennung bei unruhigen/lastigen Importverlaeufen, in denen adaptive Baseline zuvor zu konservativ war

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
