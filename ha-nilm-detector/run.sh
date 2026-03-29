#!/bin/sh
set -e

OPTIONS_PATH="/data/options.json"

echo "Starting HA NILM Detector (options: ${OPTIONS_PATH})"

PYTHON_BIN="python3"
if [ -x /usr/bin/python3 ]; then
	PYTHON_BIN="/usr/bin/python3"
fi

if ! "$PYTHON_BIN" -c "import numpy" >/dev/null 2>&1; then
	echo "numpy missing for ${PYTHON_BIN}; trying fast apk recovery..."
	if command -v apk >/dev/null 2>&1; then
		apk add --no-cache py3-numpy py3-scipy py3-scikit-learn >/dev/null || true
		if [ -x /usr/bin/python3 ]; then
			PYTHON_BIN="/usr/bin/python3"
		fi
	fi
fi

if ! "$PYTHON_BIN" -c "import numpy" >/dev/null 2>&1; then
	echo "numpy still missing; using pip fallback (can be slower once) ..."
	"$PYTHON_BIN" -m pip install --no-cache-dir --prefer-binary numpy scipy scikit-learn
fi

exec "$PYTHON_BIN" -u /app/main.py
