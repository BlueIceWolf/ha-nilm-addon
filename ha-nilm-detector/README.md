# HA NILM Detector

[![GitHub Actions](https://github.com/BlueIceWolf/ha-nilm-addon/workflows/Python%20application/badge.svg)](https://github.com/BlueIceWolf/ha-nilm-addon/actions)
[![Docker Build](https://github.com/BlueIceWolf/ha-nilm-addon/workflows/Docker%20Build/badge.svg)](https://github.com/BlueIceWolf/ha-nilm-addon/actions)

Home Assistant Add-on for Non-Intrusive Load Monitoring (NILM). Automatically detects and monitors household appliances based on their power consumption patterns.

## Quick Start

1. **Add Repository**: Add `https://github.com/BlueIceWolf/ha-nilm-addon` to your Home Assistant Add-on Store
2. **Install Add-on**: Search for "HA NILM Detector" and install
3. **Configure**: Set your MQTT broker details
4. **Start**: The add-on will begin learning device patterns automatically

## Features

- 🔍 **Automatic Detection**: Learns appliance signatures from power data
- 📊 **Real-time Monitoring**: Continuous power consumption analysis
- 🏠 **Home Assistant Native**: Full MQTT Discovery integration
- 🔧 **Extensible**: Easy to add new device types and sensors
- 📈 **Statistics**: Daily runtime and cycle tracking

## Supported Devices

- 🧊 Refrigerators (100-300W)
- 🧺 Washing Machines (500-2000W)
- 🍽️ Dishwashers (1000-3000W)
- 🔥 Ovens (1500-4000W)

## Architecture

```
Power Sensor → Collector → Auto Detector → MQTT Publisher → Home Assistant
```

## Development

### Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
python test_local.py

# Run realistic simulation
python test_realistic.py
```

### Project Structure

```
ha-nilm-detector/
├── config.yaml          # Add-on configuration
├── Dockerfile          # Container definition
├── run.sh             # Startup script
├── build.yaml         # Build configuration
├── DOCS.md           # Documentation
├── translations/     # UI translations
└── app/              # Python application
    ├── main.py       # Entry point
    ├── detectors/    # Detection algorithms
    ├── publishers/   # MQTT integration
    └── utils/        # Utilities
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License - see LICENSE file for details