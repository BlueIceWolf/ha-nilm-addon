ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install system packages:
# - gcc/g++/musl-dev/python3-dev for numpy compilation
# - py3-scikit-learn + py3-scipy as pre-compiled Alpine packages
#   (avoids 10-30 min source compilation of scikit-learn on ARM)
RUN apk add --no-cache \
    gcc \
    g++ \
    musl-dev \
    python3-dev \
    py3-scikit-learn \
    py3-scipy

# Set working directory
WORKDIR /app

# Copy dependency manifest first so pip install can use layer cache
COPY requirements.txt /tmp/requirements.txt

# Install Python dependencies
# --prefer-binary: prefer pre-built wheels over source compilation
RUN pip3 install --no-cache-dir --prefer-binary -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

# Copy application sources after dependencies
# Keep the Python package structure so `/app/main.py` can import `app.*`.
COPY app/ /app/app
COPY main.py /app/main.py
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
