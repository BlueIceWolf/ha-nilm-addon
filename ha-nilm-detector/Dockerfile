ARG BUILD_FROM=alpine:3.20
FROM ${BUILD_FROM}

# Keep runtime dependencies in the image. The container should never install
# packages at startup because Home Assistant add-ons must start deterministically.
RUN apk add --no-cache \
    python3 \
    py3-requests \
    py3-paho-mqtt \
    py3-numpy \
    py3-scipy \
    py3-scikit-learn

WORKDIR /app

# config.yaml is copied intentionally: app.version reads the add-on manifest
# at runtime so the Web UI can show the real release version.
COPY config.yaml /app/config.yaml
COPY app/ /app/app
COPY main.py /app/main.py
COPY run.sh /run.sh

RUN chmod 0755 /run.sh

CMD ["/run.sh"]
