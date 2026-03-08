# Release 0.3.5

## Store Kurztext
- Behoben: Manuelle Muster-Erstellung speichert jetzt zuverlässig (cursor-Fix).
- Behoben: Muster-Erkennung schlägt nicht mehr fehl wegen fehlender Feature-Spalten in der Datenbank.
- Muster werden jetzt sofort erkannt, wenn genug Datenpunkte vorhanden sind.

## Highlights
- **Critical fix for pattern recognition**: Added missing feature columns (rise/fall rates, substates, pattern types) to pattern matching logic. These were being omitted from database queries, causing fallback penalties that blocked valid pattern detection.
- **Fixed manual pattern persistence**: Moved cursor.lastrowid retrieval inside transaction context to ensure pattern IDs are properly retrieved when created from UI range selection.
- Patterns now reliably save and match even with minimal power variations, significantly improving learning accuracy.

## Technical Details
- Pattern distance calculation was applying 0.35 fallback penalty when advanced features were missing
- Manual pattern creation could fail silently without returning a valid pattern ID
- Both issues combined prevented new patterns from being recognized even with adequate data
- All storage operations remain local with no cloud dependency

---

# Release 0.2.11

## Store Kurztext
- Korrigierter Pfad für Pattern-DB: jetzt unter `/addon_configs/ha_nilm_detector/` (empfohlener HA Add-on Speicherort).
- Folgt den Best Practices für addon-spezifische persistente Konfiguration.

## Highlights
- Updated patterns database path to `/addon_configs/ha_nilm_detector/nilm_patterns.sqlite3` - the recommended Home Assistant addon configuration directory.
- Follows HA best practices for addon-specific persistent configuration storage.
- Existing patterns will be automatically migrated to the new location on first startup.

---

# Release 0.2.10

## Store Kurztext
- Datenbank-Trennung: Live-Rotationsdaten und Geraete-/Musterdaten sind jetzt getrennt.
- Geraete-/Muster-DB kann dauerhaft unter `/addon_configs/ha_nilm_detector/` liegen und bleibt damit besser erhalten.
- Bestehende Muster werden beim Umstieg einmalig automatisch in die neue Pattern-DB migriert.

## Highlights
- Added dedicated patterns database support via `storage.patterns_db_path`.
- Default patterns path is `/addon_configs/ha_nilm_detector/nilm_patterns.sqlite3` for persistent local storage.
- Pattern operations (labeling, matching, nightly merge, manual pattern creation) now use the dedicated DB.
- Added automatic one-time migration from existing `learned_patterns` in the live DB.

## Notes
- Live readings/detections continue in the rotating runtime DB.
- Learned devices/patterns are now decoupled from live data retention cleanup.
- All processing remains fully local (privacy-first, no cloud dependency).
- Update via Supervisor by refreshing the repository and reinstalling the add-on.
