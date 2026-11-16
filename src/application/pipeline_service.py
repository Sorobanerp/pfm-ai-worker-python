"""3-Layer AI Categorization Pipeline Orchestrator and Inbox Learning Use Case."""

from src.application.ports import (
    CategorizedEventPublisherPort,
    LlmClassifierPort,
    TenantRuleRepositoryPort,
)
from src.application.resilience import CircuitBreaker
from src.domain.models import (
    CategorizationSource,
    CategorizedTransaction,
    LearnedRule,
    RawTransaction,
)
from src.domain.normalizer import MerchantNormalizer
from src.domain.taxonomy import CategoryCode, CategoryGroup, get_category_group

CONFIDENCE_THRESHOLD = 0.85


class ThreeLayerCategorizationService:
    """
    Orchestrates the 3-Layer Categorization Pipeline (ADR-002 / ADR-009):
    - Layer 1: Tenant Learned Rules (PostgreSQL RLS `pfm_ai_rules`) -> confidence = 1.00
    - Layer 2: Deterministic Acquirer Stripper, City Extractor & Regex Normalizer -> confidence >= 0.85
    - Layer 3: Google Gemini Structured Outputs (ONLY if Layer 1 & 2 < 0.85), protected by
               8s Timeout, Retry with Backoff, and Circuit Breaker (fallback -> SYS_UNCLASSIFIED).
    """

    def __init__(
        self,
        rule_repository: TenantRuleRepositoryPort,
        llm_classifier: LlmClassifierPort,
        event_publisher: CategorizedEventPublisherPort,
        normalizer: MerchantNormalizer | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
    ) -> None:
        self._rule_repository = rule_repository
        self._llm_classifier = llm_classifier
        self._event_publisher = event_publisher
        self._normalizer = normalizer or MerchantNormalizer()
        self._circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=3,
            recovery_timeout_seconds=30.0,
            call_timeout_seconds=8.0,
            max_retries=2,
        )
        self._confidence_threshold = confidence_threshold

    def categorize_transaction(self, raw_tx: RawTransaction) -> CategorizedTransaction:
        """Run the 3-layer pipeline for a single RawTransaction and publish the result."""
        # Always run Layer 2 normalization first to obtain clean merchant name, acquirer prefix & city
        norm = self._normalizer.normalize(raw_tx.raw_description)

        # LAYER 1: Check Tenant Learned Rules first (highest priority, user-verified memory)
        learned_rule = self._rule_repository.find_matching_rule(
            tenant_id=raw_tx.tenant_id,
            merchant_clean=norm.merchant_clean,
        )
        if learned_rule is not None and learned_rule.confidence >= self._confidence_threshold:
            categorized = CategorizedTransaction(
                idempotency_key=raw_tx.idempotency_key,
                tenant_id=raw_tx.tenant_id,
                statement_id=raw_tx.statement_id,
                card_last4=raw_tx.card_last4,
                transaction_date=raw_tx.transaction_date,
                competence_date=raw_tx.competence_date,
                raw_description=raw_tx.raw_description,
                merchant_normalized=norm.merchant_clean,
                city=norm.city,
                acquirer_prefix=norm.acquirer_prefix,
                amount=raw_tx.amount,
                installment_current=raw_tx.installment_current,
                installment_total=raw_tx.installment_total,
                category_group=learned_rule.category_group,
                category_code=learned_rule.category_code,
                confidence=learned_rule.confidence,
                categorization_source=CategorizationSource.LAYER_1_TENANT_RULE,
                requires_inbox_review=False,
            )
            self._event_publisher.publish_categorized(categorized)
            return categorized

        # LAYER 2: Deterministic Regex & Keyword Rules (if confidence >= 0.85, skip LLM!)
        if (
            norm.matched_category is not None
            and norm.confidence >= self._confidence_threshold
        ):
            category_group = get_category_group(norm.matched_category)
            categorized = CategorizedTransaction(
                idempotency_key=raw_tx.idempotency_key,
                tenant_id=raw_tx.tenant_id,
                statement_id=raw_tx.statement_id,
                card_last4=raw_tx.card_last4,
                transaction_date=raw_tx.transaction_date,
                competence_date=raw_tx.competence_date,
                raw_description=raw_tx.raw_description,
                merchant_normalized=norm.merchant_clean,
                city=norm.city,
                acquirer_prefix=norm.acquirer_prefix,
                amount=raw_tx.amount,
                installment_current=raw_tx.installment_current,
                installment_total=raw_tx.installment_total,
                category_group=category_group,
                category_code=norm.matched_category,
                confidence=norm.confidence,
                categorization_source=CategorizationSource.LAYER_2_DETERMINISTIC_REGEX,
                requires_inbox_review=False,
            )
            self._event_publisher.publish_categorized(categorized)
            return categorized

        # LAYER 3: Cognitive Fallback via Gemini Structured Outputs protected by Circuit Breaker
        try:
            llm_response = self._circuit_breaker.execute(
                lambda: self._llm_classifier.classify_merchant(
                    tenant_id=raw_tx.tenant_id,
                    raw_description=raw_tx.raw_description,
                    merchant_clean=norm.merchant_clean,
                    city=norm.city,
                    amount_str=f"{raw_tx.amount:.4f}",
                )
            )
            if llm_response.confidence >= self._confidence_threshold:
                categorized = CategorizedTransaction(
                    idempotency_key=raw_tx.idempotency_key,
                    tenant_id=raw_tx.tenant_id,
                    statement_id=raw_tx.statement_id,
                    card_last4=raw_tx.card_last4,
                    transaction_date=raw_tx.transaction_date,
                    competence_date=raw_tx.competence_date,
                    raw_description=raw_tx.raw_description,
                    merchant_normalized=llm_response.merchant_clean or norm.merchant_clean,
                    city=norm.city,
                    acquirer_prefix=norm.acquirer_prefix,
                    amount=raw_tx.amount,
                    installment_current=raw_tx.installment_current,
                    installment_total=raw_tx.installment_total,
                    category_group=get_category_group(llm_response.category_code),
                    category_code=llm_response.category_code,
                    confidence=llm_response.confidence,
                    categorization_source=CategorizationSource.LAYER_3_GEMINI_LLM,
                    requires_inbox_review=False,
                )
            else:
                categorized = self._build_unclassified_fallback(
                    raw_tx=raw_tx,
                    merchant_clean=norm.merchant_clean,
                    city=norm.city,
                    acquirer_prefix=norm.acquirer_prefix,
                    confidence=llm_response.confidence,
                    source=CategorizationSource.LAYER_3_GEMINI_LLM,
                )
        except Exception:  # noqa: BLE001
            # Safe Fallback when Gemini fails, times out (8s), or Circuit Breaker is OPEN
            categorized = self._build_unclassified_fallback(
                raw_tx=raw_tx,
                merchant_clean=norm.merchant_clean,
                city=norm.city,
                acquirer_prefix=norm.acquirer_prefix,
                confidence=0.0,
                source=CategorizationSource.FALLBACK_CIRCUIT_BREAKER,
            )

        self._event_publisher.publish_categorized(categorized)
        return categorized

    @staticmethod
    def _build_unclassified_fallback(
        raw_tx: RawTransaction,
        merchant_clean: str,
        city: str | None,
        acquirer_prefix: str | None,
        confidence: float,
        source: CategorizationSource,
    ) -> CategorizedTransaction:
        return CategorizedTransaction(
            idempotency_key=raw_tx.idempotency_key,
            tenant_id=raw_tx.tenant_id,
            statement_id=raw_tx.statement_id,
            card_last4=raw_tx.card_last4,
            transaction_date=raw_tx.transaction_date,
            competence_date=raw_tx.competence_date,
            raw_description=raw_tx.raw_description,
            merchant_normalized=merchant_clean,
            city=city,
            acquirer_prefix=acquirer_prefix,
            amount=raw_tx.amount,
            installment_current=raw_tx.installment_current,
            installment_total=raw_tx.installment_total,
            category_group=CategoryGroup.SYSTEM_CONTROL,
            category_code=CategoryCode.SYS_UNCLASSIFIED,
            confidence=confidence,
            categorization_source=source,
            requires_inbox_review=True,
        )


class LearnFromInboxCorrectionUseCase:
    """
    Handles human-in-the-loop Inbox corrections:
    1. Normalizes the merchant descriptor to extract clean pattern.
    2. Persists a new tenant-scoped LearnedRule (`confidence = 1.0`).
    3. Triggers retroactive reclassification of pending/historical transactions matching that merchant.
    """

    def __init__(
        self,
        rule_repository: TenantRuleRepositoryPort,
        categorization_service: ThreeLayerCategorizationService,
        normalizer: MerchantNormalizer | None = None,
    ) -> None:
        self._rule_repository = rule_repository
        self._categorization_service = categorization_service
        self._normalizer = normalizer or MerchantNormalizer()

    def execute(
        self,
        tenant_id: str,
        raw_description: str,
        corrected_category: CategoryCode,
        retroactive_transactions: list[RawTransaction] | None = None,
    ) -> tuple[LearnedRule, list[CategorizedTransaction]]:
        norm = self._normalizer.normalize(raw_description)
        rule = LearnedRule(
            tenant_id=tenant_id,
            merchant_pattern=norm.merchant_clean,
            category_code=corrected_category,
            category_group=get_category_group(corrected_category),
            confidence=1.0,
            created_by_inbox_correction=True,
        )
        saved_rule = self._rule_repository.upsert_learned_rule(rule)

        reclassified: list[CategorizedTransaction] = []
        for tx in retroactive_transactions or []:
            if tx.tenant_id == tenant_id:
                reclassified.append(self._categorization_service.categorize_transaction(tx))

        return saved_rule, reclassified
