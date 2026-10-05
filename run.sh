#!/usr/bin/with-contenv bashio
set -e

CONFIG_PATH=/data/options.json

export GEMINI_API_KEY="$(jq --raw-output '.gemini_api_key // ""' $CONFIG_PATH)"
export GEMINI_MODELS="$(jq --raw-output '.gemini_models // "gemini-3.8-flash"' $CONFIG_PATH)"
export GEMINI_PROXY="$(jq --raw-output '.gemini_proxy // ""' $CONFIG_PATH)"
export SUB_LANGS="$(jq --raw-output '.sub_langs // "ru.*"' $CONFIG_PATH)"
export COOKIES_FILE="$(jq --raw-output '.cookies_file // ""' $CONFIG_PATH)"
export LOG_LEVEL="$(jq --raw-output '.log_level // "info"' $CONFIG_PATH)"

export GITHUB_REPO="$(jq --raw-output '.github_repo // ""' $CONFIG_PATH)"
export GITHUB_USERNAME="$(jq --raw-output '.github_username // ""' $CONFIG_PATH)"
export GITHUB_TOKEN="$(jq --raw-output '.github_token // ""' $CONFIG_PATH)"
export GITHUB_BRANCH="$(jq --raw-output '.github_branch // "main"' $CONFIG_PATH)"
export GITHUB_PATH="$(jq --raw-output '.github_path // "data/recipes.json"' $CONFIG_PATH)"

bashio::log.info "Starting Recipe Manager add-on on port 8099"
bashio::log.info "Models: ${GEMINI_MODELS}"
bashio::log.info "API key configured: $([ -n "${GEMINI_API_KEY}" ] && echo yes || echo no)"
bashio::log.info "Sub langs: ${SUB_LANGS}"
bashio::log.info "GitHub: $([ -n "${GITHUB_REPO}" ] && echo "${GITHUB_REPO}@${GITHUB_BRANCH}" || echo 'not configured')"

exec /opt/venv/bin/uvicorn main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --log-level "${LOG_LEVEL}" \
    --proxy-headers \
    --forwarded-allow-ips='*'