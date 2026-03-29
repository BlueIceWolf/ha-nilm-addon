ARG BUILD_FROM
FROM ${BUILD_FROM}

# Fast dependency install path for HA add-on updates:
# - use Alpine system Python + prebuilt py3-* packages for heavy deps
# - keep pip only for small pure-Python extras
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-numpy \
    py3-scipy \
    py3-scikit-learn

# Set working directory
WORKDIR /app

# Copy dependency manifest first so pip install can use layer cache
COPY requirements.txt /tmp/requirements.txt

# Install only lightweight pip dependencies.
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

# Copy application sources after dependencies
# Keep the Python package structure so `/app/main.py` can import `app.*`.
COPY app/ /app/app
COPY main.py /app/main.py
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
