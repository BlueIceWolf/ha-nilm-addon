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