# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=10 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Install the exact production dependency graph exported from uv.lock before
# copying application sources so normal code changes retain this cache layer.
COPY deploy/gongwen/requirements.lock /tmp/gongwen-requirements.lock
COPY deploy/gongwen/requirements-build.lock /tmp/gongwen-requirements-build.lock

RUN python -m venv /opt/gongwen-venv \
    && /opt/gongwen-venv/bin/pip install \
       --require-hashes \
       -r /tmp/gongwen-requirements-build.lock \
       -r /tmp/gongwen-requirements.lock

# Dockerfile.dockerignore keeps credentials, local databases, test artefacts
# and media outside this dedicated build without changing other build contexts.
COPY . .

RUN /opt/gongwen-venv/bin/pip install --no-deps --no-build-isolation .


FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="Yanzhang Gongwen Web" \
      org.opencontainers.image.description="Personal official-document writing web service" \
      org.opencontainers.image.version="0.1.0b1"

ENV PATH="/opt/gongwen-venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GONGWEN_DATA_DIR=/var/lib/gongwen \
    TZ=Asia/Shanghai

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 gongwen \
    && useradd --uid 10001 --gid 10001 \
       --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin gongwen \
    && install -d -o 10001 -g 10001 -m 0700 /var/lib/gongwen

COPY --from=builder /opt/gongwen-venv /opt/gongwen-venv

WORKDIR /app
USER 10001:10001

EXPOSE 8787
VOLUME ["/var/lib/gongwen"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import json, urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8787/api/ready', timeout=3)); assert data.get('ok') is True"]

CMD ["python", "-m", "gongwen_web.app", "--host", "0.0.0.0", "--port", "8787"]
