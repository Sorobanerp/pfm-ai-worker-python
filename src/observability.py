"""OpenTelemetry OTLP configuration, W3C traceparent propagation, and LGPD PII sanitizer."""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass

DEFAULT_OTLP_ENDPOINT = "http://datadog-agent.monitoring.svc.cluster.local:4318"
DEFAULT_SERVICE_NAME = "pfm-ai-worker-python"

_CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-\d{2}\b|\b\d{11}\b")
_PAN_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
_PASS_RE = re.compile(r'(?i)("?(?:pdf_?password|password)"?\s*[:=]\s*"?)([^"\s,}]+)("?)')
_W3C_RE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


@dataclass(frozen=True)
class OtlpRuntimeConfig:
    service_name: str
    endpoint: str
    noop: bool
    logs_injection: bool


def init_otel_config() -> OtlpRuntimeConfig:
    svc = os.getenv("OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME).strip() or DEFAULT_SERVICE_NAME
    ep = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    noop = not ep or ep.lower() == "noop"
    resolved_ep = DEFAULT_OTLP_ENDPOINT if noop else ep
    logs_inj = os.getenv("DD_LOGS_INJECTION", "true").strip().lower() != "false"
    return OtlpRuntimeConfig(
        service_name=svc,
        endpoint=resolved_ep,
        noop=noop,
        logs_injection=logs_inj,
    )


def ensure_traceparent(incoming: str | None = None) -> str:
    if incoming and _W3C_RE.match(incoming.strip()):
        return incoming.strip()
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"


def mask_sensitive_pii(raw: str) -> str:
    if not raw:
        return ""
    masked = _PASS_RE.sub(r"\1[REDACTED]\3", raw)
    masked = _PAN_RE.sub("[PAN_MASKED]", masked)
    masked = _CPF_RE.sub("[CPF_MASKED]", masked)
    return masked


def format_structured_json_log(
    level: str, message: str, traceparent: str | None = None
) -> str:
    tp = ensure_traceparent(traceparent)
    parts = tp.split("-")
    lvl = (level or "INFO").strip().upper() or "INFO"
    payload = {
        "level": lvl,
        "dd.service": DEFAULT_SERVICE_NAME,
        "dd.env": "production",
        "dd.version": "0.1.0",
        "dd.trace_id": parts[1],
        "dd.span_id": parts[2],
        "traceparent": tp,
        "message": mask_sensitive_pii(message),
    }
    return json.dumps(payload)
