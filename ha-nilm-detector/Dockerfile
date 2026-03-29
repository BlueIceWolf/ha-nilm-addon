ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install pre-built Alpine Python packages for heavy scientific deps.
# This avoids source compilation on ARM during addon updates.
RUN apk add --no-cache \
    py3-numpy \
    py3-scikit-learn \
    py3-scipy

# Set working directory
WORKDIR /app

# Copy dependency manifest first so pip install can use layer cache
COPY requirements.txt /tmp/requirements.txt

# Install Python dependencies
# Keep pip installs lightweight (pure Python deps from requirements.txt).
RUN pip3 install --no-cache-dir --prefer-binary -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

# Copy application sources after dependencies
# Keep the Python package structure so `/app/main.py` can import `app.*`.
COPY app/ /app/app
COPY main.py /app/main.py
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
