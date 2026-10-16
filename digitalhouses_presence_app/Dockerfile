FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION="0.1.21"
ARG BUILD_ARCH

ENV APP_VERSION="${BUILD_VERSION}" \
    PYTHONUNBUFFERED="1"

LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache ca-certificates python3 py3-paho-mqtt tzdata iproute2 iputils-arping py3-websockets
COPY rootfs /
RUN chmod a+x /run.sh && python3 -m compileall -q /app
CMD ["/run.sh"]
