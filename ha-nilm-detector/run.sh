#!/bin/sh
set -eu

OPTIONS_PATH="/data/options.json"
PYTHON_BIN="/usr/bin/python3"

echo "Starting HA NILM Detector"
echo "Options: ${OPTIONS_PATH}"

if [ ! -x "${PYTHON_BIN}" ]; then
    echo "ERROR: Python runtime not found at ${PYTHON_BIN}" >&2
    exit 1
fi

# Dependencies belong to the image. Fail clearly instead of modifying the
# container at runtime when a build is incomplete.
if ! "${PYTHON_BIN}" -c "import numpy, scipy, sklearn, requests, paho.mqtt.client" >/dev/null 2>&1; then
    echo "ERROR: Required Python dependencies are missing from the add-on image." >&2
    exit 1
fi

exec "${PYTHON_BIN}" -u /app/main.py
