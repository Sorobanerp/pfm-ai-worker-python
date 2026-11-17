"""Kafka Producer for topic `tx.categorized` partitioned by `tenant_id`."""

from confluent_kafka import Producer

from src.domain.models import CategorizedTransaction

TX_CATEGORIZED_TOPIC = "tx.categorized"


class KafkaCategorizedEventProducer:
    """Publishes `CategorizedTransaction` events to `tx.categorized` keyed by `tenant_id`."""

    def __init__(
        self,
        bootstrap_servers: str = "localhost:19092",
        topic: str = TX_CATEGORIZED_TOPIC,
    ) -> None:
        self._topic = topic
        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "acks": "all",
                "enable.idempotence": True,
            }
        )

    def publish_categorized(self, tx: CategorizedTransaction) -> None:
        payload = tx.model_dump_json().encode("utf-8")
        key = tx.tenant_id.encode("utf-8")
        self._producer.produce(
            topic=self._topic,
            key=key,
            value=payload,
            headers=[
                ("tenant_id", key),
                ("idempotency_key", tx.idempotency_key.encode("utf-8")),
                ("categorization_source", tx.categorization_source.value.encode("utf-8")),
            ],
        )
        self._producer.poll(0)

    def flush(self, timeout: float = 5.0) -> None:
        self._producer.flush(timeout)
