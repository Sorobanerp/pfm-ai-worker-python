# pfm-ai-worker-python

Microsserviço de Inteligência e Categorização Financeira em 3 Camadas seguindo **Arquitetura Hexagonal (Ports & Adapters)** e **ADR-002 / ADR-009 V2**.

## Arquitetura do Pipeline em 3 Camadas
1. **Camada 1 — Memória do Tenant (PostgreSQL RLS `pfm_ai_rules` — host `15433` / container `5432`):** Consulta regras aprendidas a partir de correções do usuário no Inbox (`confidence = 1.00`).
2. **Camada 2 — Normalizador Determinístico de Adquirentes, Cidade & Regex (`src/domain/normalizer.py`):**
   - Remove prefixos de subadquirentes/maquininhas (`JIM.COM*`, `MP *`, `BMB*`, `HNA*`, `PG *`, `EC *`, `PAG*`).
   - Extrai sufixos colados de Município/UF/País (ex: `POSTO FREI DAMIAOACUBRA` -> `POSTO FREI DAMIAO`, Cidade: `Acu`).
   - Aplica regras determinísticas de alta precisão (`CHURRASCARIA` -> `VAR_FOOD_RESTAURANT`, `POSTO` -> `VAR_MOBILITY_FUEL`, `DROGARIA`/`FARMACIA` -> `VAR_FAMILY_CARE`).
3. **Camada 3 — Fallback Cognitivo (Google Gemini Structured Outputs):**
   - Acionado **exclusivamente** se Camadas 1 e 2 obtiverem confiança `< 0.85`.
   - Protegido por **Timeout (8s)**, **Retry com Exponential Backoff** (`tenacity`) e **Circuit Breaker** com fallback seguro para `SYS_UNCLASSIFIED` (encaminhamento para revisão humana no Inbox).

---

## Topologia de Portas Locais & 12-Factor App

| Interface | Porta Host Local | Porta Container / K8s | Variável de Ambiente | Endpoint / Probe |
|---|:---:|:---:|---|---|
| **Health HTTP** | `18400` | `8080` | `WORKER_PORT` | `http://localhost:18400/health` |
| **PostgreSQL Rules** | `15433` | `5432` | `PFM_AI_RULES_DSN` | `postgresql://...:15433/pfm_ai_rules` |
| **Kafka Backbone** | `19092` | `9092` | `KAFKA_BROKERS` | `localhost:19092` |
| **LocalStack KMS/Secrets** | `14566` | `4566` | `AWS_ENDPOINT_URL` | `http://localhost:14566` |
