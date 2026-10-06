"""Связывание ингредиентов рецепта с продуктами базы.

Этот сервис решает одну конкретную задачу: берёт распарсенный рецепт
(в котором ингредиенты могут иметь `product.barcode` или `product.uuid`
из front matter) и превращает эти ссылки в реальные `product_id`
из `ingredients_store`.

Логика для каждого ингредиента:

  1. Нет блока `product` → пропускаем, оставляем как есть.
     Ингредиент позже может быть связан через matcher по имени.

  2. Есть `product.barcode`:
     a. Продукт с таким barcode уже в store → берём его product_id.
     b. Продукта нет → запрашиваем OFF по barcode.
        - OFF ответил → создаём продукт в store, берём product_id.
        - OFF не ответил/не нашёл → логируем, оставляем без product_id.

  3. Есть только `product.uuid` (без barcode):
     a. Продукт с таким uuid в store → берём product_id.
     b. Продукта нет → значит рецепт пришёл из чужой инсталляции,
        uuid оттуда нам ничего не говорит. Оставляем без product_id.

  4. Есть только `product.name` (без uuid и barcode):
     → не создаём продукт. Пользователь свяжет вручную или через matcher.

После успешной привязки временный блок `product` удаляется из ингредиента
(product_id остаётся как единственный источник правды).

Сервис не бросает исключений — ошибки логируются, но импорт рецепта
не падает. Это критично: недоступность OFF не должна ломать импорт
100 рецептов.

Публичные функции:
    link_recipe_ingredients(recipe) -> dict
    link_many_recipes(recipes) -> list[dict]
"""
from __future__ import annotations

import logging
from typing import Any

from stores import ingredients_store

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def link_recipe_ingredients(recipe: dict[str, Any]) -> dict[str, Any]:
    """Обогащает ингредиенты рецепта полем product_id.

    Возвращает тот же dict (модифицированный in-place для удобства).
    Добавляет в результат `_linker_stats` со счётчиками для диагностики.

    Никогда не бросает исключений — все ошибки логируются.
    """
    ingredients = recipe.get("ingredients") or []
    if not isinstance(ingredients, list):
        return recipe

    stats = {
        "total": 0,
        "linked_existing": 0,
        "linked_new": 0,
        "skipped": 0,
        "failed": 0,
    }

    # Кэш barcode → product_id в рамках одного вызова. Если у рецепта
    # два ингредиента с одинаковым barcode, второй получит результат
    # первого без повторного запроса в OFF.
    barcode_cache: dict[str, str | None] = {}

    for ing in ingredients:
        if not isinstance(ing, dict):
            continue

        product_block = ing.get("product")
        if not isinstance(product_block, dict):
            # Нет блока product — не наша забота
            continue

        stats["total"] += 1

        try:
            product_id, created = await _resolve_product(product_block, barcode_cache)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Linker: не удалось связать '%s': %s",
                ing.get("name"), exc,
            )
            stats["failed"] += 1
            continue

        if not product_id:
            stats["skipped"] += 1
            continue

        # Убираем временный блок, оставляем только product_id
        ing["product_id"] = product_id
        ing.pop("product", None)

        if created:
            stats["linked_new"] += 1
        else:
            stats["linked_existing"] += 1

    recipe["_linker_stats"] = stats

    if stats["total"] > 0:
        logger.info(
            "Linker: %d ингредиентов, existing=%d, new=%d, skipped=%d, failed=%d",
            stats["total"],
            stats["linked_existing"],
            stats["linked_new"],
            stats["skipped"],
            stats["failed"],
        )

    return recipe


async def link_many_recipes(recipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Обогащает список рецептов. Общий barcode-кэш между рецептами.

    Полезно при массовом импорте: если у 10 рецептов один и тот же
    греческий йогурт, OFF запрашивается один раз, а не десять.
    """
    barcode_cache: dict[str, str | None] = {}
    out: list[dict[str, Any]] = []

    for recipe in recipes:
        try:
            await _link_recipe_with_cache(recipe, barcode_cache)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Linker: рецепт '%s' пропущен: %s", recipe.get("name"), exc)
        out.append(recipe)

    return out


# ---------------------------------------------------------------------------
# Внутренние функции
# ---------------------------------------------------------------------------

async def _link_recipe_with_cache(
    recipe: dict[str, Any],
    barcode_cache: dict[str, str | None],
) -> None:
    """Версия link_recipe_ingredients с внешним кэшем barcode."""
    ingredients = recipe.get("ingredients") or []
    if not isinstance(ingredients, list):
        return

    stats = {"total": 0, "linked_existing": 0, "linked_new": 0, "skipped": 0, "failed": 0}

    for ing in ingredients:
        if not isinstance(ing, dict):
            continue
        product_block = ing.get("product")
        if not isinstance(product_block, dict):
            continue

        stats["total"] += 1

        try:
            product_id, created = await _resolve_product(product_block, barcode_cache)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Linker: '%s' не связан: %s", ing.get("name"), exc)
            stats["failed"] += 1
            continue

        if not product_id:
            stats["skipped"] += 1
            continue

        ing["product_id"] = product_id
        ing.pop("product", None)

        if created:
            stats["linked_new"] += 1
        else:
            stats["linked_existing"] += 1

    recipe["_linker_stats"] = stats


async def _resolve_product(
    product_block: dict[str, Any],
    barcode_cache: dict[str, str | None],
) -> tuple[str | None, bool]:
    """Возвращает (product_id, created).

    created=True — продукт создан в store в рамках этого вызова.
    created=False — продукт уже был.

    Порядок разрешения: barcode → uuid.
    """
    barcode = _clean_str(product_block.get("barcode"))
    uuid = _clean_str(product_block.get("uuid"))

    # --- Путь 1: barcode ---
    if barcode:
        # Сначала кэш в рамках сессии импорта
        if barcode in barcode_cache:
            cached = barcode_cache[barcode]
            return cached, False

        # Затем store
        existing = ingredients_store.get_by_barcode(barcode)
        if existing:
            pid = existing.get("product_id")
            barcode_cache[barcode] = pid
            return pid, False

        # Продукта нет — пробуем OFF
        created_id = await _create_from_off(barcode, product_block)
        barcode_cache[barcode] = created_id
        return created_id, bool(created_id)

    # --- Путь 2: uuid ---
    if uuid:
        existing = ingredients_store.get_active(uuid)
        if existing:
            return uuid, False
        # UUID из чужой инсталляции — бесполезен
        logger.debug("Linker: uuid %s не найден в local store, пропускаем", uuid)
        return None, False

    # Ни barcode, ни uuid — связывать нечем
    return None, False


async def _create_from_off(
    barcode: str,
    product_block: dict[str, Any],
) -> str | None:
    """Пытается создать продукт из данных OpenFoodFacts.

    Если OFF недоступен или товар не найден — возвращает None и
    логирует причину. Не бросает исключений.
    """
    # Импорт внутри функции — чтобы не создавать циклическую зависимость
    # и не падать, если модуль product_lookup ещё не собран.
    try:
        from services.product_lookup import lookup_barcode  # type: ignore[import]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Linker: product_lookup недоступен: %s", exc)
        return None

    try:
        off = await lookup_barcode(barcode)
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "Linker: OFF не дал данных по barcode %s (%s) — "
            "создам локальный продукт из front matter",
            barcode, exc,
        )
        # OFF недоступен — fallback: создать продукт из того, что есть
        # в product_block рецепта (обычно это name, brand, nutrition).
        return await _create_from_block(barcode, product_block)

    # OFF что-то вернул — обогащаем недостающими полями из product_block
    name = (product_block.get("name")
            or off.get("name")
            or f"Товар {barcode}")

    payload: dict[str, Any] = {
        "name": str(name).strip(),
        "barcode": barcode,
        "brand": product_block.get("brand") or off.get("brand"),
        "image_url": product_block.get("image_url") or off.get("image_url"),
        "category": product_block.get("category") or off.get("category"),
        "source": "openfoodfacts",
    }

    # Nutrition: приоритет у front matter (может быть уточнено пользователем),
    # иначе — то, что вернул OFF (в текущей версии lookup_barcode не отдаёт
    # nutrition, но структура готова).
    nutrition = product_block.get("nutrition_per_100g") or off.get("nutrition_per_100g")
    if isinstance(nutrition, dict) and nutrition:
        payload["nutrition_per_100g"] = nutrition

    if product_block.get("serving_size_g"):
        payload["serving_size_g"] = product_block["serving_size_g"]

    try:
        product = await ingredients_store.add(payload)
    except ValueError as exc:
        # Скорее всего конфликт по имени или barcode
        logger.warning("Linker: не удалось создать продукт '%s': %s", payload["name"], exc)
        return None

    logger.info(
        "Linker: создан продукт '%s' (barcode=%s, id=%s)",
        product["name"], barcode, product["product_id"][:8],
    )
    return product["product_id"]


async def _create_from_block(
    barcode: str,
    product_block: dict[str, Any],
) -> str | None:
    """Fallback: создаёт продукт только из данных front matter.

    Используется, когда OFF недоступен, но в рецепте есть хотя бы имя
    и, желательно, nutrition.
    """
    name = _clean_str(product_block.get("name"))
    if not name:
        # Без имени создавать нечего
        return None

    payload: dict[str, Any] = {
        "name": name,
        "barcode": barcode,
        "brand": product_block.get("brand"),
        "image_url": product_block.get("image_url"),
        "category": product_block.get("category"),
        "source": "recipe",
    }

    if isinstance(product_block.get("nutrition_per_100g"), dict):
        payload["nutrition_per_100g"] = product_block["nutrition_per_100g"]

    if product_block.get("serving_size_g"):
        payload["serving_size_g"] = product_block["serving_size_g"]

    try:
        product = await ingredients_store.add(payload)
    except ValueError as exc:
        logger.warning("Linker: fallback-создание '%s' не удалось: %s", name, exc)
        return None

    logger.info(
        "Linker: создан локальный продукт '%s' (barcode=%s, source=recipe)",
        product["name"], barcode,
    )
    return product["product_id"]


def _clean_str(value: Any) -> str | None:
    """Нормализует строковое поле: пустое → None."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None