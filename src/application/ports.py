"""Hexagonal Ports (Interfaces) for the Application Layer."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.domain.models import CategorizedTransaction, LearnedRule
from src.domain.taxonomy import CategoryCode, CategoryGroup


class LlmClassificationResponse(BaseModel):
    """Strict Structured Output schema returned by Layer 3 LLM (Google Gemini)."""

    model_config = ConfigDict(frozen=True)

    category_group: CategoryGroup
    category_code: CategoryCode
    merchant_clean: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(default="")


class TenantRuleRepositoryPort(Protocol):
    """Outbound Port for Tenant Learned Rules persistence (PostgreSQL RLS on port 5433)."""

    def find_matching_rule(self, tenant_id: str, merchant_clean: str) -> LearnedRule | None:
        """Return a matching learned rule for the tenant and normalized merchant, or None."""
        ...

    def upsert_learned_rule(self, rule: LearnedRule) -> LearnedRule:
        """Save or update a learned rule created from a user Inbox correction."""
        ...


class LlmClassifierPort(Protocol):
    """Outbound Port for Layer 3 Cognitive Fallback (Google Gemini Structured Outputs)."""

    def classify_merchant(
        self,
        tenant_id: str,
        raw_description: str,
        merchant_clean: str,
        city: str | None,
        amount_str: str,
    ) -> LlmClassificationResponse:
        """Classify an ambiguous transaction using Gemini with strict Pydantic JSON Schema."""
        ...


class CategorizedEventPublisherPort(Protocol):
    """Outbound Port for publishing categorized transactions to Kafka (`tx.categorized`)."""

    def publish_categorized(self, tx: CategorizedTransaction) -> None:
        """Publish categorized transaction partitioned by `tenant_id`."""
        ...
