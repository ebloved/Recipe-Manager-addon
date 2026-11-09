"""Все пути и env-переменные в одном месте."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# --- Режим развертывания (addon или standalone) ---
DEPLOY_MODE = os.environ.get("DEPLOY_MODE", "addon").strip().lower()
AUTH_MODE = os.environ.get("AUTH_MODE", "ha").strip().lower()
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "") # fallback

DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", str(BASE_DIR.parent / "downloads")))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR.parent / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Медиа рецептов: originals/variants не храним в JSON/SQLite.
MEDIA_DIR = Path(os.environ.get("MEDIA_DIR", str(DATA_DIR / "media")))
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# Кэш озвучки PTT (можно удалить — пересоберётся).
TTS_DIR = Path(os.environ.get("TTS_DIR", str(DATA_DIR / "tts")))
TTS_DIR.mkdir(parents=True, exist_ok=True)


# --- SECRET_KEY ------------------------------------------------------------
# В HA-аддоне переменная не задаётся, поэтому генерируем per-install ключ
# и храним его в DATA_DIR. Иначе все шифрованные поля жили бы на публичном
# дефолтном ключе.
def _load_secret_key() -> str:
    raw = (os.environ.get("SECRET_KEY") or "").strip()
    if raw and raw != "dev-secret-key-change-in-prod":
        return raw

    key_file = DATA_DIR / ".secret_key"
    try:
        if key_file.exists():
            existing = key_file.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        generated = secrets.token_urlsafe(48)
        key_file.write_text(generated, encoding="utf-8")
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        print(f"[config] generated per-install SECRET_KEY -> {key_file}")
        return generated
    except OSError as exc:
        print(f"[config] WARNING: cannot persist SECRET_KEY ({exc}); using ephemeral key")
        return secrets.token_urlsafe(48)


SECRET_KEY = _load_secret_key()

# --- Файлы данных ----------------------------------------------------------

DB_FILE = DATA_DIR / "rm.sqlite3"

RECIPES_FILE = DATA_DIR / "recipes.json"
MEAL_PLAN_FILE = DATA_DIR / "meal_plan.json"
SHOPPING_FILE = DATA_DIR / "shopping_list.json"
INGREDIENTS_FILE = DATA_DIR / "ingredients.json"
GEN_PROFILES_FILE = DATA_DIR / "gen_profiles.json"
OFF_CACHE_FILE = DATA_DIR / "off_cache.json"
EMBEDDINGS_CACHE_FILE = DATA_DIR / "embeddings_cache.json"
SUGGESTIONS_FILE = DATA_DIR / "suggestions.json"
MEAL_PLAN_DRAFTS_FILE = DATA_DIR / "meal_plan_drafts.json"

# --- Бэкапы -----------------------------------------------------------------
BACKUP_ENABLED = os.environ.get("BACKUP_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_INTERVAL_HOURS = int(os.environ.get("BACKUP_INTERVAL_HOURS", "24") or 24)
BACKUP_KEEP_DAYS = int(os.environ.get("BACKUP_KEEP_DAYS", "30") or 30)

# --- CORS -------------------------------------------------------------------
# Пусто = CORS не нужен (same-origin UI/BFF). Явный список — только при
# необходимости внешнего браузерного клиента.
CORS_ORIGINS = [
    item.strip()
    for item in (os.environ.get("CORS_ORIGINS") or "").split(",")
    if item.strip()
]

# Разрешать ли пользовательские URL на приватные адреса (только для локальной
# разработки; на публичном VPS — false).
ALLOW_PRIVATE_URLS = os.environ.get("ALLOW_PRIVATE_URLS", "false").strip().lower() in (
    "1", "true", "yes", "on",
)

# --- Sync / remote client -----------------------------------------------
SYNC_CONTRACT_VERSION = os.environ.get("SYNC_CONTRACT_VERSION", "1.0").strip() or "1.0"
SERVER_PUBLIC_URL = (os.environ.get("SERVER_PUBLIC_URL") or "").rstrip("/")
REMOTE_MODE = os.environ.get("REMOTE_MODE", "false").strip().lower() in ("1", "true", "yes", "on")
REMOTE_SERVER_URL = (os.environ.get("REMOTE_SERVER_URL") or "").rstrip("/")
REMOTE_DEVICE_TOKEN = os.environ.get("REMOTE_DEVICE_TOKEN", "").strip()
# Разрешать private/LAN-адрес сервера только для BFF-pairing.
# Не влияет на SSRF-защиту импорта и Custom LLM.
REMOTE_ALLOW_PRIVATE_URLS = os.environ.get(
    "REMOTE_ALLOW_PRIVATE_URLS", "false"
).strip().lower() in ("1", "true", "yes", "on")

# --- Шаблоны и статика -----------------------------------------------------

TEMPLATE_FILE = BASE_DIR / "recipe_template.md"
BASE_PRODUCTS_FILE = BASE_DIR / "base_products.json"
BASE_PROFILES_FILE = BASE_DIR / "base_profiles.json"
STATIC_DIR = BASE_DIR / "static"

# --- Gemini (генерация рецептов, embeddings) -------------------------------

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODELS = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_MODELS",
        "gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash",
    ).split(",")
    if m.strip()
]
GEMINI_PROXY = os.environ.get("GEMINI_PROXY") or None

# --- OrcaRouter (только user-ключи) ---
ORC_BASE_URL = os.environ.get("ORC_BASE_URL", "https://api.orcarouter.ai/v1").strip().rstrip("/")
ORC_MODEL = os.environ.get("ORC_MODEL", "deepseek/deepseek-v4.1-flash-free").strip()
_orc_models_env = os.environ.get("ORC_MODELS", "").strip()
ORC_MODELS: list[str] = (
    [m.strip() for m in _orc_models_env.split(",") if m.strip()]
    if _orc_models_env
    else [
        "tencent/hy4-preview-free",
        "deepseek/deepseek-v4.1-flash-free",
        "deepseek/deepseek-v4-flash-free",
        "orca/orcaverify-text1.0-free",
    ]
)
ORC_TIMEOUT = float(os.environ.get("ORC_TIMEOUT", "120") or 120)

# --- yt-dlp -----------------------------------------------------------------

def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


# Глобальный выключатель YouTube-импорта: скрывает вкладку и отдаёт 503.
FEATURE_YOUTUBE_IMPORT = _env_bool("FEATURE_YOUTUBE_IMPORT", True)

# --- Apify (единственный источник транскриптов YouTube) ---------------------

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
APIFY_ACTOR_ID = (
    os.environ.get("APIFY_ACTOR_ID", "").strip()
    or "automationnation/youtube-transcript-scraper"
)
APIFY_BASE_URL = os.environ.get("APIFY_BASE_URL", "https://api.apify.com/v2").rstrip("/")
APIFY_TIMEOUT = float(os.environ.get("APIFY_TIMEOUT", "180") or 180)
# Запасной лимит, если Apify не вернул maxMonthlyUsageUsd (free plan = $5).
APIFY_QUOTA_LIMIT_USD = float(os.environ.get("APIFY_QUOTA_LIMIT_USD", "5") or 5)
# Порог, после которого импорт блокируется (0.9 = 90%).
APIFY_STOP_RATIO = float(os.environ.get("APIFY_STOP_RATIO", "0.9") or 0.9)

# --- OpenFoodFacts ---------------------------------------------------------

OFF_ENABLED = os.environ.get("OFF_ENABLED", "true").strip().lower() == "true"
OFF_CONTRIBUTE_ENABLED = os.environ.get("OFF_CONTRIBUTE_ENABLED", "false").strip().lower() == "true"
OFF_USER_ID = os.environ.get("OFF_USER_ID", "").strip()
OFF_PASSWORD = os.environ.get("OFF_PASSWORD", "")
OFF_USER_AGENT = os.environ.get(
    "OFF_USER_AGENT",
    "HomeAssistant-RecipeManager/1.0 (add-on)",
).strip()
OFF_SUBDOMAIN = os.environ.get("OFF_SUBDOMAIN", "world").strip() or "world"
OFF_TIMEOUT_SEC = float(os.environ.get("OFF_TIMEOUT_SEC", "10") or 10)
OFF_CACHE_TTL_DAYS = int(os.environ.get("OFF_CACHE_TTL_DAYS", "7") or 7)

# --- Матчинг ингредиентов --------------------------------------------------

MATCHER_PROVIDER = os.environ.get("MATCHER_PROVIDER", "auto").strip().lower()
MATCHER_EXTERNAL_ENABLED = os.environ.get("MATCHER_EXTERNAL_ENABLED", "false").strip().lower() == "true"
MATCHER_EXTERNAL_URL = os.environ.get("MATCHER_EXTERNAL_URL", "").strip().rstrip("/")
MATCHER_EXTERNAL_KEY = os.environ.get("MATCHER_EXTERNAL_KEY", "")
MATCHER_EXTERNAL_MODEL = os.environ.get("MATCHER_EXTERNAL_MODEL", "hermes-agent").strip()
MATCHER_EXTERNAL_EMBEDDING_MODEL = os.environ.get("MATCHER_EXTERNAL_EMBEDDING_MODEL", "").strip()
MATCHER_EXTERNAL_TIMEOUT = float(os.environ.get("MATCHER_EXTERNAL_TIMEOUT", "15") or 15)

MATCHER_DAILY_LIMIT = int(os.environ.get("MATCHER_DAILY_LIMIT", "200") or 200)
MATCHER_AUTO_THRESHOLD = float(os.environ.get("MATCHER_AUTO_THRESHOLD", "0.95") or 0.95)
MATCHER_SUGGEST_THRESHOLD = float(os.environ.get("MATCHER_SUGGEST_THRESHOLD", "0.80") or 0.80)
MATCHER_CONFIRM_MODE = os.environ.get("MATCHER_CONFIRM_MODE", "single").strip().lower()

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001").strip()
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "768") or 768)

# --- Локальный эмбеддер (sentence-transformers + ONNX) ---------------------

LOCAL_EMBEDDER_ENABLED = os.environ.get("LOCAL_EMBEDDER_ENABLED", "false").strip().lower() == "true"
LOCAL_EMBEDDER_MODEL = os.environ.get(
    "LOCAL_EMBEDDER_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
).strip()
LOCAL_EMBEDDER_ONNX = os.environ.get("LOCAL_EMBEDDER_ONNX", "true").strip().lower() == "true"
LOCAL_EMBEDDER_MAX_CONCURRENT = int(os.environ.get("LOCAL_EMBEDDER_MAX_CONCURRENT", "1") or 1)

# --- Semantic enricher (built-in, admin Gemini key) -------------------------
SEMANTIC_ENRICHER_ENABLED = os.environ.get(
    "SEMANTIC_ENRICHER_ENABLED", "true"
).strip().lower() in ("1", "true", "yes", "on")
SEMANTIC_ENRICHER_IDLE_SECONDS = int(
    os.environ.get("SEMANTIC_ENRICHER_IDLE_SECONDS", "600") or 600
)
SEMANTIC_ENRICHER_INTERVAL_SECONDS = int(
    os.environ.get("SEMANTIC_ENRICHER_INTERVAL_SECONDS", "60") or 60
)
SEMANTIC_ENRICHER_MODELS = [
    x.strip()
    for x in (
        os.environ.get(
            "SEMANTIC_ENRICHER_MODELS",
            "gemini-3.5-flash-lite,gemini-3.1-flash-lite",
        )
    ).split(",")
    if x.strip()
]

# --- GitHub sync ------------------------------------------------------------

GITHUB_REPO = os.environ.get("GITHUB_REPO", "").strip()
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "").strip()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main").strip() or "main"
GITHUB_PATH = os.environ.get("GITHUB_PATH", "recipes.json").strip() or "recipes.json"
GITHUB_INGREDIENTS_ENABLED = (
    os.environ.get("GITHUB_INGREDIENTS_ENABLED", "true").strip().lower() == "true"
)
GITHUB_INGREDIENTS_PATH = (
    os.environ.get("GITHUB_INGREDIENTS_PATH", "ingredients.json").strip()
    or "ingredients.json"
)

# --- Generator ------------------------------------------------------------

GENERATOR_MAX_COUNT = int(os.environ.get("GENERATOR_MAX_COUNT", "5") or 5)
GENERATOR_DEFAULT_COUNT = int(os.environ.get("GENERATOR_DEFAULT_COUNT", "1") or 1)
GENERATOR_SAMPLES_MAX = int(os.environ.get("GENERATOR_SAMPLES_MAX", "10") or 10)
GENERATOR_DEFAULT_SAMPLES = int(os.environ.get("GENERATOR_DEFAULT_SAMPLES", "2") or 2)
GENERATOR_MAX_TOKENS = int(os.environ.get("GENERATOR_MAX_TOKENS", "15000") or 15000)
GENERATOR_AUTO_ACTIVE_TIME = os.environ.get("GENERATOR_AUTO_ACTIVE_TIME", "false").strip().lower() == "true"

# --- Нормализация рецептов (фон) ------------------------------------------

RECIPE_NORMALIZER_ENABLED = (
    os.environ.get("RECIPE_NORMALIZER_ENABLED", "false").strip().lower() == "true"
)
RECIPE_ENRICHER_ENABLED = (
    os.environ.get("RECIPE_ENRICHER_ENABLED", "false").strip().lower() == "true"
)
RECIPE_NORMALIZER_START_DELAY = int(
    os.environ.get("RECIPE_NORMALIZER_START_DELAY", "60") or 60
)
RECIPE_NORMALIZER_INTERVAL = int(
    os.environ.get("RECIPE_NORMALIZER_INTERVAL", "300") or 300
)

# --- Feature flags ---------------------------------------------------------

FEATURE_PRODUCTS = os.environ.get("FEATURE_PRODUCTS", "true").strip().lower() == "true"
FEATURE_MATCHER = os.environ.get("FEATURE_MATCHER", "false").strip().lower() == "true"
FEATURE_PROFILES = os.environ.get("FEATURE_PROFILES", "false").strip().lower() == "true"
FEATURE_GENERATOR = os.environ.get("FEATURE_GENERATOR", "false").strip().lower() == "true"

# --- Режим работы ----------------------------------------------------------

RUNTIME_MODE = os.environ.get("RUNTIME_MODE", "standard").strip().lower() or "standard"

ADDON_VERSION = os.environ.get("ADDON_VERSION", "unknown")

# --- Test mode (только для smoke-test в dev) ---
# При TEST_MODE=true запросы с loopback (127.0.0.1/::1) и заголовком
# X-Test-Token == TEST_TOKEN получают фейкового админа.
# НИКОГДА не включать в prod.
TEST_MODE = os.environ.get("TEST_MODE", "false").strip().lower() == "true"
TEST_TOKEN = os.environ.get("TEST_TOKEN", "")


# --- Standalone Embeddings ---
STANDALONE_EMBEDDING_MODEL = os.environ.get("STANDALONE_EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
SERVICE_TOKEN = os.environ.get("SERVICE_TOKEN", "")

# --- Магазины: ВкусВилл OAuth 2.0 + PKCE -------------------------------
# client_id/secret — глобальные для приложения, токены — per-user в SQLite.
VKUSVILL_CLIENT_ID = os.environ.get("VKUSVILL_CLIENT_ID", "").strip()
VKUSVILL_CLIENT_SECRET = os.environ.get("VKUSVILL_CLIENT_SECRET", "").strip()
VKUSVILL_REDIRECT_URI = os.environ.get("VKUSVILL_REDIRECT_URI", "").strip()
VKUSVILL_SCOPES = os.environ.get(
    "VKUSVILL_SCOPES",
    "catalog.search purchase_history.read discounts.view "
    "recommendations.personalized offline_access",
).strip()
VKUSVILL_AUTH_URL = os.environ.get(
    "VKUSVILL_AUTH_URL", "https://oauth.vkusvill.ru/oauth2/auth"
).strip()
VKUSVILL_TOKEN_URL = os.environ.get(
    "VKUSVILL_TOKEN_URL", "https://oauth.vkusvill.ru/oauth2/token"
).strip()
VKUSVILL_REVOKE_URL = os.environ.get(
    "VKUSVILL_REVOKE_URL", "https://oauth.vkusvill.ru/oauth2/revoke"
).strip()
VKUSVILL_MCP_URL = os.environ.get(
    "VKUSVILL_MCP_URL", "https://mcp.vkusvill.ru/mcp"
).strip()
VKUSVILL_MCP_TIMEOUT = float(os.environ.get("VKUSVILL_MCP_TIMEOUT", "30") or 30)
VKUSVILL_MAX_CART_ITEMS = int(os.environ.get("VKUSVILL_MAX_CART_ITEMS", "100") or 100)
VKUSVILL_LLM_TIMEOUT = float(os.environ.get("VKUSVILL_LLM_TIMEOUT", "120") or 120)
VKUSVILL_PROXY = os.environ.get("VKUSVILL_PROXY") or None
