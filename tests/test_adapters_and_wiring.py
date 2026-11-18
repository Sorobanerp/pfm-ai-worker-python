"""Comprehensive pure unit test suite covering adapters, config, health, resilience, and main."""

import importlib
import json
import time
import urllib.request
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.adapter.out.gemini.gemini_classifier import GeminiStructuredClassifierAdapter
from src.adapter.out.kafka.categorized_producer import KafkaCategorizedEventProducer
from src.adapter.out.postgres.tenant_rule_repository import (
    PostgresTenantRuleRepository,
)
from src.application.pipeline_service import ThreeLayerCategorizationService
from src.application.ports import LlmClassificationResponse
from src.application.resilience import CircuitBreaker, CircuitBreakerOpenError
from src.config import WorkerConfig, load_config
from src.domain.models import (
    CategorizationSource,
    CategorizedTransaction,
    LearnedRule,
    RawTransaction,
)
from src.domain.taxonomy import CategoryCode, CategoryGroup
from src.health import start_health_server
from src.observability import (
    DEFAULT_OTLP_ENDPOINT,
    ensure_traceparent,
    format_structured_json_log,
    init_otel_config,
    mask_sensitive_pii,
)

_kafka_in_mod = importlib.import_module("src.adapter.in.kafka.statement_consumer")
StatementRawExtractedConsumer = _kafka_in_mod.StatementRawExtractedConsumer


# 1. Config Tests
def test_load_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    monkeypatch.delenv("KAFKA_GROUP_ID", raising=False)
    monkeypatch.delenv("WORKER_PORT", raising=False)
    cfg = load_config()
    assert isinstance(cfg, WorkerConfig)
    assert cfg.kafka_bootstrap_servers == "localhost:19092"
    assert cfg.worker_port == 18400


# 2. Health Server Tests
def test_health_server_endpoints() -> None:
    server = start_health_server(0)
    port = server.server_address[1]

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        assert data["status"] == "UP"

    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/not_found")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404

    server.shutdown()


# 3. Gemini Classifier Adapter Tests
def test_gemini_classifier_adapter() -> None:
    with patch("src.adapter.out.gemini.gemini_classifier.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "category_group": "VARIABLE_LIFESTYLE",
            "category_code": "VAR_FOOD_RESTAURANT",
            "confidence": 0.95,
            "merchant_clean": "BURGER KING",
            "reasoning": "Fast food burger chain",
        })
        mock_client.models.generate_content.return_value = mock_response

        adapter = GeminiStructuredClassifierAdapter(api_key="fake-key")
        res = adapter.classify_merchant(
            tenant_id="t-1",
            raw_description="BK SHOPPING",
            merchant_clean="BK",
            city="SAO PAULO",
            amount_str="45.9000",
        )
        assert isinstance(res, LlmClassificationResponse)
        assert res.category_code == CategoryCode.VAR_FOOD_RESTAURANT
        assert res.confidence == 0.95

        mock_response.text = None
        with pytest.raises(ValueError, match="Empty structured response"):
            adapter.classify_merchant("t-1", "desc", "merch", None, "10.00")


# 4. Kafka Producer Tests
def test_kafka_categorized_producer() -> None:
    with patch("src.adapter.out.kafka.categorized_producer.Producer") as mock_prod_cls:
        mock_producer = MagicMock()
        mock_prod_cls.return_value = mock_producer

        producer = KafkaCategorizedEventProducer(bootstrap_servers="localhost:9092")
        tx = CategorizedTransaction(
            idempotency_key="idemp-12345678",  # gitleaks:allow
            tenant_id="tenant-1",
            statement_id="stmt-1",
            card_last4="1234",
            transaction_date="2026-04-10",
            competence_date="2026-04-10",
            raw_description="UBER",
            merchant_normalized="UBER",
            city=None,
            acquirer_prefix=None,
            amount=Decimal("35.50"),
            installment_current=1,
            installment_total=1,
            category_group=CategoryGroup.VARIABLE_LIFESTYLE,
            category_code=CategoryCode.VAR_MOBILITY_APP,
            confidence=1.0,
            categorization_source=CategorizationSource.LAYER_1_TENANT_RULE,
            requires_inbox_review=False,
        )

        producer.publish_categorized(tx)
        assert mock_producer.produce.called
        assert mock_producer.poll.called

        producer.flush(1.0)
        assert mock_producer.flush.called


# 5. Postgres Tenant Rule Repository Tests
def test_postgres_tenant_rule_repository() -> None:
    with patch("src.adapter.out.postgres.tenant_rule_repository.psycopg.connect") as mock_conn_fn:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn_fn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchone.return_value = {
            "tenant_id": "tenant-1",
            "merchant_pattern": "PADARIA CENTRAL",
            "category_code": "VAR_FOOD_GROCERY",
            "category_group": "VARIABLE_LIFESTYLE",
            "confidence": 1.0,
            "updated_at": "2026-04-10T10:00:00Z",
        }

        repo = PostgresTenantRuleRepository("fake-dsn")
        rule = repo.find_matching_rule("tenant-1", "PADARIA CENTRAL")
        assert rule is not None
        assert rule.category_code == CategoryCode.VAR_FOOD_GROCERY

        mock_cur.fetchone.return_value = None
        assert repo.find_matching_rule("tenant-1", "UNKNOWN") is None

        new_rule = LearnedRule(
            tenant_id="tenant-1",
            merchant_pattern="PADARIA CENTRAL",
            category_code=CategoryCode.VAR_FOOD_GROCERY,
            category_group=CategoryGroup.VARIABLE_LIFESTYLE,
            confidence=1.0,
            updated_at="2026-04-10T10:00:00Z",
        )
        saved = repo.upsert_learned_rule(new_rule)
        assert saved == new_rule
        assert mock_cur.execute.called


# 6. Kafka Consumer Tests
def test_statement_consumer_single_and_batch() -> None:
    mock_pipeline = MagicMock()
    mock_tx = MagicMock()
    mock_pipeline.categorize_transaction.return_value = mock_tx

    with patch("src.adapter.in.kafka.statement_consumer.Consumer") as mock_cons_cls:
        mock_consumer = MagicMock()
        mock_cons_cls.return_value = mock_consumer

        consumer = StatementRawExtractedConsumer(
            bootstrap_servers="localhost:9092",
            group_id="grp",
            pipeline_service=mock_pipeline,
        )

        single_payload = json.dumps({
            "tenant_id": "tenant-1",
            "statement_id": "stmt-1",
            "idempotency_key": "idemp-12345678",  # gitleaks:allow
            "card_last_four": "1234",
            "transaction_date": "2026-04-10",
            "competence_date": "2026-04-10",
            "raw_description": "PADARIA",
            "merchant_normalized": "PADARIA",
            "amount": "25.0000",
            "currency": "BRL",
            "installment_number": 1,
            "total_installments": 1,
            "kind": "PURCHASE",
            "occurred_at": "2026-04-10T10:00:00Z",
        }).encode("utf-8")

        res_single = consumer.handle_payload(single_payload)
        assert len(res_single) == 1

        batch_payload = json.dumps({
            "tenant_id": "tenant-1",
            "statement_id": "stmt-1",
            "competence_date": "2026-04-10",
            "transactions": [
                {
                    "idempotency_key": "idemp-batch-1",
                    "transaction_date": "2026-04-10",
                    "raw_description": "MERCADO",
                    "amount": "100.00",
                }
            ],
        })
        res_batch = consumer.handle_payload(batch_payload)
        assert len(res_batch) == 1

        mock_msg = MagicMock()
        mock_msg.error.return_value = None
        mock_msg.value.return_value = single_payload
        mock_consumer.poll.return_value = mock_msg

        polled = consumer.poll_once(1.0)
        assert len(polled) == 1
        assert mock_consumer.commit.called

        mock_consumer.poll.return_value = None
        assert consumer.poll_once(1.0) == []

        consumer.subscribe()
        assert mock_consumer.subscribe.called

        consumer.close()
        assert mock_consumer.close.called


# 7. Pipeline Service Gemini Success Branch
def test_pipeline_service_gemini_success() -> None:
    mock_repo = MagicMock()
    mock_repo.find_matching_rule.return_value = None

    mock_llm = MagicMock()
    mock_llm.classify_merchant.return_value = LlmClassificationResponse(
        category_group=CategoryGroup.VARIABLE_LIFESTYLE,
        category_code=CategoryCode.VAR_FOOD_GROCERY,
        confidence=0.92,
        merchant_clean="HIPERMERCADO NOVO",
        reasoning="Supermarket retail",
    )

    mock_pub = MagicMock()

    service = ThreeLayerCategorizationService(
        rule_repository=mock_repo,
        llm_classifier=mock_llm,
        event_publisher=mock_pub,
    )

    raw_tx = RawTransaction(
        idempotency_key="idemp-gem-12345678",
        tenant_id="tenant-1",
        statement_id="stmt-1",
        card_last4="1234",
        transaction_date="2026-04-10",
        competence_date="2026-04-10",
        raw_description="CONSULTORIA XYZ TECH ADVISORY",
        amount=Decimal("150.00"),
    )

    categorized = service.categorize_transaction(raw_tx)
    assert categorized.category_code == CategoryCode.VAR_FOOD_GROCERY
    assert categorized.categorization_source == CategorizationSource.LAYER_3_GEMINI_LLM
    assert not categorized.requires_inbox_review
    assert mock_pub.publish_categorized.called


# 8. Resilience Unit Tests
def test_resilience_circuit_breaker_transitions() -> None:
    caller = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=0.05,
        max_retries=1,
        call_timeout_seconds=0.1,
    )

    assert caller.state == "CLOSED"

    def slow_func() -> str:
        time.sleep(0.3)
        return "slow"

    with pytest.raises(TimeoutError):
        caller.execute(slow_func)

    def failing_func() -> str:
        raise RuntimeError("network failure")

    with pytest.raises(RuntimeError):
        caller.execute(failing_func)

    assert caller.state == "OPEN"
    with pytest.raises(CircuitBreakerOpenError):
        caller.execute(lambda: "blocked")

    time.sleep(0.08)
    assert caller.state == "HALF_OPEN"

    res = caller.execute(lambda: "success")
    assert res == "success"
    assert caller.state == "CLOSED"


# 9. Main Function Graceful Shutdown Test
def test_main_graceful_shutdown() -> None:
    with (
        patch("src.main.load_config") as mock_cfg,
        patch("src.main.start_health_server"),
        patch("src.main.PostgresTenantRuleRepository"),
        patch("src.main.GeminiStructuredClassifierAdapter"),
        patch("src.main.KafkaCategorizedEventProducer") as mock_prod_cls,
        patch("src.main.ThreeLayerCategorizationService"),
        patch("src.main.StatementRawExtractedConsumer") as mock_cons_cls,
    ):
        mock_cfg.return_value = WorkerConfig(
            kafka_bootstrap_servers="localhost:9092",
            kafka_group_id="grp",
            ai_rules_dsn="dsn",
            gemini_api_key="key",
            aws_endpoint_url="http://localhost:4566",
            worker_port=0,
        )
        mock_consumer = MagicMock()
        mock_cons_cls.return_value = mock_consumer
        mock_producer = MagicMock()
        mock_prod_cls.return_value = mock_producer

        import src.main as worker_main

        mock_consumer.poll_once.side_effect = KeyboardInterrupt()

        with pytest.raises(SystemExit):
            worker_main.main()

        assert mock_consumer.close.called
        assert mock_producer.flush.called


def test_observability_and_lgpd_sanitizer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    cfg = init_otel_config()
    assert cfg.noop is True
    assert cfg.endpoint == DEFAULT_OTLP_ENDPOINT
    assert cfg.service_name == "pfm-ai-worker-python"

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", DEFAULT_OTLP_ENDPOINT)
    monkeypatch.setenv("OTEL_SERVICE_NAME", "custom-ai")
    cfg_live = init_otel_config()
    assert cfg_live.noop is False
    assert cfg_live.service_name == "custom-ai"

    valid_tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    assert ensure_traceparent(valid_tp) == valid_tp
    gen_tp = ensure_traceparent("invalid")
    assert len(gen_tp) == 55 and gen_tp.startswith("00-")

    assert mask_sensitive_pii("") == ""
    masked = mask_sensitive_pii('CPF 123.456.789-01 cartao 4532 1122 3344 5566 "pdfPassword":"abc"')
    assert "123.456.789-01" not in masked
    assert "4532 1122" not in masked
    assert "abc" not in masked

    log_json = format_structured_json_log("", "CPF 11122233344 password=xyz", valid_tp)
    assert "[CPF_MASKED]" in log_json
    assert "[REDACTED]" in log_json
    assert "4bf92f3577b34da6a3ce929d0e0e4736" in log_json

