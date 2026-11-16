# pfm-ai-worker-python

Microsserviço de Inteligência e Categorização Financeira em 3 Camadas seguindo **Arquitetura Hexagonal (Ports & Adapters)** e **ADR-002 / ADR-009 V2**.

## Arquitetura do Pipeline em 3 Camadas
1. **Camada 1 — Memória do Tenant (PostgreSQL RLS `pfm_ai_rules:5433`):** Consulta regras aprendidas a partir de correções do usuário no Inbox (`confidence = 1.00`).
2. **Camada 2 — Normalizador Determinístico de Adquirentes, Cidade & Regex (`src/domain/normalizer.py`):**
   - Remove prefixos de subadquirentes/maquininhas (`JIM.COM*`, `MP *`, `BMB*`, `HNA*`, `PG *`, `EC *`, `PAG*`).
   - Extrai sufixos colados de Município/UF/País (ex: `POSTO FREI DAMIAOACUBRA` -> `POSTO FREI DAMIAO`, Cidade: `Acu`).
   - Aplica regras determinísticas de alta precisão (`CHURRASCARIA` -> `VAR_FOOD_RESTAURANT`, `POSTO` -> `VAR_MOBILITY_FUEL`, `DROGARIA`/`FARMACIA` -> `VAR_FAMILY_CARE`).
3. **Camada 3 — Fallback Cognitivo (Google Gemini Structured Outputs):**
   - Acionado **exclusivamente** se Camadas 1 e 2 obtiverem confiança `< 0.85`.
   - Protegido por **Timeout (8s)**, **Retry com Exponential Backoff** (`tenacity`) e **Circuit Breaker** com fallback seguro para `SYS_UNCLASSIFIED` (encaminhamento para revisão humana no Inbox).
