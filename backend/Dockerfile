# syntax=docker/dockerfile:1.7
# SafeFace backend image. Targets: api, worker, test.
# Build happens on a connected build machine; the resulting images are saved
# to tarballs and loaded on the air-gapped server (scripts/offline_bundle.sh).

# Debian 13 (glibc 2.41): the official c2patool binary needs glibc >= 2.38.
ARG PYTHON_IMAGE=python:3.11.14-slim-trixie

# ---------------------------------------------------------------- base ------
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Air-gap guards for libraries that might otherwise try the network.
    NO_ALBUMENTATIONS_UPDATE=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TORCH_HOME=/models/torch \
    MPLCONFIGDIR=/tmp/matplotlib \
    INSIGHTFACE_HOME=/models/insightface \
    CUBLAS_WORKSPACE_CONFIG=:4096:8
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0t64 libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
        fonts-dejavu-core libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 safeface \
    && useradd --system --uid 10001 --gid safeface --home-dir /nonexistent --shell /usr/sbin/nologin safeface
WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install -r requirements.txt -c constraints.txt

# ------------------------------------------------------------------ api -----
FROM base AS api
COPY app ./app
COPY alembic.ini .
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", \
     "--forwarded-allow-ips", "*", "--no-server-header"]

# ------------------------------------------------------------ c2patool ------
FROM ${PYTHON_IMAGE} AS c2patool
ARG C2PATOOL_VERSION=0.27.22
# Digest published by GitHub for the release asset.
ARG C2PATOOL_SHA256=6f138ad53da1a62f1cd6ee71c60727efa27d13b811f4c0ea8c2a8528968b358b
RUN python - <<EOF
import hashlib, tarfile, urllib.request, io, sys
url = "https://github.com/contentauth/c2pa-rs/releases/download/c2patool-v${C2PATOOL_VERSION}/c2patool-v${C2PATOOL_VERSION}-x86_64-unknown-linux-gnu.tar.gz"
data = urllib.request.urlopen(url, timeout=120).read()
digest = hashlib.sha256(data).hexdigest()
if digest != "${C2PATOOL_SHA256}":
    sys.exit(f"c2patool checksum mismatch: {digest}")
with tarfile.open(fileobj=io.BytesIO(data)) as tar:
    member = next(m for m in tar.getmembers() if m.isfile() and m.name.rsplit("/", 1)[-1] == "c2patool")
    open("/usr/local/bin/c2patool", "wb").write(tar.extractfile(member).read())
EOF
RUN chmod 0755 /usr/local/bin/c2patool

# --------------------------------------------------------- ml-wheels -------
FROM base AS mlwheels
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN pip install Cython==3.3.1 -c constraints.txt && pip wheel --no-build-isolation --no-deps -w /wheels insightface==0.7.3

# --------------------------------------------------------------- worker -----
FROM base AS worker
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN apt-get update && apt-get install -y --no-install-recommends libimage-exiftool-perl ffmpeg mediainfo \
    && rm -rf /var/lib/apt/lists/*
COPY --from=c2patool /usr/local/bin/c2patool /usr/local/bin/c2patool
COPY --from=mlwheels /wheels /wheels
COPY requirements-ml.txt .
RUN pip install --index-url ${TORCH_INDEX} torch==2.5.1 torchvision==0.20.1 \
    && pip install --find-links /wheels -r requirements-ml.txt -c constraints.txt \
    && rm -rf /wheels
COPY app ./app
COPY alembic.ini .
USER 10001:10001
CMD ["celery", "-A", "app.workers.celery_app:celery_app", "worker", "--loglevel=INFO", \
     "--concurrency=1", "-Q", "cpu"]

# ----------------------------------------------------------------- test -----
FROM worker AS test
USER root
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt -c constraints.txt
COPY tests ./tests
COPY pyproject.toml .
RUN mkdir -p /work && chown 10001:10001 /work
USER 10001:10001
CMD ["pytest", "-q"]
