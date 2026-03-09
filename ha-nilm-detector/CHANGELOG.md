# Changelog
## 0.6.0 (BETA)

> ⚠️ **BETA-STATUS**: Fundamentales Architektur-Redesign - noch nicht ausführlich in Produktion getestet. Bei Problemen auf v0.5.2.1 zurückrollen.

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
