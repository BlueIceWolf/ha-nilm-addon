# Release 0.2.0

## Store Kurztext
- Selbstlernende Geraete-Erkennung aus einem einzelnen Leistungssensor.
- Neue Web-UI mit Live-Statistiken und Muster-Vorschlaegen.
- Korrektur-Workflow: Vorschlaege direkt labeln, damit kuenftige Erkennung genauer wird.
- Robuste SQLite-Persistenz fuer Lernhistorie und Neustarts.

## Highlights
- Added autonomous pattern learning from a single power sensor (cycle extraction + signature storage).
- Added learned pattern persistence in SQLite with recurring-match updates over time.
- Added suggestion and correction workflow in Web UI (`/api/patterns`, `/api/patterns/<id>/label`).
- Added configurable learning thresholds in add-on options (`learning.*`).

## Notes
- Update via Supervisor by refreshing the repository and reinstalling the add-on to trigger a rebuild.
