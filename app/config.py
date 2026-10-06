"""Все пути и env-переменные в одном месте."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "/downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- Файлы данных ----------------------------------------------------------

RECIPES_FILE = DATA_DIR / "recipes.json"
MEAL_PLAN_FILE = DATA_DIR / "meal_plan.json"
SHOPPING_FILE = DATA_DIR / "shopping_list.json"
INGREDIENTS_FILE = DATA_DIR / "ingredients.json"
GEN_PROFILES_FILE = DATA_DIR / "gen_profiles.json"
OFF_CACHE_FILE = DATA_DIR / "off_cache.json"
EMBEDDINGS_CACHE_FILE = DATA_DIR / "embeddings_cache.json"

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

# --- yt-dlp -----------------------------------------------------------------

SUB_LANGS = os.environ.get("SUB_LANGS", "ru.*")
COOKIES_FILE = os.environ.get("COOKIES_FILE") or None

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

# --- Feature flags ---------------------------------------------------------

FEATURE_PRODUCTS = os.environ.get("FEATURE_PRODUCTS", "true").strip().lower() == "true"
FEATURE_MATCHER = os.environ.get("FEATURE_MATCHER", "false").strip().lower() == "true"
FEATURE_PROFILES = os.environ.get("FEATURE_PROFILES", "false").strip().lower() == "true"
FEATURE_GENERATOR = os.environ.get("FEATURE_GENERATOR", "false").strip().lower() == "true"

# --- Режим работы ----------------------------------------------------------

RUNTIME_MODE = os.environ.get("RUNTIME_MODE", "standard").strip().lower() or "standard"