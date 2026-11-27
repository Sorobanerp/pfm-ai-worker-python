"""OpenTelemetry OTLP configuration, W3C traceparent propagation, and LGPD PII sanitizer."""

from __future__ import annotations

import json
import os
import re
import secrets
import urllib.parse
from dataclasses import dataclass

DEFAULT_OTLP_ENDPOINT = "https://otel-collector.pfm.internal:4318"
DEFAULT_SERVICE_NAME = "pfm-ai-worker-python"

_CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-\d{2}\b|\b\d{11}\b")
_CPF_KV_RE = re.compile(r'(?i)("?cpf"?\s*[:=]\s*"?)([^"\s,}]+)("?)')
_PAN_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
_CARD_KV_RE = re.compile(r'(?i)("?(?:card_?number|pan)"?\s*[:=]\s*"?)([^"\s,}]+)("?)')
_PASS_RE = re.compile(
    r'(?i)("?(?:pdf_?password|password|token|access_?token|refresh_?token|secret|api_?key|authorization)"?\s*[:=]\s*"?)([^"\s,}]+)("?)'
)
_NFCE_KEY_44_RE = re.compile(r"^\d{44}$")
_W3C_RE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")
_ALLOWED_SEFAZ_SUFFIXES = (".gov.br", ".sefaz.gov.br", ".fazenda.gov.br")
_BLOCKED_SSRF_HOSTS = ("169.254.169.254", "127.0.0.1", "localhost", "0.0.0.0", "[::1]", "metadata.google.internal")


def validate_pdf_magic_bytes_in_ram(payload: bytes | bytearray | memoryview) -> bool:
    """Strictly validate %PDF- magic bytes in RAM buffer before parsing (OWASP A04/A05)."""
    if not payload or len(payload) < 5:
        raise ValueError("Invalid PDF payload in RAM: missing %PDF- magic bytes header")
    header = bytes(payload[:5])
    if header != b"%PDF-":
        raise ValueError("Invalid PDF payload in RAM: must start with %PDF- magic bytes")
    return True


def validate_nfce_access_key(access_key: str) -> str:
    """Strictly validate 44-digit numeric SEFAZ NFC-e access key (OWASP A03/A04)."""
    cleaned = (access_key or "").strip()
    if not _NFCE_KEY_44_RE.match(cleaned):
        raise ValueError("Invalid NFC-e access key: must contain strictly 44 numeric digits")
    return cleaned


def validate_external_url_no_ssrf(url: str) -> str:
    """Block arbitrary external URLs, cloud metadata (169.254.169.254) and private IPs (OWASP A10 SSRF)."""
    cleaned = (url or "").strip()
    parsed = urllib.parse.urlparse(cleaned)
    if parsed.scheme not in ("https",):
        raise ValueError("SSRF blocked: only HTTPS scheme is permitted for external SEFAZ/fiscal URLs")
    host = (parsed.hostname or "").lower()
    if not host or host in _BLOCKED_SSRF_HOSTS or host.startswith(("10.", "192.168.", "172.16.", "169.254.")):
        raise ValueError(f"SSRF blocked: internal or metadata host '{host}' is forbidden")
    if not host.endswith(_ALLOWED_SEFAZ_SUFFIXES):
        raise ValueError(f"SSRF blocked: untrusted external domain '{host}' (only *.gov.br allowed)")
    return cleaned


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
    masked = _CARD_KV_RE.sub(r"\1[PAN_MASKED]\3", masked)
    masked = _CPF_KV_RE.sub(r"\1[CPF_MASKED]\3", masked)
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
