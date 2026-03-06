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

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application
COPY app ./app
COPY run.sh /

# Make run script executable
RUN chmod a+x /run.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD [ "wget", "--quiet", "--tries=1", "--spider", "http://localhost:8080/health" ] || exit 1

CMD [ "/run.sh" ]
