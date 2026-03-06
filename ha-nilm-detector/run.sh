#!/bin/sh
set -e

OPTIONS_PATH="/data/options.json"

echo "Starting HA NILM Detector (options: ${OPTIONS_PATH})"

exec python3 -u /app/main.py
