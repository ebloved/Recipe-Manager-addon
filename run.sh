#!/usr/bin/with-contenv bashio
set -e

CONFIG_PATH=/data/options.json

export GEMINI_API_KEY="$(jq --raw-output '.gemini_api_key // ""' $CONFIG_PATH)"
export GEMINI_MODELS="$(jq --raw-output '.gemini_models // "gemini-3.8-flash"' $CONFIG_PATH)"
export GEMINI_PROXY="$(jq --raw-output '.gemini_proxy // ""' $CONFIG_PATH)"
export SUB_LANGS="$(jq --raw-output '.sub_langs // "ru.*"' $CONFIG_PATH)"
export COOKIES_FILE="$(jq --raw-output '.cookies_file // ""' $CONFIG_PATH)"
export LOG_LEVEL="$(jq --raw-output '.log_level // "info"' $CONFIG_PATH)"

bashio::log.info "Starting Recipe Manager add-on on port 8099"
bashio::log.info "Models: ${GEMINI_MODELS}"
bashio::log.info "API key configured: $([ -n "${GEMINI_API_KEY}" ] && echo yes || echo no)"
bashio::log.info "Sub langs: ${SUB_LANGS}"

exec /opt/venv/bin/uvicorn main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --log-level "${LOG_LEVEL}" \
    --proxy-headers \
    --forwarded-allow-ips='*'