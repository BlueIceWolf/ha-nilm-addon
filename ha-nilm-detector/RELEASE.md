# Release 0.2.10

## Store Kurztext
- Datenbank-Trennung: Live-Rotationsdaten und Geraete-/Musterdaten sind jetzt getrennt.
- Geraete-/Muster-DB kann dauerhaft unter `/config` liegen und bleibt damit besser erhalten.
- Bestehende Muster werden beim Umstieg einmalig automatisch in die neue Pattern-DB migriert.

## Highlights
- Added dedicated patterns database support via `storage.patterns_db_path`.
- Default patterns path is `/config/nilm_patterns.sqlite3` for persistent local storage.
- Pattern operations (labeling, matching, nightly merge, manual pattern creation) now use the dedicated DB.
- Added automatic one-time migration from existing `learned_patterns` in the live DB.

## Notes
- Live readings/detections continue in the rotating runtime DB.
- Learned devices/patterns are now decoupled from live data retention cleanup.
- All processing remains fully local (privacy-first, no cloud dependency).
- Update via Supervisor by refreshing the repository and reinstalling the add-on.
