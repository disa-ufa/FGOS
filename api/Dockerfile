FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

# System deps
# NOTE: Do NOT cache /var/lib/apt (it can persist stale lock files across failed builds).
RUN --mount=type=cache,target=/var/cache/apt \
    rm -f /var/lib/apt/lists/lock /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock || true \
    && apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt /app/requirements.txt

# IMPORTANT: do NOT use --no-cache-dir here; we use BuildKit cache mount for pip.
# Network can be flaky; avoid upgrading pip during image build (extra network hop).
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --retries 20 --timeout 240 -r /app/requirements.txt \
    && python -m pip check

COPY api /app/api
COPY shared /app/shared

RUN chmod +x /app/api/scripts/entrypoint.sh

CMD ["/app/api/scripts/entrypoint.sh"]
