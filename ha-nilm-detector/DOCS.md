# HA NILM Detector

Non-Intrusive Load Monitoring (NILM) Add-on for Home Assistant. Automatically detects and monitors appliances based on their power consumption patterns.

## Features

- **Automatic Device Detection**: Learns and identifies appliances from power consumption patterns
- **Real-time Monitoring**: Continuous monitoring of power usage
- **Home Assistant Integration**: Native MQTT Discovery integration
- **Multiple Device Types**: Support for refrigerators, washing machines, dishwashers, and more
- **Flexible Configuration**: Easy setup and customization

## Installation

1. Add this repository to your Home Assistant Add-on Store:
   ```
   https://github.com/BlueIceWolf/ha-nilm-addon
   ```

2. Install the "HA NILM Detector" add-on

3. Configure the add-on with your MQTT broker settings

4. Start the add-on

## Configuration

### Home Assistant Add-on UI setup

The add-on now exposes core options directly in the Home Assistant add-on UI:

- `debug`, `log_level`, `update_interval_seconds`
- `power_source` and `power_phase`
- `mqtt.*` (broker, port, credentials, topic/discovery prefixes)
- `home_assistant.*` (`url`, `power_entity_id`, `token`, `entity_id_prefix`)
- `storage.*` for local SQLite persistence and warm-start learning
- `processing.*` and `confidence.min_confidence`
- `devices_json` for device definitions

### How to pass your power sensor to the add-on

Set the following in add-on options:

- `power_source: home_assistant_rest`
- `home_assistant.power_entity_id: sensor.<your_power_sensor>`
- `home_assistant.url: http://supervisor/core/api` (default for HA add-ons)
- `home_assistant.token`: can stay empty in most add-on setups because `SUPERVISOR_TOKEN` is used automatically

If your sensor state is numeric (for example `432.5`), the add-on reads it directly.

### Built-in database and learning

Yes, the add-on now has its own local SQLite database:

- Path: `storage.db_path` (default `/data/nilm.sqlite3`)
- Stored data: raw power readings and detection events
- Retention: `storage.retention_days`
- Learning warm-start: `storage.learning_warmup_minutes`

On startup, adaptive detectors are primed from recent stored readings so learning continues across restarts.

Storage crash-safety details:

- SQLite uses `WAL` journaling and `synchronous=FULL` for stronger durability on sudden restarts/power loss.
- Writes are executed in atomic transactions.
- On shutdown, a WAL checkpoint is attempted.
- Database integrity is checked on startup; if corruption is detected, the file is quarantined (`*.corrupt.<timestamp>`) and a new DB is created automatically.

Example for `devices_json`:

```json
{
   "kitchen_fridge": {
      "enabled": true,
      "detector_type": "fridge",
      "power_min_w": 10,
      "power_max_w": 500,
      "min_runtime_seconds": 30,
      "min_pause_seconds": 60,
      "startup_duration_seconds": 5
   }
}
```

### Do I need a Home Assistant integration?

Short answer: no, not required.

- This add-on publishes via MQTT and supports Home Assistant MQTT Discovery.
- With MQTT Discovery enabled, entities appear automatically without a custom integration.
- A custom HA integration is only needed if you want a dedicated config flow/UI beyond add-on options (for example, wizard-based device onboarding).

### Power Data Source
The add-on currently uses mock data for testing. To connect real power sensors:

- Modify `app/collector/source.py` to read from your power sensors
- Support for MQTT-based sensors (Shelly, Tasmota, etc.) can be added

### Device Detection
The system automatically learns device patterns during the initial learning phase (24 hours). After learning, it can detect:

- Refrigerators (100-300W)
- Washing machines (500-2000W)
- Dishwashers (1000-3000W)
- Ovens (1500-4000W)

## Usage

Once installed and configured, the add-on will:

1. **Learning Phase** (24 hours): Collect baseline power consumption
2. **Detection Phase**: Automatically identify and monitor devices
3. **Reporting**: Publish device states via MQTT to Home Assistant

## Troubleshooting

### Detailed logs for debugging

Set `log_level` in the add-on options to get more detail in Home Assistant logs:

- `trace` or `debug`: maximum detail for startup/runtime troubleshooting
- `info`: normal operational logs (default)
- `warning`, `error`, `fatal`: reduced output

When debugging startup issues, use `debug` first.

### No devices detected
- Ensure the learning phase has completed (24 hours)
- Check power sensor data is being received
- Verify MQTT connection

### Incorrect device classification
- Power consumption patterns may vary by device model
- Consider manual device configuration for specific cases

## Development

This add-on is written in Python and uses:
- NumPy for data analysis
- Paho-MQTT for Home Assistant communication
- Modular detector system for different appliance types

## License

MIT License