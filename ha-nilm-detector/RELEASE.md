# Release 0.2.1

## Store Kurztext
- Fix fuer Web-UI JSON-Fehler unter Home Assistant Ingress.
- Sensor kann jetzt explizit per `sensor_entity_id` oder `sensor_name` gewaehlt werden.
- MQTT ist jetzt wirklich optional (`mqtt.enabled`).

## Highlights
- Web-UI requests use ingress-safe relative API paths and improved JSON error handling.
- Added explicit sensor selection aliases for analysis target configuration.
- Disabled MQTT connection attempts when `mqtt.enabled` is false.

## Notes
- Update via Supervisor by refreshing the repository and reinstalling the add-on to trigger a rebuild.
