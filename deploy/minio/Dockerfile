FROM debian:bookworm-slim

ARG TARGETARCH

LABEL org.opencontainers.image.title="MinIO for the Cambodia rice DSS demonstration" \
      org.opencontainers.image.version="RELEASE.2025-07-23T15-54-02Z" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.source="https://github.com/minio/minio/tree/RELEASE.2025-07-23T15-54-02Z"

# Keep the existing server version after its registry images became unavailable.
# Digests match both the official release assets and their .sha256sum files.
RUN set -eu; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    rm -rf /var/lib/apt/lists/*; \
    case "${TARGETARCH}" in \
      amd64) minio_sha256="eef6581f6509f43ece007a6f2eb4c5e3ce41498c8956e919a7ac7b4b170fa431" ;; \
      arm64) minio_sha256="ec9f48fee97dee7e6ce8fe9f576471bcd52380c035091d8b075b64d606124c7e" ;; \
      *) echo "Unsupported MinIO architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl --fail --location --retry 3 --connect-timeout 15 --max-time 180 \
      "https://github.com/minio/minio/releases/download/RELEASE.2025-07-23T15-54-02Z/minio.linux-${TARGETARCH}.RELEASE.2025-07-23T15-54-02Z" \
      --output /usr/local/bin/minio; \
    printf '%s  /usr/local/bin/minio\n' "${minio_sha256}" | sha256sum --check --strict; \
    chmod 0755 /usr/local/bin/minio; \
    mkdir -p /data

COPY LICENSE /usr/share/licenses/minio/LICENSE

EXPOSE 9000 9001
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
