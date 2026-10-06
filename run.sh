#!/usr/bin/with-contenv bashio
set -e

CONFIG_PATH=/data/options.json

# --- Пути для опциональной установки зависимостей -------------------------
EXTRA_PACKAGES_DIR="/data/.extra_packages"
EXTRA_MARKER="${EXTRA_PACKAGES_DIR}/.installed"

# --- Режим работы ----------------------------------------------------------
export RUNTIME_MODE="$(jq --raw-output '.runtime_mode // "standard"' $CONFIG_PATH)"

# --- Gemini ---------------------------------------------------------------
export GEMINI_API_KEY="$(jq --raw-output '.gemini_api_key // ""' $CONFIG_PATH)"
export GEMINI_MODELS="$(jq --raw-output '.gemini_models // "gemini-3.8-flash"' $CONFIG_PATH)"
export GEMINI_PROXY="$(jq --raw-output '.gemini_proxy // ""' $CONFIG_PATH)"

# --- yt-dlp ---------------------------------------------------------------
export SUB_LANGS="$(jq --raw-output '.sub_langs // "ru.*"' $CONFIG_PATH)"
export COOKIES_FILE="$(jq --raw-output '.cookies_file // ""' $CONFIG_PATH)"

# --- Open Food Facts ------------------------------------------------------
export OFF_ENABLED="$(jq --raw-output '.off_enabled // true' $CONFIG_PATH)"
export OFF_SUBDOMAIN="$(jq --raw-output '.off_subdomain // "world"' $CONFIG_PATH)"
export OFF_USER_AGENT="$(jq --raw-output '.off_user_agent // "HomeAssistant-RecipeManager/1.0 (add-on)"' $CONFIG_PATH)"
export OFF_CACHE_TTL_DAYS="$(jq --raw-output '.off_cache_ttl_days // 7' $CONFIG_PATH)"
export OFF_CONTRIBUTE_ENABLED="$(jq --raw-output '.off_contribute_enabled // false' $CONFIG_PATH)"
export OFF_USER_ID="$(jq --raw-output '.off_user_id // ""' $CONFIG_PATH)"
export OFF_PASSWORD="$(jq --raw-output '.off_password // ""' $CONFIG_PATH)"

# --- Матчинг ингредиентов -------------------------------------------------
export MATCHER_PROVIDER="$(jq --raw-output '.matcher_provider // "auto"' $CONFIG_PATH)"
export MATCHER_CONFIRM_MODE="$(jq --raw-output '.matcher_confirm_mode // "single"' $CONFIG_PATH)"
export MATCHER_AUTO_THRESHOLD="$(jq --raw-output '.matcher_auto_threshold // 0.95' $CONFIG_PATH)"
export MATCHER_SUGGEST_THRESHOLD="$(jq --raw-output '.matcher_suggest_threshold // 0.80' $CONFIG_PATH)"
export MATCHER_DAILY_LIMIT="$(jq --raw-output '.matcher_daily_limit // 200' $CONFIG_PATH)"

export MATCHER_EXTERNAL_ENABLED="$(jq --raw-output '.matcher_external_enabled // false' $CONFIG_PATH)"
export MATCHER_EXTERNAL_URL="$(jq --raw-output '.matcher_external_url // ""' $CONFIG_PATH)"
export MATCHER_EXTERNAL_KEY="$(jq --raw-output '.matcher_external_key // ""' $CONFIG_PATH)"
export MATCHER_EXTERNAL_MODEL="$(jq --raw-output '.matcher_external_model // "hermes-agent"' $CONFIG_PATH)"
export MATCHER_EXTERNAL_EMBEDDING_MODEL="$(jq --raw-output '.matcher_external_embedding_model // ""' $CONFIG_PATH)"
export MATCHER_EXTERNAL_TIMEOUT="$(jq --raw-output '.matcher_external_timeout // 15' $CONFIG_PATH)"

export EMBEDDING_MODEL="$(jq --raw-output '.embedding_model // "gemini-embedding-001"' $CONFIG_PATH)"
export EMBEDDING_DIM="$(jq --raw-output '.embedding_dim // 768' $CONFIG_PATH)"

# --- Локальный эмбеддер ---------------------------------------------------
export LOCAL_EMBEDDER_ENABLED="$(jq --raw-output '.local_embedder_enabled // false' $CONFIG_PATH)"
export LOCAL_EMBEDDER_MODEL="$(jq --raw-output '.local_embedder_model // "sentence-transformers/all-MiniLM-L6-v2"' $CONFIG_PATH)"
export LOCAL_EMBEDDER_ONNX="$(jq --raw-output '.local_embedder_onnx // true' $CONFIG_PATH)"
export LOCAL_EMBEDDER_MAX_CONCURRENT="$(jq --raw-output '.local_embedder_max_concurrent // 1' $CONFIG_PATH)"

# --- GitHub sync ----------------------------------------------------------
export GITHUB_REPO="$(jq --raw-output '.github_repo // ""' $CONFIG_PATH)"
export GITHUB_USERNAME="$(jq --raw-output '.github_username // ""' $CONFIG_PATH)"
export GITHUB_TOKEN="$(jq --raw-output '.github_token // ""' $CONFIG_PATH)"
export GITHUB_BRANCH="$(jq --raw-output '.github_branch // "main"' $CONFIG_PATH)"
export GITHUB_PATH="$(jq --raw-output '.github_path // "recipes.json"' $CONFIG_PATH)"
export GITHUB_INGREDIENTS_ENABLED="$(jq --raw-output '.github_ingredients_enabled // true' $CONFIG_PATH)"
export GITHUB_INGREDIENTS_PATH="$(jq --raw-output '.github_ingredients_path // "ingredients.json"' $CONFIG_PATH)"

# --- Прочее ---------------------------------------------------------------
export LOG_LEVEL="$(jq --raw-output '.log_level // "info"' $CONFIG_PATH)"

# --- Feature flags выводятся из runtime_mode ------------------------------
case "${RUNTIME_MODE}" in
    minimal)
        export FEATURE_PRODUCTS="false"
        export FEATURE_MATCHER="false"
        export FEATURE_PROFILES="false"
        export FEATURE_GENERATOR="false"
        ;;
    standard)
        export FEATURE_PRODUCTS="true"
        export FEATURE_MATCHER="false"
        export FEATURE_PROFILES="false"
        export FEATURE_GENERATOR="false"
        ;;
    full)
        export FEATURE_PRODUCTS="true"
        export FEATURE_MATCHER="true"
        export FEATURE_PROFILES="true"
        export FEATURE_GENERATOR="true"
        ;;
    *)
        bashio::log.warning "Unknown runtime_mode '${RUNTIME_MODE}', falling back to 'standard'"
        export RUNTIME_MODE="standard"
        export FEATURE_PRODUCTS="true"
        export FEATURE_MATCHER="false"
        export FEATURE_PROFILES="false"
        export FEATURE_GENERATOR="false"
        ;;
esac

# ==========================================================================
# Локальный эмбеддер: опциональная установка sentence-transformers + onnxruntime
# ==========================================================================
#
# Устанавливаем только если пользователь включил local_embedder_enabled=true.
# Пакеты идут в /data/.extra_packages — персистентная папка, переживает
# пересборку образа и перезапуски контейнера. Маркер .installed не даёт
# повторять pip install при каждом старте.
#
# Установка занимает 30–120 секунд при первом запуске (зависит от скорости
# сети до PyPI). Модель HuggingFace скачается в /data/.hf_cache при первом
# использовании эмбеддера.

install_local_embedder_deps() {
    bashio::log.info "Local embedder enabled — installing sentence-transformers and onnxruntime (first run may take up to 2 minutes)…"
    mkdir -p "$EXTRA_PACKAGES_DIR"

    if ! /opt/venv/bin/pip install \
            --target="$EXTRA_PACKAGES_DIR" \
            --no-cache-dir \
            --upgrade \
            sentence-transformers onnxruntime 2>&1; then
        bashio::log.error "Failed to install local embedder deps. Local embeddings will be unavailable."
        return 1
    fi

    touch "$EXTRA_MARKER"
    bashio::log.info "Local embedder deps installed successfully."
    return 0
}

if [ "${LOCAL_EMBEDDER_ENABLED}" = "true" ]; then
    if [ -f "$EXTRA_MARKER" ]; then
        bashio::log.info "Local embedder deps already installed (marker: $EXTRA_MARKER)"
    else
        install_local_embedder_deps || true
    fi

    # Продлеваем PYTHONPATH, чтобы Python видел пакеты из /data/.extra_packages
    export PYTHONPATH="${EXTRA_PACKAGES_DIR}:${PYTHONPATH}"
    bashio::log.info "PYTHONPATH extended with ${EXTRA_PACKAGES_DIR}"

    # Кэш моделей HuggingFace — в /data, чтобы не перекачивать при перезапусках
    export HF_HOME="/data/.hf_cache"
    export TRANSFORMERS_CACHE="/data/.hf_cache"
    export SENTENCE_TRANSFORMERS_HOME="/data/.hf_cache"
    mkdir -p "$HF_HOME"
fi

# --- Логирование конфигурации ---------------------------------------------
bashio::log.info "Starting Recipe Manager add-on on port 8099"
bashio::log.info "Runtime mode: ${RUNTIME_MODE}"
bashio::log.info "Models: ${GEMINI_MODELS}"
bashio::log.info "API key configured: $([ -n "${GEMINI_API_KEY}" ] && echo yes || echo no)"
bashio::log.info "Sub langs: ${SUB_LANGS}"
bashio::log.info "Open Food Facts: $([ "${OFF_ENABLED}" = "true" ] && echo "enabled (${OFF_SUBDOMAIN})" || echo "disabled")"
bashio::log.info "OFF contribute: $([ "${OFF_CONTRIBUTE_ENABLED}" = "true" ] && echo "yes" || echo "no")"
bashio::log.info "Matcher: ${MATCHER_PROVIDER}$([ "${MATCHER_EXTERNAL_ENABLED}" = "true" ] && echo " + external" || echo "")"
bashio::log.info "Local embedder: $([ "${LOCAL_EMBEDDER_ENABLED}" = "true" ] && echo "enabled (${LOCAL_EMBEDDER_MODEL})" || echo "disabled")"
bashio::log.info "GitHub: $([ -n "${GITHUB_REPO}" ] && echo "${GITHUB_REPO}@${GITHUB_BRANCH}" || echo 'not configured')"
bashio::log.info "GitHub ingredients sync: $([ "${GITHUB_INGREDIENTS_ENABLED}" = "true" ] && echo "yes (${GITHUB_INGREDIENTS_PATH})" || echo "no")"
bashio::log.info "Features: products=${FEATURE_PRODUCTS} matcher=${FEATURE_MATCHER} profiles=${FEATURE_PROFILES} generator=${FEATURE_GENERATOR}"

exec /opt/venv/bin/uvicorn main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --log-level "${LOG_LEVEL}" \
    --proxy-headers \
    --forwarded-allow-ips='*'