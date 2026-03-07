# Release 0.2.6

## Store Kurztext
- `power_source` entfernt: Add-on nutzt jetzt immer Home Assistant REST.
- Kein Mock-Fallback mehr im Runtime-Pfad.
- Sichtbare Web-UI-Texte mit deutschen Umlauten verbessert.

## Highlights
- Removed `power_source` from add-on options/schema and fixed source to HA REST.
- Removed runtime fallback to `MockPowerSource`.
- Kept MQTT functionality in backend (not shown in visible add-on config).
- Polished visible Web UI labels with umlauts for better readability.

## Notes
- Configuration is now minimal: log_level, phase_entities, learning, storage.
- All advanced options use sensible defaults (no manual configuration needed).
- Configure L1/L2/L3 phase entities to see individual phase power in UI.
- Update via Supervisor by refreshing the repository and reinstalling the add-on.
