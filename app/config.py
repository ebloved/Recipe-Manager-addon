"""Все пути и env-переменные в одном месте."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# --- Пути ------------------------------------------------------------------

DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "/downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

RECIPES_FILE = DATA_DIR / "recipes.json"
MEAL_PLAN_FILE = DATA_DIR / "meal_plan.json"
SHOPPING_FILE = DATA_DIR / "shopping_list.json"
INGREDIENTS_FILE = DATA_DIR / "ingredients.json"

BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATE_FILE = BASE_DIR / "recipe_template.md"
STATIC_DIR = BASE_DIR / "static"

# --- Gemini -----------------------------------------------------------------

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

# --- Product lookup (shopping / OpenFoodFacts) ------------------------------

OFF_USER_AGENT = "HomeAssistant-RecipeManager/1.0 (add-on)"

# --- GitHub sync ------------------------------------------------------------

GITHUB_REPO = os.environ.get("GITHUB_REPO", "").strip()          # "user/repo"
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "").strip()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main").strip() or "main"
GITHUB_PATH = os.environ.get("GITHUB_PATH", "recipes.json").strip() or "recipes.json"
GITHUB_INGREDIENTS_PATH = (
    os.environ.get("GITHUB_INGREDIENTS_PATH", "ingredients.json").strip()
    or "ingredients.json"
)

# --- Matcher (каскад матчинга ингредиентов) ---------------------------------

# Общий режим:
#   auto        — использовать каскад со всеми доступными провайдерами
#   gemini      — только Gemini (эмбеддинги + генеративный)
#   external    — только внешний OpenAI-совместимый endpoint
#   local       — только локальные методы (fuzzy + локальные эмбеддинги)
#   none        — отключить каскад, работать через ручное подтверждение
MATCHER_PROVIDER = os.environ.get("MATCHER_PROVIDER", "auto").strip().lower()

# Пороги
try:
    MATCHER_AUTO_THRESHOLD = float(os.environ.get("MATCHER_AUTO_THRESHOLD", "0.95"))
except ValueError:
    MATCHER_AUTO_THRESHOLD = 0.95
try:
    MATCHER_SUGGEST_THRESHOLD = float(os.environ.get("MATCHER_SUGGEST_THRESHOLD", "0.80"))
except ValueError:
    MATCHER_SUGGEST_THRESHOLD = 0.80

# Лимит запросов к внешним LLM/embedding-провайдерам в день (0 = без лимита)
try:
    MATCHER_DAILY_LIMIT = int(os.environ.get("MATCHER_DAILY_LIMIT", "200"))
except ValueError:
    MATCHER_DAILY_LIMIT = 200

# Режим подтверждения автосвязок:
#   single  — спрашивать для каждой связки отдельно (при одиночном добавлении)
#   batch   — копить в очередь и показывать один раз (при массовом импорте)
#   auto    — auto-связки (>= auto_threshold) применять сразу, без вопросов
MATCHER_CONFIRM_MODE = os.environ.get("MATCHER_CONFIRM_MODE", "single").strip().lower()

# Внешний OpenAI-совместимый endpoint (Hermes, OpenRouter, Groq, Ollama, ...)
MATCHER_EXTERNAL_ENABLED = (
    os.environ.get("MATCHER_EXTERNAL_ENABLED", "false").strip().lower() in ("1", "true", "yes")
)
MATCHER_EXTERNAL_URL = os.environ.get("MATCHER_EXTERNAL_URL", "").strip()   # http://host:port/v1
MATCHER_EXTERNAL_KEY = os.environ.get("MATCHER_EXTERNAL_KEY", "")
MATCHER_EXTERNAL_MODEL = (
    os.environ.get("MATCHER_EXTERNAL_MODEL", "hermes-agent").strip() or "hermes-agent"
)
MATCHER_EXTERNAL_EMBEDDING_MODEL = (
    os.environ.get("MATCHER_EXTERNAL_EMBEDDING_MODEL", "").strip() or None
)

# Таймаут для внешних запросов, секунды
try:
    MATCHER_EXTERNAL_TIMEOUT = float(os.environ.get("MATCHER_EXTERNAL_TIMEOUT", "15"))
except ValueError:
    MATCHER_EXTERNAL_TIMEOUT = 15.0

# OpenRouter (fallback эмбеддингов)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_EMBEDDING_MODEL = (
    os.environ.get("OPENROUTER_EMBEDDING_MODEL", "openai/text-embedding-3-small").strip()
    or "openai/text-embedding-3-small"
)

# Groq (fallback эмбеддингов)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_EMBEDDING_MODEL = (
    os.environ.get("GROQ_EMBEDDING_MODEL", "nomic-embed-text-v1_5").strip()
    or "nomic-embed-text-v1_5"
)

# Локальные эмбеддинги через sentence-transformers (OFF по умолчанию, т.к. нет GPU-зависимостей)
LOCAL_EMBEDDER_ENABLED = (
    os.environ.get("LOCAL_EMBEDDER_ENABLED", "false").strip().lower() in ("1", "true", "yes")
)
LOCAL_EMBEDDER_MODEL = (
    os.environ.get("LOCAL_EMBEDDER_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2").strip()
    or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
LOCAL_EMBEDDER_ONNX = (
    os.environ.get("LOCAL_EMBEDDER_ONNX", "true").strip().lower() in ("1", "true", "yes")
)
LOCAL_EMBEDDER_MAX_CONCURRENT = int(os.environ.get("LOCAL_EMBEDDER_MAX_CONCURRENT", "1") or 1)

# --- Backup -----------------------------------------------------------------

BACKUP_ENABLED = (
    os.environ.get("BACKUP_ENABLED", "true").strip().lower() in ("1", "true", "yes")
)
try:
    BACKUP_KEEP_DAYS = int(os.environ.get("BACKUP_KEEP_DAYS", "7"))
except ValueError:
    BACKUP_KEEP_DAYS = 7
try:
    BACKUP_INTERVAL_HOURS = int(os.environ.get("BACKUP_INTERVAL_HOURS", "24"))
except ValueError:
    BACKUP_INTERVAL_HOURS = 24