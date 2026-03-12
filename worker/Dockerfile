FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    rm -f /var/lib/apt/lists/lock /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock || true \
    && apt-get update \
    && apt-get install -y --no-install-recommends gcc fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY worker/requirements.txt /app/requirements.txt

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --retries 20 --timeout 240 -r /app/requirements.txt \
    && python -m pip check

COPY worker /app/worker
COPY api /app/api
COPY shared /app/shared

CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=INFO"]

