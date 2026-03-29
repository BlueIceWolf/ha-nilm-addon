ARG BUILD_FROM=alpine:3.20
FROM ${BUILD_FROM}

# Fast dependency install path for HA add-on updates:
# - use Alpine system Python + prebuilt py3-* packages for heavy deps
# - keep pip only for small pure-Python extras
RUN apk add --no-cache \
    python3 \
    py3-requests \
    py3-paho-mqtt \
    py3-numpy \
    py3-scipy \
    py3-scikit-learn

# Set working directory
WORKDIR /app

# All runtime dependencies are installed with apk for fast addon builds and
# to avoid PEP 668 restrictions on system Python pip installs.

# Copy application sources after dependencies
# Keep the Python package structure so `/app/main.py` can import `app.*`.
COPY app/ /app/app
COPY main.py /app/main.py
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
