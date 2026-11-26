# Changelog — `pfm-ai-worker-python`

Todas as alterações notáveis neste repositório são documentadas neste arquivo seguindo o padrão [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e versionamento semântico [SemVer 2.0.0](https://semver.org/lang/pt-BR/).

---

## [Unreleased]

### Added
- Entrypoint Serverless **AWS Lambda Arm64** (`src/adapter/in/lambda_handler.py`) conforme **ADR-009**: custo \$0 ocioso, sem conexão direta ao PostgreSQL (`InMemoryZeroDbRuleRepository`), compatível com eventos Kafka/Upstash, SQS e invocação direta, devolvendo eventos para `tx.categorized`.
- Entrypoint contínuo **Kubernetes/KEDA** (`src/adapter/in/kafka_worker.py`) com `KafkaWorkerRunner` e *graceful shutdown* (`SIGTERM`/`SIGINT`).
- Padronização de governança DevEx (`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`) e workflow de validação de **Conventional Commits** em Pull Requests para `develop` e `main`.

---

## [0.2.0] - 2026-11-20

### Added
- Arquitetura Hexagonal estrita sem driver PostgreSQL; funil L1/L2 ONNX/L3 LLM com Circuit Breaker e DLQ cifrada.

### Changed
- Alinhamento com a arquitetura **PFM Core Banking V3.0 (Production-Ready FinOps & Multi-Cloud)**.

### Security
- Aplicação estrita de políticas Zero-Trust (OIDC sem chaves estáticas, Trivy/Semgrep/Gitleaks gates e isolamento por tenant).

### Infrastructure
- Instrumentação OpenTelemetry Python e cobertura $\ge 95\%$ no SonarCloud Portfolio.

---

## [0.1.0] - 2026-11-15

### Added
- Estrutura inicial do repositório `pfm-ai-worker-python`, pipelines GitHub Actions e integração ao ecossistema Gitflow `Sorobanerp`.
