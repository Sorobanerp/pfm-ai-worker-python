"""Unit tests for the 3-Layer AI Categorization & Merchant Normalization Pipeline."""

from datetime import date
from decimal import Decimal

import pytest

from src.application.pipeline_service import (
    LearnFromInboxCorrectionUseCase,
    ThreeLayerCategorizationService,
)
from src.application.ports import LlmClassificationResponse
from src.application.resilience import CircuitBreaker
from src.domain.models import (
    CategorizationSource,
    CategorizedTransaction,
    LearnedRule,
    RawTransaction,
)
from src.domain.normalizer import MerchantNormalizer
from src.domain.taxonomy import CategoryCode, CategoryGroup


class InMemoryTenantRuleRepository:
    """In-memory test double for `TenantRuleRepositoryPort`."""

    def __init__(self) -> None:
        self._rules: dict[tuple[str, str], LearnedRule] = {}

    def find_matching_rule(self, tenant_id: str, merchant_clean: str) -> LearnedRule | None:
        key = (tenant_id, merchant_clean.upper())
        if key in self._rules:
            return self._rules[key]
        for (rule_tenant, pattern), rule in self._rules.items():
            if rule_tenant == tenant_id and pattern in merchant_clean.upper():
                return rule
        return None

    def upsert_learned_rule(self, rule: LearnedRule) -> LearnedRule:
        self._rules[(rule.tenant_id, rule.merchant_pattern.upper())] = rule
        return rule


class SpyEventPublisher:
    """In-memory spy for `CategorizedEventPublisherPort`."""

    def __init__(self) -> None:
        self.published: list[CategorizedTransaction] = []

    def publish_categorized(self, tx: CategorizedTransaction) -> None:
        self.published.append(tx)


class FakeGeminiClassifier:
    """Configurable test double for `LlmClassifierPort`."""

    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: int = 0

    def classify_merchant(
        self,
        tenant_id: str,
        raw_description: str,
        merchant_clean: str,
        city: str | None,
        amount_str: str,
    ) -> LlmClassificationResponse:
        self.calls += 1
        if self.should_fail:
            raise ConnectionError("Gemini 503 Service Unavailable")
        return LlmClassificationResponse(
            category_group=CategoryGroup.VARIABLE_LIFESTYLE,
            category_code=CategoryCode.VAR_SHOPPING_RETAIL,
            merchant_clean=merchant_clean,
            confidence=0.91,
            reasoning="Classified via Gemini Structured Outputs",
        )


def _make_raw_tx(
    raw_description: str,
    amount: str = "125.9000",
    tenant_id: str = "tenant-dantas-001",
    initial_hint: str | None = None,
) -> RawTransaction:
    return RawTransaction(
        idempotency_key="a" * 64,
        tenant_id=tenant_id,
        statement_id="stmt-2026-03",
        card_last4="9874",
        transaction_date=date(2026, 3, 14),
        competence_date=date(2026, 3, 1),
        raw_description=raw_description,
        amount=Decimal(amount),
        installment_current=1,
        installment_total=1,
        initial_category_hint=initial_hint,
    )


@pytest.mark.parametrize(
    ("raw_descriptor", "expected_prefix", "expected_merchant"),
    [
        ("JIM.COM* MERCADINHO SAO JOSE", "JIM.COM*", "MERCADINHO SAO JOSE"),
        ("MP *DROGARIA SANTA CLARA", "MP *", "DROGARIA SANTA CLARA"),
        ("BMB*FARMACIA POPULAR", "BMB*", "FARMACIA POPULAR"),
        ("HNA*PADARIA CENTRAL", "HNA*", "PADARIA CENTRAL"),
        ("PG *POSTO CENTRAL", "PG *", "POSTO CENTRAL"),
        ("EC *SUPERMERCADO MAIS", "EC *", "SUPERMERCADO MAIS"),
        ("PAG*RESTAURANTE SABOR", "PAG*", "RESTAURANTE SABOR"),
    ],
)
def test_layer2_strips_acquirer_prefixes(
    raw_descriptor: str,
    expected_prefix: str,
    expected_merchant: str,
) -> None:
    normalizer = MerchantNormalizer()
    result = normalizer.normalize(raw_descriptor)

    assert result.acquirer_prefix == expected_prefix
    assert result.merchant_clean == expected_merchant
    assert result.confidence >= 0.85


def test_layer2_extracts_glued_city_suffix_posto_frei_damiao_acubra() -> None:
    normalizer = MerchantNormalizer()
    result = normalizer.normalize("POSTO FREI DAMIAOACUBRA")

    assert result.merchant_clean == "POSTO FREI DAMIAO"
    assert result.city == "Acu"
    assert result.country_or_state == "BRA"
    assert result.matched_category == CategoryCode.VAR_MOBILITY_FUEL
    assert result.confidence >= 0.90


def test_layer2_corrects_churrascaria_gaucha_from_supermercado_to_restaurant() -> None:
    repo = InMemoryTenantRuleRepository()
    publisher = SpyEventPublisher()
    gemini = FakeGeminiClassifier(should_fail=False)
    service = ThreeLayerCategorizationService(
        rule_repository=repo,
        llm_classifier=gemini,
        event_publisher=publisher,
    )

    # Even if an upstream/raw hint suggested Supermercado (VAR_FOOD_GROCERY) or had acquirer + city noise:
    raw_tx = _make_raw_tx(
        raw_description="MP *CHURRASCARIA GAUCHAACUBRA",
        amount="189.5000",
        initial_hint="SUPERMERCADO",
    )

    categorized = service.categorize_transaction(raw_tx)

    assert categorized.merchant_normalized == "CHURRASCARIA GAUCHA"
    assert categorized.city == "Acu"
    assert categorized.acquirer_prefix == "MP *"
    assert categorized.category_code == CategoryCode.VAR_FOOD_RESTAURANT
    assert categorized.category_group == CategoryGroup.VARIABLE_LIFESTYLE
    assert categorized.categorization_source == CategorizationSource.LAYER_2_DETERMINISTIC_REGEX
    assert categorized.requires_inbox_review is False
    # Layer 2 solved with confidence >= 0.85, so Gemini Layer 3 must NOT be called
    assert gemini.calls == 0


def test_inbox_correction_learns_tenant_rule_and_reclassifies_retroactively() -> None:
    repo = InMemoryTenantRuleRepository()
    publisher = SpyEventPublisher()
    gemini = FakeGeminiClassifier(should_fail=False)
    service = ThreeLayerCategorizationService(
        rule_repository=repo,
        llm_classifier=gemini,
        event_publisher=publisher,
    )
    learn_use_case = LearnFromInboxCorrectionUseCase(
        rule_repository=repo,
        categorization_service=service,
    )

    # Obscure merchant name that initially does not match Layer 2 keywords
    historical_tx_1 = _make_raw_tx("JIM.COM* IRMAOS SILVA LTDAACUBRA", amount="75.0000")
    historical_tx_2 = _make_raw_tx("PG *IRMAOS SILVA LTDA", amount="42.3000")

    learned_rule, reclassified = learn_use_case.execute(
        tenant_id="tenant-dantas-001",
        raw_description="JIM.COM* IRMAOS SILVA LTDAACUBRA",
        corrected_category=CategoryCode.VAR_FOOD_GROCERY,
        retroactive_transactions=[historical_tx_1, historical_tx_2],
    )

    assert learned_rule.merchant_pattern == "IRMAOS SILVA LTDA"
    assert learned_rule.category_code == CategoryCode.VAR_FOOD_GROCERY
    assert learned_rule.confidence == 1.0
    assert len(reclassified) == 2
    for item in reclassified:
        assert item.category_code == CategoryCode.VAR_FOOD_GROCERY
        assert item.category_group == CategoryGroup.VARIABLE_LIFESTYLE
        assert item.categorization_source == CategorizationSource.LAYER_1_TENANT_RULE
        assert item.confidence == 1.0
    assert gemini.calls == 0


def test_layer3_circuit_breaker_fallback_to_sys_unclassified_when_gemini_fails() -> None:
    repo = InMemoryTenantRuleRepository()
    publisher = SpyEventPublisher()
    failing_gemini = FakeGeminiClassifier(should_fail=True)
    circuit_breaker = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=60.0,
        call_timeout_seconds=1.0,
        max_retries=2,
    )
    service = ThreeLayerCategorizationService(
        rule_repository=repo,
        llm_classifier=failing_gemini,
        event_publisher=publisher,
        circuit_breaker=circuit_breaker,
    )

    unknown_tx_1 = _make_raw_tx("HNA*COMERCIO MISTERIOSO XYZ", amount="310.0000")
    unknown_tx_2 = _make_raw_tx("BMB*SERVICOS ALFA BETA", amount="99.9000")
    unknown_tx_3 = _make_raw_tx("EC *EMPRESA DESCONHECIDA 123", amount="50.0000")

    res_1 = service.categorize_transaction(unknown_tx_1)
    res_2 = service.categorize_transaction(unknown_tx_2)

    assert res_1.category_code == CategoryCode.SYS_UNCLASSIFIED
    assert res_1.category_group == CategoryGroup.SYSTEM_CONTROL
    assert res_1.categorization_source == CategorizationSource.FALLBACK_CIRCUIT_BREAKER
    assert res_1.requires_inbox_review is True

    assert res_2.category_code == CategoryCode.SYS_UNCLASSIFIED
    assert circuit_breaker.state == "OPEN"

    # Once circuit breaker is OPEN, the 3rd transaction fast-fails without invoking Gemini at all
    calls_before_open = failing_gemini.calls
    res_3 = service.categorize_transaction(unknown_tx_3)
    assert res_3.category_code == CategoryCode.SYS_UNCLASSIFIED
    assert res_3.requires_inbox_review is True
    assert failing_gemini.calls == calls_before_open
