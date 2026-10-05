"""Все пути и env-переменные в одном месте."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "/downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

RECIPES_FILE = DATA_DIR / "recipes.json"
MEAL_PLAN_FILE = DATA_DIR / "meal_plan.json"
SHOPPING_FILE = DATA_DIR / "shopping_list.json"

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

# --- Product lookup (shopping) ----------------------------------------------

# "auto" | "openfoodfacts" | "national"
CATALOG_SOURCE = os.environ.get("CATALOG_SOURCE", "auto").strip().lower()
CATALOG_API_KEY = os.environ.get("CATALOG_API_KEY", "")

OFF_USER_AGENT = "HomeAssistant-RecipeManager/1.0 (add-on)"
NATIONAL_CATALOG_URL = "https://апи.национальный-каталог.рф/v3/product"