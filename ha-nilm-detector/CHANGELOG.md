# Changelog
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
