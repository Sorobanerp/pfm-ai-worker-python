"""Domain layer — Pure business models, Official 2-Level Taxonomy, and Layer 2 Normalizer."""

from src.domain.models import (
    CategorizationSource,
    CategorizedTransaction,
    LearnedRule,
    NormalizationResult,
    RawTransaction,
)
from src.domain.normalizer import MerchantNormalizer
from src.domain.taxonomy import (
    CATEGORY_GROUP_MAP,
    CategoryCode,
    CategoryGroup,
    get_category_group,
)

__all__ = [
    "CATEGORY_GROUP_MAP",
    "CategorizationSource",
    "CategorizedTransaction",
    "CategoryCode",
    "CategoryGroup",
    "LearnedRule",
    "MerchantNormalizer",
    "NormalizationResult",
    "RawTransaction",
    "get_category_group",
]
