FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION="1.1.0"
ARG BUILD_ARCH
ARG OOKLA_VERSION="1.2.0"

ENV APP_VERSION="${BUILD_VERSION}" \
    HOME="/data" \
    XDG_CONFIG_HOME="/data/.config" \
    PYTHONUNBUFFERED="1"

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache \
        ca-certificates \
        curl \
        iputils \
        libstdc++ \
        py3-paho-mqtt \
        python3 \
        tar \
        zlib \
    && set -eux; \
    case "${BUILD_ARCH:-$(uname -m)}" in \
        amd64|x86_64) \
            OOKLA_ARCH="x86_64"; \
            OOKLA_SHA256="5690596c54ff9bed63fa3732f818a05dbc2db19ad36ed68f21ca5f64d5cfeeb7"; \
            ;; \
        aarch64) \
            OOKLA_ARCH="aarch64"; \
            OOKLA_SHA256="3953d231da3783e2bf8904b6dd72767c5c6e533e163d3742fd0437affa431bd3"; \
            ;; \
        *) \
            echo "Unsupported architecture: ${BUILD_ARCH:-$(uname -m)}" >&2; \
            exit 1; \
            ;; \
    esac; \
    curl --fail --location --silent --show-error \
        "https://install.speedtest.net/app/cli/ookla-speedtest-${OOKLA_VERSION}-linux-${OOKLA_ARCH}.tgz" \
        --output /tmp/ookla-speedtest.tgz; \
    echo "${OOKLA_SHA256} /tmp/ookla-speedtest.tgz" | sha256sum -c -; \
    tar -xzf /tmp/ookla-speedtest.tgz -C /tmp speedtest; \
    install -m 0755 /tmp/speedtest /usr/local/bin/speedtest; \
    rm -f /tmp/speedtest /tmp/ookla-speedtest.tgz; \
    speedtest --version

COPY rootfs /

RUN chmod a+x /run.sh \
    && python3 -m py_compile \
        /app/core.py \
        /app/discovery.py \
        /app/app.py

CMD ["/run.sh"]
