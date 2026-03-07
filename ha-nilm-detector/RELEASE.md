# Release 0.1.8

## Highlights
- Added direct Home Assistant sensor ingestion via REST (`power_source=home_assistant_rest`).
- Added built-in SQLite persistence for readings and detection events.
- Added warm-start learning for adaptive detectors from persisted history.
- Expanded add-on UI setup to configure sensor source and storage behavior.

## Notes
- Update via Supervisor by refreshing the repository and reinstalling the add-on to trigger a rebuild.
