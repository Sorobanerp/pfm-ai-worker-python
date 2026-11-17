-- ============================================================================
-- Migration: V1__init_ai_rules_rls.sql
-- Target Database: pfm_ai_rules (Port 5433)
-- Enforces PostgreSQL 16 Row-Level Security (RLS) for Tenant Learned Rules
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pfm_ai_user') THEN
        CREATE ROLE pfm_ai_user WITH LOGIN PASSWORD 'pfm_ai_pass' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS learned_merchant_rules (
    tenant_id        VARCHAR(64)   NOT NULL,
    merchant_pattern VARCHAR(255)  NOT NULL,
    category_code    VARCHAR(64)   NOT NULL,
    category_group   VARCHAR(64)   NOT NULL,
    confidence       NUMERIC(19,4) NOT NULL DEFAULT 1.0000,
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, merchant_pattern)
);

ALTER TABLE learned_merchant_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE learned_merchant_rules FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rls_learned_merchant_rules_isolation ON learned_merchant_rules;
CREATE POLICY rls_learned_merchant_rules_isolation ON learned_merchant_rules
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(BTRIM(current_setting('app.current_tenant_id', true)), ''))
    WITH CHECK (tenant_id = NULLIF(BTRIM(current_setting('app.current_tenant_id', true)), ''));

GRANT USAGE ON SCHEMA public TO pfm_ai_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON learned_merchant_rules TO pfm_ai_user;
