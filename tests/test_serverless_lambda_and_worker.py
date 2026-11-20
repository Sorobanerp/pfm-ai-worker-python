"""Tests for ADR-009 Serverless Lambda Arm64 Handler and K8s/KEDA Kafka Worker."""

import base64
import importlib
import json
import sys
from unittest.mock import MagicMock

import pytest

from src.domain.models import LearnedRule
from src.domain.taxonomy import CategoryCode, CategoryGroup

lambda_mod = importlib.import_module("src.adapter.in.lambda_handler")
kafka_worker_mod = importlib.import_module("src.adapter.in.kafka_worker")


def _sample_tx(key: str = "idem-key-0001") -> dict:
    return {
        "idempotency_key": key,
        "tenant_id": "11111111-1111-4111-8111-111111111111",
        "statement_id": "stmt-001",
        "card_last4": "4242",
        "transaction_date": "2026-11-10",
        "competence_date": "2026-11-10",
        "raw_description": "UBER *TRIP HELP.UBER.COM",
        "amount": "34.9000",
    }


def test_lambda_handler_direct_and_zero_postgres_invariant() -> None:
    res = lambda_mod.handler(_sample_tx("idem-direct-001"))
    assert res["statusCode"] == 200
    assert res["topic"] == "tx.categorized"
    assert res["processedCount"] == 1
    assert len(res["events"]) == 1

    # ADR-009: Lambda handler must never import PostgreSQL drivers
    from pathlib import Path
    lambda_source = Path(lambda_mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("psycopg", "psycopg2", "sqlalchemy", "asyncpg"):
        assert forbidden not in lambda_source


def test_lambda_handler_kafka_base64_and_sqs_events() -> None:
    downstream = MagicMock()
    payload = {"transactions": [_sample_tx("idem-kafka-001"), _sample_tx("idem-kafka-002")], "tenant_id": "11111111-1111-4111-8111-111111111111", "statement_id": "stmt-002", "card_last4": "1234", "competence_date": "2026-11-10"}
    b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

    kafka_event = {"records": {"statement.raw.extracted-0": [{"value": b64}]}}
    res_kafka = lambda_mod.handler(kafka_event, publisher=downstream)
    assert res_kafka["processedCount"] == 2
    assert downstream.publish_categorized.call_count == 2

    sqs_event = {"Records": [{"body": json.dumps(_sample_tx("idem-sqs-001"))}]}
    res_sqs = lambda_mod.handler(sqs_event)
    assert res_sqs["processedCount"] == 1


def test_in_memory_rule_repo_and_fallback_llm() -> None:
    repo = lambda_mod.InMemoryZeroDbRuleRepository()
    rule = LearnedRule(
        tenant_id="t1",
        merchant_pattern="PADARIA CENTRAL",
        category_group=CategoryGroup.VARIABLE_LIFESTYLE,
        category_code=CategoryCode.VAR_FOOD_RESTAURANT,
    )
    repo.upsert_learned_rule(rule)
    assert repo.find_matching_rule("t1", "PADARIA CENTRAL") == rule
    assert repo.find_matching_rule("t1", "OTHER") is None

    llm = lambda_mod.FallbackLlmClassifier()
    resp = llm.classify_merchant("t1", "DESC", "MERCHANT", None, "10.0000")
    assert resp.category_code == CategoryCode.SYS_UNCLASSIFIED

    with pytest.raises(ValueError):
        lambda_mod._decode_record_payload(12345)


def test_kafka_worker_runner_polling_and_shutdown() -> None:
    mock_consumer = MagicMock()
    mock_consumer.poll_once.side_effect = [["tx1"], []]

    runner = kafka_worker_mod.KafkaWorkerRunner(consumer=mock_consumer, poll_timeout=0.1)
    total = runner.run(max_iterations=2)

    assert total == 1
    mock_consumer.subscribe.assert_called_once()
    assert mock_consumer.poll_once.call_count == 2
    mock_consumer.close.assert_called_once()

    runner.stop()
    assert runner._running is False
