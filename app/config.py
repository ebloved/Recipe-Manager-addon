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

TEMPLATE_FILE = BASE_DIR / "recipe_template.md"
STATIC_DIR = BASE_DIR / "static"

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
SUB_LANGS = os.environ.get("SUB_LANGS", "ru.*")
COOKIES_FILE = os.environ.get("COOKIES_FILE") or None