"""Continuous Kafka Worker Entrypoint for Kubernetes / KEDA Hyperscale (ADR-008 / ADR-009)."""

from __future__ import annotations

import logging
import os
import signal
from typing import Any

from .kafka.statement_consumer import (
    RAW_EXTRACTED_TOPIC,
    StatementRawExtractedConsumer,
)
from src.application.pipeline_service import ThreeLayerCategorizationService

logger = logging.getLogger(__name__)


class KafkaWorkerRunner:
    """Continuous polling runner for Kubernetes/KEDA horizontal scaling."""

    def __init__(
        self,
        consumer: StatementRawExtractedConsumer,
        poll_timeout: float = 1.0,
    ) -> None:
        self._consumer = consumer
        self._poll_timeout = poll_timeout
        self._running = False

    def stop(self, *_args: Any) -> None:
        logger.info("Stopping KafkaWorkerRunner gracefully...")
        self._running = False

    def run(self, max_iterations: int | None = None) -> int:
        self._consumer.subscribe()
        self._running = True
        iterations = 0
        processed_total = 0

        try:
            while self._running:
                batch = self._consumer.poll_once(timeout=self._poll_timeout)
                processed_total += len(batch)
                iterations += 1
                if max_iterations is not None and iterations >= max_iterations:
                    break
        finally:
            self._consumer.close()

        return processed_total


def main(pipeline_service: ThreeLayerCategorizationService | None = None) -> None:  # pragma: no cover
    if pipeline_service is None:
        raise ValueError("pipeline_service must be provided by composition root")

    brokers = os.getenv("KAFKA_BROKERS", "localhost:19092")
    group_id = os.getenv("KAFKA_GROUP_ID", "pfm-ai-worker-group")
    topic = os.getenv("KAFKA_RAW_TOPIC", RAW_EXTRACTED_TOPIC)

    consumer = StatementRawExtractedConsumer(
        bootstrap_servers=brokers,
        group_id=group_id,
        pipeline_service=pipeline_service,
        topic=topic,
    )
    runner = KafkaWorkerRunner(consumer=consumer)
    signal.signal(signal.SIGTERM, runner.stop)
    signal.signal(signal.SIGINT, runner.stop)
    runner.run()
