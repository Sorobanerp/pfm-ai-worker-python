"""AWS Lambda Arm64 Serverless Entrypoint (ADR-009).

Zero direct PostgreSQL connections: operates exclusively via hexagonal ports,
reading event batches (Kafka/Upstash Event Source, SQS, or direct invocation)
and publishing categorized events to `tx.categorized` or returning them for gRPC delivery.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from src.application.pipeline_service import ThreeLayerCategorizationService
from src.application.ports import (
    CategorizedEventPublisherPort,
    LlmClassificationResponse,
    LlmClassifierPort,
    TenantRuleRepositoryPort,
)
from src.domain.models import CategorizedTransaction, LearnedRule, RawTransaction
from src.domain.taxonomy import CategoryCode, CategoryGroup

logger = logging.getLogger(__name__)


class InMemoryZeroDbRuleRepository(TenantRuleRepositoryPort):
    """ADR-009 compliant rule repository: zero PostgreSQL/SQL connections inside Lambda."""

    def __init__(self) -> None:
        self._rules: dict[tuple[str, str], LearnedRule] = {}

    def find_matching_rule(self, tenant_id: str, merchant_clean: str) -> LearnedRule | None:
        return self._rules.get((tenant_id, merchant_clean))

    def upsert_learned_rule(self, rule: LearnedRule) -> LearnedRule:
        self._rules[(rule.tenant_id, rule.merchant_pattern)] = rule
        return rule


class FallbackLlmClassifier(LlmClassifierPort):
    """Graceful degradation LLM adapter when external LLM key is absent or in offline mode."""

    def classify_merchant(
        self,
        tenant_id: str,
        raw_description: str,
        merchant_clean: str,
        city: str | None,
        amount_str: str,
    ) -> LlmClassificationResponse:
        return LlmClassificationResponse(
            category_group=CategoryGroup.SYSTEM_CONTROL,
            category_code=CategoryCode.SYS_UNCLASSIFIED,
            merchant_clean=merchant_clean or "UNKNOWN",
            confidence=0.50,
            reasoning="Serverless fallback without external LLM call",
        )


class CollectingEventPublisher(CategorizedEventPublisherPort):
    """Collects categorized transactions for `tx.categorized` Kafka or gRPC forwarding."""

    def __init__(self, downstream_publisher: CategorizedEventPublisherPort | None = None) -> None:
        self._downstream = downstream_publisher
        self.published: list[CategorizedTransaction] = []

    def publish_categorized(self, tx: CategorizedTransaction) -> None:
        self.published.append(tx)
        if self._downstream is not None:
            self._downstream.publish_categorized(tx)


def _decode_record_payload(raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        try:
            decoded = base64.b64decode(raw_value, validate=True).decode("utf-8")
            return json.loads(decoded)
        except Exception:
            return json.loads(raw_value)
    raise ValueError(f"Unsupported event payload type: {type(raw_value).__name__}")


def _extract_raw_transactions(event: dict[str, Any]) -> list[RawTransaction]:
    items: list[dict[str, Any]] = []

    # 1. Kafka / Upstash Event Source Mapping (`records`: { "topic-0": [ { "value": ... } ] })
    if "records" in event and isinstance(event["records"], dict):
        for partition_records in event["records"].values():
            for rec in partition_records:
                payload = _decode_record_payload(rec.get("value", "{}"))
                items.extend(_flatten_payload(payload))
    # 2. AWS SQS Event (`Records`: [ { "body": "..." } ])
    elif "Records" in event and isinstance(event["Records"], list):
        for rec in event["Records"]:
            payload = _decode_record_payload(rec.get("body", "{}"))
            items.extend(_flatten_payload(payload))
    # 3. Direct invocation (single tx or batch `transactions`)
    else:
        items.extend(_flatten_payload(event))

    return [RawTransaction.model_validate(item) for item in items]


def _flatten_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    if "transactions" in data and isinstance(data["transactions"], list):
        tenant_id = data.get("tenant_id", "")
        statement_id = data.get("statement_id", "")
        card_last4 = data.get("card_last4", "0000")
        competence_date = data.get("competence_date")
        return [
            {
                "tenant_id": tenant_id,
                "statement_id": statement_id,
                "card_last4": card_last4,
                "competence_date": competence_date,
                **tx,
            }
            for tx in data["transactions"]
        ]
    return [data]


_CACHED_SERVICE: ThreeLayerCategorizationService | None = None
_CACHED_COLLECTOR: CollectingEventPublisher | None = None


def _get_service(
    publisher: CategorizedEventPublisherPort | None = None,
    llm_classifier: LlmClassifierPort | None = None,
) -> tuple[ThreeLayerCategorizationService, CollectingEventPublisher]:
    global _CACHED_SERVICE, _CACHED_COLLECTOR
    if publisher is not None or llm_classifier is not None or _CACHED_SERVICE is None:
        collector = CollectingEventPublisher(downstream_publisher=publisher)
        service = ThreeLayerCategorizationService(
            rule_repository=InMemoryZeroDbRuleRepository(),
            llm_classifier=llm_classifier or FallbackLlmClassifier(),
            event_publisher=collector,
        )
        if publisher is None and llm_classifier is None:
            _CACHED_SERVICE = service
            _CACHED_COLLECTOR = collector
        return service, collector
    assert _CACHED_COLLECTOR is not None
    _CACHED_COLLECTOR.published.clear()
    return _CACHED_SERVICE, _CACHED_COLLECTOR


def handler(
    event: dict[str, Any],
    context: Any = None,
    *,
    publisher: CategorizedEventPublisherPort | None = None,
    llm_classifier: LlmClassifierPort | None = None,
) -> dict[str, Any]:
    """AWS Lambda Arm64 handler (ADR-009): categorizes transactions without PostgreSQL access."""
    service, collector = _get_service(publisher=publisher, llm_classifier=llm_classifier)
    raw_transactions = _extract_raw_transactions(event)

    categorized = [service.categorize_transaction(tx) for tx in raw_transactions]
    return {
        "statusCode": 200,
        "topic": os.getenv("TX_CATEGORIZED_TOPIC", "tx.categorized"),
        "processedCount": len(categorized),
        "events": [tx.model_dump(mode="json") for tx in collector.published],
    }
