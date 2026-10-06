#!/usr/bin/with-contenv bashio
set -e

CONFIG_PATH=/data/options.json
EXTRA_PACKAGES_DIR="/data/.extra_packages"
EXTRA_MARKER="${EXTRA_PACKAGES_DIR}/.installed"

# --- Конфиг ----------------------------------------------------------------

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
export GITHUB_PATH="$(jq --raw-output '.github_path // "recipes.json"' $CONFIG_PATH)"
export GITHUB_INGREDIENTS_PATH="$(jq --raw-output '.github_ingredients_path // "ingredients.json"' $CONFIG_PATH)"

export MATCHER_PROVIDER="$(jq --raw-output '.matcher_provider // "auto"' $CONFIG_PATH)"
export MATCHER_AUTO_THRESHOLD="$(jq --raw-output '.matcher_auto_threshold // 0.95' $CONFIG_PATH)"
export MATCHER_SUGGEST_THRESHOLD="$(jq --raw-output '.matcher_suggest_threshold // 0.80' $CONFIG_PATH)"
export MATCHER_DAILY_LIMIT="$(jq --raw-output '.matcher_daily_limit // 200' $CONFIG_PATH)"
export MATCHER_CONFIRM_MODE="$(jq --raw-output '.matcher_confirm_mode // "single"' $CONFIG_PATH)"

export MATCHER_EXTERNAL_ENABLED="$(jq --raw-output '.matcher_external_enabled // false' $CONFIG_PATH)"
export MATCHER_EXTERNAL_URL="$(jq --raw-output '.matcher_external_url // ""' $CONFIG_PATH)"
export MATCHER_EXTERNAL_KEY="$(jq --raw-output '.matcher_external_key // ""' $CONFIG_PATH)"
export MATCHER_EXTERNAL_MODEL="$(jq --raw-output '.matcher_external_model // "hermes-agent"' $CONFIG_PATH)"
export MATCHER_EXTERNAL_EMBEDDING_MODEL="$(jq --raw-output '.matcher_external_embedding_model // ""' $CONFIG_PATH)"
export MATCHER_EXTERNAL_TIMEOUT="$(jq --raw-output '.matcher_external_timeout // 15' $CONFIG_PATH)"

export OPENROUTER_API_KEY="$(jq --raw-output '.openrouter_api_key // ""' $CONFIG_PATH)"
export OPENROUTER_EMBEDDING_MODEL="$(jq --raw-output '.openrouter_embedding_model // "openai/text-embedding-3-small"' $CONFIG_PATH)"
export GROQ_API_KEY="$(jq --raw-output '.groq_api_key // ""' $CONFIG_PATH)"
export GROQ_EMBEDDING_MODEL="$(jq --raw-output '.groq_embedding_model // "nomic-embed-text-v1_5"' $CONFIG_PATH)"

export LOCAL_EMBEDDER_ENABLED="$(jq --raw-output '.local_embedder_enabled // false' $CONFIG_PATH)"
export LOCAL_EMBEDDER_MODEL="$(jq --raw-output '.local_embedder_model // "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"' $CONFIG_PATH)"
export LOCAL_EMBEDDER_ONNX="$(jq --raw-output '.local_embedder_onnx // true' $CONFIG_PATH)"
export LOCAL_EMBEDDER_MAX_CONCURRENT="$(jq --raw-output '.local_embedder_max_concurrent // 1' $CONFIG_PATH)"

export BACKUP_ENABLED="$(jq --raw-output '.backup_enabled // true' $CONFIG_PATH)"
export BACKUP_KEEP_DAYS="$(jq --raw-output '.backup_keep_days // 7' $CONFIG_PATH)"
export BACKUP_INTERVAL_HOURS="$(jq --raw-output '.backup_interval_hours // 24' $CONFIG_PATH)"

# --- Логи ------------------------------------------------------------------

bashio::log.info "Starting Recipe Manager add-on on port 8099"
bashio::log.info "Models: ${GEMINI_MODELS}"
bashio::log.info "GitHub: $([ -n "${GITHUB_REPO}" ] && echo "${GITHUB_REPO}@${GITHUB_BRANCH}" || echo 'not configured')"
bashio::log.info "Matcher provider: ${MATCHER_PROVIDER}"
bashio::log.info "Local embedder: ${LOCAL_EMBEDDER_ENABLED}"

# --- Опциональная установка локального эмбеддера ---------------------------
#
# Устанавливаем sentence-transformers и onnxruntime ТОЛЬКО если пользователь
# включил local_embedder_enabled=true в config.yaml. Пакеты кладутся в
# /data/.extra_packages — это персистентная папка, переживает пересборку
# образа и перезапуски контейнера.
#
# Установка занимает 30–90 секунд при первом запуске. Маркер .installed
# не даёт повторять установку при каждом старте.

install_local_embedder_deps() {
    bashio::log.info "Local embedder enabled — installing sentence-transformers and onnxruntime (first run may take up to 2 minutes)…"

    mkdir -p "$EXTRA_PACKAGES_DIR"

    if ! /opt/venv/bin/pip install \
            --target="$EXTRA_PACKAGES_DIR" \
            --no-cache-dir \
            --upgrade \
            sentence-transformers onnxruntime 2>&1; then
        bashio::log.error "Failed to install local embedder dependencies. Local embeddings will be unavailable."
        return 1
    fi

    touch "$EXTRA_MARKER"
    bashio::log.info "Local embedder dependencies installed successfully."
    return 0
}

if [ "${LOCAL_EMBEDDER_ENABLED}" = "true" ]; then
    if [ -f "$EXTRA_MARKER" ]; then
        bashio::log.info "Local embedder dependencies already installed (marker: $EXTRA_MARKER)"
    else
        install_local_embedder_deps || true
    fi

    # Добавляем папку с пакетами в PYTHONPATH, чтобы Python их видел
    export PYTHONPATH="${EXTRA_PACKAGES_DIR}:${PYTHONPATH}"
    bashio::log.info "PYTHONPATH extended with ${EXTRA_PACKAGES_DIR}"

    # Кэш моделей HuggingFace — тоже в /data, чтобы не перекачивать при перезапусках
    export HF_HOME="/data/.hf_cache"
    export TRANSFORMERS_CACHE="/data/.hf_cache"
    export SENTENCE_TRANSFORMERS_HOME="/data/.hf_cache"
    mkdir -p "$HF_HOME"
fi

# --- Запуск ----------------------------------------------------------------

exec /opt/venv/bin/uvicorn main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --log-level "${LOG_LEVEL}" \
    --proxy-headers \
    --forwarded-allow-ips='*'