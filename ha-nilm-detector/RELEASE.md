# Release 0.1.6

## Highlights
- Added richer logging and configurable `log_level` handling for easier troubleshooting.
- Improved runtime error context in startup, detector, and MQTT publish flows.
- Docker health check was removed because no HTTP server is exposed by the add-on.

## Notes
- Current status: startup in Home Assistant is still considered unstable/not fully working.
- Update via Supervisor by refreshing the repository and reinstalling the add-on to trigger a rebuild.
