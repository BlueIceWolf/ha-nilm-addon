# Release 0.2.4

## Store Kurztext
- Aufgeräumte Konfiguration: Entfernung veralteter Felder.
- Vereinfachte Multi-Phase Unterstützung (L1/L2/L3).
- Sauberere Architektur für zukünftige Auto-Discovery Features.

## Highlights
- Removed deprecated config fields: `power_phase`, `sensor_name`, `sensor_entity_id`, `power_entity_id`.
- Simplified to `phase_entities` only (L1/L2/L3) - at least one phase required.
- Removed legacy fallback code and default device configurations.
- Cleaner multi-phase detection architecture preparation.

## Notes
- Configuration upgrade: Use `home_assistant.phase_entities.l1/l2/l3` instead of deprecated fields.
- Configure devices in Web UI instead of `devices_json` config option.
- Update via Supervisor by refreshing the repository and reinstalling the add-on.
