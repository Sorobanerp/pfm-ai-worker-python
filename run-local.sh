#!/usr/bin/env bash
# ==============================================================================
# PFM PULSE — LOCAL FOREGROUND RUNNER & LIVE DATADOG JSON LOGGER
# Service: pfm-ai-worker-python (Python 3.12 | Kafka Consumer | Health :18400)
# CloudWatch: 100% DISABLED (CLOUDWATCH_LOGS_ENABLED=false)
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p logs

if [[ -f ".env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env.local"
  set +a
fi

export APP_ENV="local"
export LOG_LEVEL="DEBUG"
export CLOUDWATCH_LOGS_ENABLED="false"
export AWS_CLOUDWATCH_ENABLED="false"
export PYTHONPATH="."

echo "=============================================================================="
echo " [pfm-ai-worker-python] Verificando Infraestrutura Base Local..."
echo "=============================================================================="
for pair in "PostgreSQL:5432" "Redpanda_Kafka:9092" "Redis_Valkey:6379" "LocalStack:4566"; do
  name="${pair%%:*}"
  port="${pair##*:}"
  if ! (echo > "/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1; then
    echo " [ERRO] $name nao esta acessivel em localhost:$port!"
    echo "        Execute primeiro: /home/dantas/workspace/pfm-platform/init-local-development.sh"
    exit 1
  fi
  echo " [OK] $name ativo em localhost:$port"
done

PYTHON_BIN="python3"
if [[ -x "./.venv/bin/python" ]]; then
  PYTHON_BIN="./.venv/bin/python"
fi

echo "=============================================================================="
echo " [pfm-ai-worker-python] Iniciando em Foreground (Kafka Consumer | Health :18400)"
echo " Logs JSON estruturados (Datadog) ao vivo e em: $(pwd)/logs/app-local.log"
echo "=============================================================================="
exec "$PYTHON_BIN" -m src.main 2>&1 | tee -a ./logs/app-local.log
