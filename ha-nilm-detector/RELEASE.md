# Release 0.2.5

## Store Kurztext
- Stark vereinfachte Konfiguration - nur noch essenzielle Felder.
- Multi-Phase UI Support mit L1/L2/L3 Anzeige.
- Geräte-Erkennung via Auto-Discovery (kein devices_json mehr).

## Highlights
- Drastically simplified config.yaml - removed MQTT, web, processing, confidence sections.
- Added multi-phase display in Web UI (L1/L2/L3 power cards).
- Extract phase information from live readings and display individually.
- Removed devices_json - use auto-discovery and pattern labeling instead.
- Cleaner table headers and more compact pattern display.

## Notes
- Configuration is now minimal: log_level, power_source, phase_entities, learning, storage.
- All advanced options use sensible defaults (no manual configuration needed).
- Configure L1/L2/L3 phase entities to see individual phase power in UI.
- Update via Supervisor by refreshing the repository and reinstalling the add-on.
