# Release 0.2.9

## Store Kurztext
- Phasenverlauf im Chart korrigiert: L1/L2/L3 werden aus gespeicherten Metadaten gelesen.
- Bessere Konsistenz zwischen Live-Phasenanzeige und historischen Verlaufsdaten.
- README auf aktuellen Stand von Version und Workflow gebracht.

## Highlights
- Fixed chart phase history (`L1/L2/L3`) by using persisted `metadata.phase_powers_w`.
- Ensured historical series aligns better with live phase cards in Web UI.
- Updated root documentation to reflect current local-only setup and latest UI features.

## Notes
- All learning remains local in Home Assistant (privacy-first, no cloud dependency).
- Existing nightly automatic learning window (02:00-05:00) remains active.
- Use manual range selection in the chart to speed up labeling during test phase.
- Update via Supervisor by refreshing the repository and reinstalling the add-on.
