"""12-Factor runtime configuration for pfm-ai-worker-python (all values overridable via env)."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkerConfig:
    kafka_bootstrap_servers: str
    kafka_group_id: str
    ai_rules_dsn: str
    gemini_api_key: str
    aws_endpoint_url: str
    worker_port: int
    app_env: str = "prod"
    dd_service: str = "pfm-ai-worker-python"
    dd_env: str = "prod"
    dd_version: str = "0.1.0"
    dd_logs_injection: bool = True
    dd_trace_sample_rate: float = 0.10
    otel_exporter_otlp_endpoint: str = "https://otel-collector.pfm.internal:4318"
    cloudwatch_logs_enabled: bool = False


def _load_dotenv_if_local(path: str = ".env.local") -> None:
    env_path = Path(path)
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        k = key.strip()
        v = val.strip().strip("'\"")
        if k and k not in os.environ:
            os.environ[k] = v


def load_config() -> WorkerConfig:
    if os.getenv("APP_ENV", "").strip().lower() == "local":
        _load_dotenv_if_local(".env.local")
    is_local = os.getenv("APP_ENV", "").strip().lower() == "local"
    default_kafka = "localhost:9092" if is_local else "localhost:19092"
    return WorkerConfig(
        kafka_bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", default_kafka),
        kafka_group_id=os.getenv("KAFKA_GROUP_ID", "pfm-ai-worker-group"),
        ai_rules_dsn=os.getenv("PFM_AI_RULES_DSN", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        aws_endpoint_url=os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566" if is_local else ""),
        worker_port=int(os.getenv("WORKER_PORT", "18400")),
        app_env=os.getenv("APP_ENV", "prod"),
        dd_service=os.getenv("DD_SERVICE", "pfm-ai-worker-python"),
        dd_env=os.getenv("DD_ENV", os.getenv("APP_ENV", "prod")),
        dd_version=os.getenv("DD_VERSION", "0.1.0"),
        dd_logs_injection=os.getenv("DD_LOGS_INJECTION", "true").strip().lower() == "true",
        dd_trace_sample_rate=float(os.getenv("DD_TRACE_SAMPLE_RATE", "1.0" if is_local else "0.10")),
        otel_exporter_otlp_endpoint=os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "http://localhost:4318" if is_local else "https://otel-collector.pfm.internal:4318",
        ),
        cloudwatch_logs_enabled=os.getenv("CLOUDWATCH_LOGS_ENABLED", "false").strip().lower() == "true",
    )
