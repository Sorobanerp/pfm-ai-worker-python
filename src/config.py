"""12-Factor runtime configuration for pfm-ai-worker-python (all values overridable via env)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerConfig:
    kafka_bootstrap_servers: str
    kafka_group_id: str
    ai_rules_dsn: str
    gemini_api_key: str
    aws_endpoint_url: str
    worker_port: int


def load_config() -> WorkerConfig:
    return WorkerConfig(
        kafka_bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"),
        kafka_group_id=os.getenv("KAFKA_GROUP_ID", "pfm-ai-worker-group"),
        ai_rules_dsn=os.getenv("PFM_AI_RULES_DSN", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        aws_endpoint_url=os.getenv("AWS_ENDPOINT_URL", ""),
        worker_port=int(os.getenv("WORKER_PORT", "18400")),
    )
