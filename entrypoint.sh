#!/usr/bin/env bash
set -euo pipefail

# Если переменные не заданы, ставим дефолты для локальной разработки
export DEPLOY_MODE="${DEPLOY_MODE:-standalone}"
export AUTH_MODE="${AUTH_MODE:-dev}"
export RUNTIME_MODE="${RUNTIME_MODE:-full}"
export DOWNLOAD_DIR="${DOWNLOAD_DIR:-/data/downloads}"
export DATA_DIR="${DATA_DIR:-/data}"
export FEATURE_PRODUCTS="true"
export FEATURE_MATCHER="true"
export FEATURE_PROFILES="true"
export FEATURE_GENERATOR="true"

# Базовые настройки Gemini (подхватятся из .env, если заданы)
export GEMINI_MODELS="${GEMINI_MODELS:-gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash}"

mkdir -p "$DOWNLOAD_DIR" "$DATA_DIR"

echo "=================================================="
echo "🚀 Starting Recipe Manager Standalone (Dev Mode)"
echo "   Port: 8099"
echo "   Data: $DATA_DIR"
echo "   Mode: $DEPLOY_MODE / $AUTH_MODE"
echo "=================================================="

exec uvicorn main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --log-level "${LOG_LEVEL:-info}" \
    --proxy-headers \
    --forwarded-allow-ips='*'
