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
    )
