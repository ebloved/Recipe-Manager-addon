"""Собирает все роутеры в один api_router.

Порядок регистрации критичен:

  1. `imports` идёт ПЕРЕД `recipes`, потому что содержит
     `/api/recipes/import-url`, `/api/recipes/import-text`,
     `/api/recipes/import-batch`, `/api/recipes/import-batch`.
     Если зарегистрировать `recipes` первым, эти пути попадут в
     `/{recipe_id}` и вернут 404.

  2. `products`, `matcher`, `backup`, `sync`, `shopping`, `meal_plan`,
     `youtube` — все идут до `recipes`, чтобы их префиксы
     (`/api/products/...`, `/api/matcher/...` и т.д.) не конфликтовали
     с `/{recipe_id}` в `recipes`.

  3. `recipes` — предпоследний: у него есть catch-all `/{recipe_id}`,
     который должен матчиться только после того, как все конкретные
     пути уже проверены.

  4. `misc` — последний: он содержит `GET /` и `/files/{filename}`,
     которые должны идти в самом конце цепочки.
"""
from fastapi import APIRouter

from . import (
    imports,
    youtube,
    meal_plan,
    shopping,
    sync,
    products,
    matcher,
    backup,
    recipes,
    misc,
)

api_router = APIRouter()

# --- Импорт данных из внешних источников ---
# Должен идти ПЕРЕД recipes, потому что содержит подпути /api/recipes/import-*
api_router.include_router(imports.router)

# --- YouTube → рецепт ---
api_router.include_router(youtube.router)

# --- План питания ---
api_router.include_router(meal_plan.router)

# --- Список покупок ---
api_router.include_router(shopping.router)

# --- Синхронизация с GitHub ---
api_router.include_router(sync.router)

# --- База продуктов (CRUD) ---
api_router.include_router(products.router)

# --- Матчинг ингредиентов ---
api_router.include_router(matcher.router)

# --- Бэкапы ---
api_router.include_router(backup.router)

# --- Рецепты (CRUD + export.md + import-md) ---
# Идёт после всего, что может конфликтовать с /{recipe_id}
api_router.include_router(recipes.router)

# --- Прочее: /, /files/*, /api/health ---
api_router.include_router(misc.router)


__all__ = ["api_router"]