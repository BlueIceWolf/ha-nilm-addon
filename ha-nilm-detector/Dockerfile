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
# Keep the Python package structure so `/app/main.py` can import `app.*`.
COPY app/ /app/app
COPY main.py /app/main.py
COPY requirements.txt /tmp/requirements.txt
COPY run.sh /run.sh

# Install Python dependencies
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt \
    && chmod a+x /run.sh

CMD [ "/run.sh" ]
