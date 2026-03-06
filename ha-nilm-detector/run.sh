#!/bin/sh
# Startup script for HA NILM Detector add-on

set -e

# Load options from Home Assistant
OPTIONS_PATH="/data/options.json"

# Log startup
echo "Starting HA NILM Detector..."
echo "Options path: $OPTIONS_PATH"

# Start the Python application
cd /app
exec python3 -u app/main.py
