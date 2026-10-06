#!/usr/bin/with-contenv bashio
set -e

CONFIG_PATH=/data/options.json

# --- Gemini -----------------------------------------------------------------

export GEMINI_API_KEY="$(jq --raw-output '.gemini_api_key // ""' $CONFIG_PATH)"
export GEMINI_MODELS="$(jq --raw-output '.gemini_models // "gemini-3.8-flash"' $CONFIG_PATH)"
export GEMINI_PROXY="$(jq --raw-output '.gemini_proxy // ""' $CONFIG_PATH)"

# --- yt-dlp -----------------------------------------------------------------

export SUB_LANGS="$(jq --raw-output '.sub_langs // "ru.*"' $CONFIG_PATH)"
export COOKIES_FILE="$(jq --raw-output '.cookies_file // ""' $CONFIG_PATH)"
export LOG_LEVEL="$(jq --raw-output '.log_level // "info"' $CONFIG_PATH)"

# --- GitHub sync ------------------------------------------------------------

export GITHUB_REPO="$(jq --raw-output '.github_repo // ""' $CONFIG_PATH)"
export GITHUB_USERNAME="$(jq --raw-output '.github_username // ""' $CONFIG_PATH)"
export GITHUB_TOKEN="$(jq --raw-output '.github_token // ""' $CONFIG_PATH)"
export GITHUB_BRANCH="$(jq --raw-output '.github_branch // "main"' $CONFIG_PATH)"
export GITHUB_PATH="$(jq --raw-output '.github_path // "recipes.json"' $CONFIG_PATH)"
export GITHUB_INGREDIENTS_PATH="$(jq --raw-output '.github_ingredients_path // "ingredients.json"' $CONFIG_PATH)"

# --- Matcher (каскад матчинга ингредиентов) ---------------------------------

export MATCHER_PROVIDER="$(jq --raw-output '.matcher_provider // "auto"' $CONFIG_PATH)"
export MATCHER_AUTO_THRESHOLD="$(jq --raw-output '.matcher_auto_threshold // 0.95' $CONFIG_PATH)"
export MATCHER_SUGGEST_THRESHOLD="$(jq --raw-output '.matcher_suggest_threshold // 0.80' $CONFIG_PATH)"
export MATCHER_DAILY_LIMIT="$(jq --raw-output '.matcher_daily_limit // 200' $CONFIG_PATH)"
export MATCHER_CONFIRM_MODE="$(jq --raw-output '.matcher_confirm_mode // "single"' $CONFIG_PATH)"

# Внешний OpenAI-совместимый endpoint (Hermes, OpenRouter, Groq, Ollama, ...)
export MATCHER_EXTERNAL_ENABLED="$(jq --raw-output '.matcher_external_enabled // false' $CONFIG_PATH)"
export MATCHER_EXTERNAL_URL="$(jq --raw-output '.matcher_external_url // ""' $CONFIG_PATH)"
export MATCHER_EXTERNAL_KEY="$(jq --raw-output '.matcher_external_key // ""' $CONFIG_PATH)"
export MATCHER_EXTERNAL_MODEL="$(jq --raw-output '.matcher_external_model // "hermes-agent"' $CONFIG_PATH)"
export MATCHER_EXTERNAL_EMBEDDING_MODEL="$(jq --raw-output '.matcher_external_embedding_model // ""' $CONFIG_PATH)"
export MATCHER_EXTERNAL_TIMEOUT="$(jq --raw-output '.matcher_external_timeout // 15' $CONFIG_PATH)"

# Fallback-эмбеддинги: OpenRouter
export OPENROUTER_API_KEY="$(jq --raw-output '.openrouter_api_key // ""' $CONFIG_PATH)"
export OPENROUTER_EMBEDDING_MODEL="$(jq --raw-output '.openrouter_embedding_model // "openai/text-embedding-3-small"' $CONFIG_PATH)"

# Fallback-эмбеддинги: Groq
export GROQ_API_KEY="$(jq --raw-output '.groq_api_key // ""' $CONFIG_PATH)"
export GROQ_EMBEDDING_MODEL="$(jq --raw-output '.groq_embedding_model // "nomic-embed-text-v1_5"' $CONFIG_PATH)"

# Локальные эмбеддинги через sentence-transformers
export LOCAL_EMBEDDER_ENABLED="$(jq --raw-output '.local_embedder_enabled // false' $CONFIG_PATH)"
export LOCAL_EMBEDDER_MODEL="$(jq --raw-output '.local_embedder_model // "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"' $CONFIG_PATH)"
export LOCAL_EMBEDDER_ONNX="$(jq --raw-output '.local_embedder_onnx // true' $CONFIG_PATH)"
export LOCAL_EMBEDDER_MAX_CONCURRENT="$(jq --raw-output '.local_embedder_max_concurrent // 1' $CONFIG_PATH)"

# --- Backup -----------------------------------------------------------------

export BACKUP_ENABLED="$(jq --raw-output '.backup_enabled // true' $CONFIG_PATH)"
export BACKUP_KEEP_DAYS="$(jq --raw-output '.backup_keep_days // 7' $CONFIG_PATH)"
export BACKUP_INTERVAL_HOURS="$(jq --raw-output '.backup_interval_hours // 24' $CONFIG_PATH)"

# --- Логи -------------------------------------------------------------------

bashio::log.info "Starting Recipe Manager add-on on port 8099"
bashio::log.info "Models: ${GEMINI_MODELS}"
bashio::log.info "API key configured: $([ -n "${GEMINI_API_KEY}" ] && echo yes || echo no)"
bashio::log.info "Sub langs: ${SUB_LANGS}"
bashio::log.info "GitHub: $([ -n "${GITHUB_REPO}" ] && echo "${GITHUB_REPO}@${GITHUB_BRANCH}" || echo 'not configured')"
bashio::log.info "Matcher provider: ${MATCHER_PROVIDER}"
if [ "${MATCHER_EXTERNAL_ENABLED}" = "true" ] && [ -n "${MATCHER_EXTERNAL_URL}" ]; then
    bashio::log.info "Matcher external: ${MATCHER_EXTERNAL_URL} (model: ${MATCHER_EXTERNAL_MODEL})"
else
    bashio::log.info "Matcher external: disabled"
fi
if [ "${LOCAL_EMBEDDER_ENABLED}" = "true" ]; then
    bashio::log.info "Local embedder: enabled (${LOCAL_EMBEDDER_MODEL})"
else
    bashio::log.info "Local embedder: disabled"
fi

# --- Запуск -----------------------------------------------------------------

exec /opt/venv/bin/uvicorn main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --log-level "${LOG_LEVEL}" \
    --proxy-headers \
    --forwarded-allow-ips='*'