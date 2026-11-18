# syntax=docker/dockerfile:1.7
# MinIO built from a pinned upstream source tag (AGPL-3.0).
# MinIO no longer publishes community container images to public registries,
# so SafeFace builds its own from source on the connected build machine and
# ships it in the offline bundle like every other image.
ARG MINIO_RELEASE=RELEASE.2024-12-18T13-15-44Z

FROM golang:1.23.4-bookworm AS build
ARG MINIO_RELEASE
RUN git clone --depth 1 --branch "${MINIO_RELEASE}" https://github.com/minio/minio.git /src
WORKDIR /src
RUN CGO_ENABLED=0 go build -trimpath -tags kqueue \
      -ldflags "-s -w -X github.com/minio/minio/cmd.Version=${MINIO_RELEASE#RELEASE.} -X github.com/minio/minio/cmd.ReleaseTag=${MINIO_RELEASE}" \
      -o /out/minio .

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10002 minio && useradd --system --uid 10002 --gid minio --home-dir /data minio \
    && mkdir -p /data && chown minio:minio /data
COPY --from=build /out/minio /usr/bin/minio
USER 10002:10002
ENV MINIO_CONFIG_DIR=/tmp/minio-config
EXPOSE 9000
ENTRYPOINT ["/usr/bin/minio"]
CMD ["server", "/data"]
