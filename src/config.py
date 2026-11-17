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
        ai_rules_dsn=os.getenv(
            "PFM_AI_RULES_DSN",
            "postgresql://pfm_ai_user:pfm_ai_pass@localhost:15433/pfm_ai_rules",
        ),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "dummy-local-key"),
        aws_endpoint_url=os.getenv("AWS_ENDPOINT_URL", "http://localhost:14566"),
        worker_port=int(os.getenv("WORKER_PORT", "18400")),
    )
