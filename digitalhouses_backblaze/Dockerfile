FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION="0.1.0"
ARG BUILD_ARCH

ENV APP_VERSION="${BUILD_VERSION}" \
    PYTHONUNBUFFERED="1"

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache \
        py3-paho-mqtt \
        python3 \
        tzdata

COPY rootfs /

RUN chmod a+x /run.sh \
    && python3 -m py_compile \
        /app/app.py \
        /app/backblaze.py \
        /app/config.py \
        /app/discovery.py

CMD ["/run.sh"]
