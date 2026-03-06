# Release 0.1.3

## Highlights
- Ensure `/app/main.py` exists by copying the `app/` tree into `/app` during Docker builds.
- Install dependencies from `/tmp/requirements.txt` before startup so `python3 -u /app/main.py` can run.

## Notes
- Update via Supervisor by refreshing the repository and reinstalling the add-on to trigger a rebuild.
