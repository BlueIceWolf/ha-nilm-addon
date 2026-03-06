ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install system packages needed for numpy compilation
RUN apk add --no-cache \
    gcc \
    g++ \
    musl-dev \
    python3-dev

# Set working directory
WORKDIR /app

# Copy application sources
COPY app /app
COPY main.py /app/main.py
COPY requirements.txt /tmp/requirements.txt
COPY run.sh /run.sh

# Install Python dependencies
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt \
    && chmod a+x /run.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD [ "wget", "--quiet", "--tries=1", "--spider", "http://localhost:8080/health" ] || exit 1

CMD [ "/run.sh" ]
