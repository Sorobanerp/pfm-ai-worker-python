"""Entrypoint wiring Hexagonal Adapters into the 3-Layer Categorization Worker."""

import importlib
import logging
import signal
import sys

from src.adapter.out.gemini.gemini_classifier import GeminiStructuredClassifierAdapter
from src.adapter.out.kafka.categorized_producer import KafkaCategorizedEventProducer
from src.adapter.out.postgres.tenant_rule_repository import (
    PostgresTenantRuleRepository,
)
from src.application.pipeline_service import ThreeLayerCategorizationService
from src.config import load_config
from src.health import start_health_server

_kafka_in_mod = importlib.import_module("src.adapter.in.kafka.statement_consumer")
StatementRawExtractedConsumer = _kafka_in_mod.StatementRawExtractedConsumer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("pfm-ai-worker")


def main() -> None:
    cfg = load_config()
    bootstrap_servers = cfg.kafka_bootstrap_servers
    group_id = cfg.kafka_group_id
    postgres_dsn = cfg.ai_rules_dsn
    gemini_api_key = cfg.gemini_api_key
    start_health_server(cfg.worker_port)

    rule_repo = PostgresTenantRuleRepository(dsn=postgres_dsn)
    llm_adapter = GeminiStructuredClassifierAdapter(api_key=gemini_api_key)
    producer = KafkaCategorizedEventProducer(bootstrap_servers=bootstrap_servers)

    pipeline_service = ThreeLayerCategorizationService(
        rule_repository=rule_repo,
        llm_classifier=llm_adapter,
        event_publisher=producer,
    )

    consumer = StatementRawExtractedConsumer(
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        pipeline_service=pipeline_service,
    )
    consumer.subscribe()

    running = True

    def _shutdown(signum: int, _frame: object) -> None:
        nonlocal running
        logger.info("Received signal %s, shutting down gracefully...", signum)
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("pfm-ai-worker-python started and listening on statement.raw.extracted")
    try:
        while running:
            consumer.poll_once(timeout=1.0)
    finally:
        consumer.close()
        producer.flush()
        sys.exit(0)


if __name__ == "__main__":
    main()
