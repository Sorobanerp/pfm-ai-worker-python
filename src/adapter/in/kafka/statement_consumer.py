"""Kafka Consumer for topic `statement.raw.extracted`."""

import json
import logging
from typing import Any

from confluent_kafka import Consumer, KafkaError

from src.application.pipeline_service import ThreeLayerCategorizationService
from src.domain.models import CategorizedTransaction, RawTransaction

logger = logging.getLogger(__name__)

RAW_EXTRACTED_TOPIC = "statement.raw.extracted"


class StatementRawExtractedConsumer:
    """Consumes raw extracted transactions from `statement.raw.extracted` and invokes the 3-layer pipeline."""

    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        pipeline_service: ThreeLayerCategorizationService,
        topic: str = RAW_EXTRACTED_TOPIC,
    ) -> None:
        self._pipeline_service = pipeline_service
        self._topic = topic
        self._consumer = Consumer(
            {
                "bootstrap.servers": bootstrap_servers,
                "group.id": group_id,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )

    def handle_payload(self, payload_bytes: bytes | str) -> list[CategorizedTransaction]:
        """Parse either a single transaction event or a batch statement event and process each item."""
        data: dict[str, Any] = (
            json.loads(payload_bytes.decode("utf-8"))
            if isinstance(payload_bytes, bytes)
            else json.loads(payload_bytes)
        )

        # Support both single transaction payload and batch statement payload with `transactions` list
        if "transactions" in data and isinstance(data["transactions"], list):
            results: list[CategorizedTransaction] = []
            tenant_id = data.get("tenant_id", "")
            statement_id = data.get("statement_id", "")
            card_last4 = data.get("card_last4", "0000")
            competence_date = data.get("competence_date")
            for item in data["transactions"]:
                merged = {
                    "tenant_id": tenant_id,
                    "statement_id": statement_id,
                    "card_last4": card_last4,
                    "competence_date": competence_date,
                    **item,
                }
                raw_tx = RawTransaction.model_validate(merged)
                results.append(self._pipeline_service.categorize_transaction(raw_tx))
            return results

        raw_tx = RawTransaction.model_validate(data)
        return [self._pipeline_service.categorize_transaction(raw_tx)]

    def poll_once(self, timeout: float = 1.0) -> list[CategorizedTransaction]:
        """Poll a single message from Kafka, process through the 3-layer pipeline, and commit offset."""
        msg = self._consumer.poll(timeout=timeout)
        if msg is None:
            return []
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                logger.error("Kafka consumer error: %s", msg.error())
            return []

        try:
            processed = self.handle_payload(msg.value())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Malformed event routed to DLQ handling / skipped safely: %s", exc)
            self._consumer.commit(message=msg, asynchronous=False)
            return []
        self._consumer.commit(message=msg, asynchronous=False)
        return processed

    def subscribe(self) -> None:
        self._consumer.subscribe([self._topic])

    def close(self) -> None:
        self._consumer.close()
