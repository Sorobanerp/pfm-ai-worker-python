"""Immutable Domain Models for the 3-Layer Categorization Pipeline (Zero float for monetary values)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.taxonomy import (
    CategoryCode,
    CategoryGroup,
    to_core_ledger_taxonomy,
)


class CategorizationSource(StrEnum):
    """Identifies which layer produced the classification."""

    LAYER_1_TENANT_RULE = "LAYER_1_TENANT_RULE"
    LAYER_2_DETERMINISTIC_REGEX = "LAYER_2_DETERMINISTIC_REGEX"
    LAYER_3_GEMINI_LLM = "LAYER_3_GEMINI_LLM"
    FALLBACK_CIRCUIT_BREAKER = "FALLBACK_CIRCUIT_BREAKER"


class RawTransaction(BaseModel):
    """Immutable raw transaction extracted by the Ingestion BFF."""

    model_config = ConfigDict(frozen=True)

    idempotency_key: str = Field(..., min_length=8)
    tenant_id: str = Field(..., min_length=1)
    statement_id: str = Field(..., min_length=1)
    card_last4: str = Field(default="0000", min_length=4, max_length=4)
    transaction_date: date
    competence_date: date
    raw_description: str = Field(..., min_length=1)
    amount: Decimal = Field(..., decimal_places=4)
    installment_current: int = Field(default=1, ge=1)
    installment_total: int = Field(default=1, ge=1)
    transaction_type: str = Field(default="PURCHASE")
    initial_category_hint: str | None = Field(default=None)


class NormalizationResult(BaseModel):
    """Output of Layer 2 Deterministic Merchant & City Normalizer."""

    model_config = ConfigDict(frozen=True)

    raw_description: str
    acquirer_prefix: str | None = None
    merchant_clean: str
    city: str | None = None
    country_or_state: str | None = None
    matched_category: CategoryCode | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rule_matched: str | None = None


class CategorizedTransaction(BaseModel):
    """Immutable enriched and categorized transaction emitted to `tx.categorized`."""

    model_config = ConfigDict(frozen=True)

    idempotency_key: str
    tenant_id: str
    statement_id: str
    card_last4: str
    transaction_date: date
    competence_date: date
    raw_description: str
    merchant_normalized: str
    city: str | None = None
    acquirer_prefix: str | None = None
    amount: Decimal
    installment_current: int
    installment_total: int
    category_group: CategoryGroup
    category_code: CategoryCode
    ledger_category_code: str = Field(default="OUTROS")
    ledger_subcategory_code: str = Field(default="NAO_CATEGORIZADO")
    confidence: float = Field(..., ge=0.0, le=1.0)
    categorization_source: CategorizationSource
    requires_inbox_review: bool = False
    processed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="before")
    @classmethod
    def _populate_ledger_taxonomy(cls, data: Any) -> Any:
        if isinstance(data, dict):
            raw_code = data.get("category_code")
            if raw_code is not None:
                code_enum = (
                    raw_code
                    if isinstance(raw_code, CategoryCode)
                    else CategoryCode(str(raw_code))
                )
                l1, l2 = to_core_ledger_taxonomy(code_enum)
                data.setdefault("ledger_category_code", l1)
                data.setdefault("ledger_subcategory_code", l2)
        return data


class LearnedRule(BaseModel):
    """Immutable tenant-specific rule learned from Inbox user corrections."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(..., min_length=1)
    merchant_pattern: str = Field(..., min_length=2)
    category_code: CategoryCode
    category_group: CategoryGroup
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_by_inbox_correction: bool = True
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
