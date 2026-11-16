# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    librdkafka-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel && \
    /opt/venv/bin/pip install --no-cache-dir .

FROM gcr.io/distroless/python3-debian12:nonroot
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/src /app/src

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app:/opt/venv/lib/python3.12/site-packages" \
    PYTHONUNBUFFERED=1

USER nonroot:nonroot
ENTRYPOINT ["/opt/venv/bin/python", "-m", "src.main"]
