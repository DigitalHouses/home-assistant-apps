FROM ghcr.io/home-assistant/base:latest
ARG BUILD_VERSION="0.1.11"
ARG BUILD_ARCH
ENV APP_VERSION="${BUILD_VERSION}" PYTHONUNBUFFERED="1"
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"
COPY requirements.txt /tmp/system-globals-requirements.txt
RUN apk add --no-cache python3 py3-pip tzdata ca-certificates \
    && python3 -m pip install --no-cache-dir --break-system-packages -r /tmp/system-globals-requirements.txt \
    && python3 -c "import paho.mqtt; from paho.mqtt.client import CallbackAPIVersion; assert paho.mqtt.__version__ == '2.1.0'" \
    && rm /tmp/system-globals-requirements.txt
COPY rootfs/ /
RUN chmod a+x /run.sh && python3 -c "import sqlite3; assert sqlite3.sqlite_version" && python3 -m compileall -q /app
CMD ["/run.sh"]
