FROM golang:1.23-alpine AS builder
RUN apk add --no-cache build-base sqlite-dev pkgconf
WORKDIR /src
COPY go.mod ./
COPY cmd/ ./cmd/
RUN CGO_ENABLED=1 go build -trimpath -ldflags="-s -w" -o /out/dh-network ./cmd/dh-network

FROM ghcr.io/home-assistant/base:latest
ARG BUILD_VERSION="0.1.5"
ARG BUILD_ARCH
ENV APP_VERSION="${BUILD_VERSION}"
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"
RUN apk add --no-cache python3 sqlite-libs ca-certificates
COPY rootfs/ /
COPY --from=builder /out/dh-network /usr/local/bin/dh-network
RUN chmod +x /run.sh && python3 -m compileall -q /app
CMD ["/run.sh"]
