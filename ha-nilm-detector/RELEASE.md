# Release 0.1.2

## Highlights
- Simplified `run.sh` so the Alpine container can start cleanly with `/bin/sh` and `python3 -u /app/main.py`.
- Bumped to version 0.1.2 so HA Supervisor sees the new build during repository updates.

## Notes
- Update via Supervisor by refreshing the repository and reinstalling the add-on to trigger a rebuild.
