FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

COPY bot/requirements.txt /app/requirements.txt

# IMPORTANT:
# - do NOT use --no-cache-dir (we want retries + cached wheels)
# - Network can be flaky; avoid upgrading pip during image build (extra network hop).
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --retries 25 --timeout 240 -r /app/requirements.txt \
    && python -m pip check

COPY bot /app/bot
COPY shared /app/shared

CMD ["python", "-m", "bot.app"]
