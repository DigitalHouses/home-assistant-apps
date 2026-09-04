FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION="0.1.3"
ARG BUILD_ARCH

ENV APP_VERSION="${BUILD_VERSION}" \
    PYTHONUNBUFFERED="1"

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache \
        py3-paho-mqtt \
        py3-paramiko \
        py3-psycopg2 \
        py3-pymysql \
        python3 \
        tzdata

COPY rootfs /

RUN chmod a+x /run.sh \
    && python3 -m py_compile \
        /app/app.py \
        /app/config.py \
        /app/discovery.py \
        /app/metrics.py \
        /app/storage.py \
        /app/db/__init__.py \
        /app/db/base.py \
        /app/db/postgres.py \
        /app/db/mariadb.py

CMD ["/run.sh"]
