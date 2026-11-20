"""PostgreSQL Repository connected to isolated `pfm_ai_rules` DB (port 5433) with RLS."""

import os

import psycopg
from psycopg.rows import dict_row

from src.domain.models import LearnedRule
from src.domain.taxonomy import CategoryCode, CategoryGroup

DEFAULT_AI_RULES_DSN = os.getenv("PFM_AI_RULES_DSN", "")


class PostgresTenantRuleRepository:
    """
    Adapter for `TenantRuleRepositoryPort` enforcing PostgreSQL Row-Level Security (RLS)
    via `SET LOCAL app.current_tenant_id = %s` inside every transaction block.
    """

    def __init__(self, dsn: str = DEFAULT_AI_RULES_DSN) -> None:
        self._dsn = dsn

    def find_matching_rule(self, tenant_id: str, merchant_clean: str) -> LearnedRule | None:
        normalized_pattern = merchant_clean.strip().upper()
        with (
            psycopg.connect(self._dsn, row_factory=dict_row) as conn,
            conn.transaction(),
            conn.cursor() as cur,
        ):
            cur.execute(
                "SELECT set_config('app.current_tenant_id', %s, true)",
                (tenant_id,),
            )
            cur.execute(
                """
                SELECT tenant_id, merchant_pattern, category_code, category_group, confidence, updated_at
                FROM learned_merchant_rules
                WHERE tenant_id = %s
                  AND (%s = merchant_pattern OR %s ILIKE '%%' || merchant_pattern || '%%')
                ORDER BY length(merchant_pattern) DESC
                LIMIT 1
                """,
                (tenant_id, normalized_pattern, normalized_pattern),
            )
            row = cur.fetchone()
            if not row:
                return None
            return LearnedRule(
                tenant_id=row["tenant_id"],
                merchant_pattern=row["merchant_pattern"],
                category_code=CategoryCode(row["category_code"]),
                category_group=CategoryGroup(row["category_group"]),
                confidence=float(row["confidence"]),
                updated_at=row["updated_at"],
            )

    def upsert_learned_rule(self, rule: LearnedRule) -> LearnedRule:
        with (
            psycopg.connect(self._dsn, row_factory=dict_row) as conn,
            conn.transaction(),
            conn.cursor() as cur,
        ):
            cur.execute(
                "SELECT set_config('app.current_tenant_id', %s, true)",
                (rule.tenant_id,),
            )
            cur.execute(
                """
                INSERT INTO learned_merchant_rules (
                    tenant_id, merchant_pattern, category_code, category_group, confidence, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, merchant_pattern)
                DO UPDATE SET
                    category_code = EXCLUDED.category_code,
                    category_group = EXCLUDED.category_group,
                    confidence = EXCLUDED.confidence,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    rule.tenant_id,
                    rule.merchant_pattern.upper(),
                    rule.category_code.value,
                    rule.category_group.value,
                    rule.confidence,
                    rule.updated_at,
                ),
            )
        return rule
