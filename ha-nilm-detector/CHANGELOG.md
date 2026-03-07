# Changelog

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
