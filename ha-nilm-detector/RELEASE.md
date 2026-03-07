# Release 0.2.3

## Store Kurztext
- Neuer Home Assistant API Client fuer Supervisor-Proxy Zugriff.
- Kontinuierlicher Entity-Abruf alle 5 Sekunden (optionaler Reader-Modus).
- Aktualisierte Add-on Branding-Grafiken (`logo.png`, `icon.png`).

## Highlights
- Added `app/ha_client.py` with robust requests-based API access and error handling.
- Added helpers for single, multiple, and full state reads from Home Assistant entities.
- Added optional polling mode in `app/main.py` for direct entity monitoring.

## Notes
- Update via Supervisor by refreshing the repository and reinstalling the add-on to trigger a rebuild.
