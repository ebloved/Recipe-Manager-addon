"""Сборка меню на неделю и генерация недостающих рецептов.

План собирается в два слоя:
  1. существующие записи плана и подходящие рецепты из базы;
  2. LLM-рецепты только для пустых слотов, с лимитом новых рецептов.

Рецепты из LLM не попадают в библиотеку, пока пользователь не одобрит их.
"""
from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from config import GENERATOR_MAX_TOKENS
from recipe_manager.importer import parse_markdown_recipe
from services.generator.generator import _clean_md, _SPLIT_RE
from services.generator.prompt import _fmt_list, _fmt_num, _recipe_to_md
from services.llm_cascade import call_llm_cascade
from stores import (
    gen_profiles_store,
    jobs_store,
    meal_plan_drafts_store,
    meal_plan_store,
    recipe_store,
    suggestions_store,
)
from stores.settings import settings_store

MEAL_LABELS = {
    "breakfast": "Завтрак",
    "lunch": "Обед",
    "snack": "Полдник",
    "dinner": "Ужин",
}
ALLOWED_MEALS = ("breakfast", "lunch", "snack", "dinner")
MAX_NEW_DEFAULT = 10
BATCH_SIZE = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("ё", "е")


def _values(recipe: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("tags", "courses", "categories", "collections"):
        for item in recipe.get(key) or []:
            text = _norm(item)
            if text:
                out.append(text)
    for key in ("category", "name", "description"):
        text = _norm(recipe.get(key))
        if text:
            out.append(text)
    return out


_BREAKFAST = (
    "завтрак", "каша", "овсян", "омлет", "яичн", "сырник", "блин", "олад",
    "тост", "бутерброд", "гранол", "мюсли", "йогурт", "творог", "круассан",
)
_SALAD = ("салат",)
_SIDE = ("гарнир",)
_DESSERT = ("десерт", "выпеч", "сладк")
_SOUP = ("суп", "борщ", "похлеб", "бульон", "рассольник", "солянк")
_DRINK = ("напиток", "смузи", "компот", "морс")
_MAIN_KEYWORDS = (
    "мясо", "рыб", "котлет", "куриц", "индейк", "запекан", "плов", "паста",
    "стейк", "гуляш", "рагу", "лазань", "пельмен", "тефтел",
)
_MAIN_COURSE = ("основное", "горячее", "второе")
SELF_CONTAINED_TAG = "самостоятельное"
NEEDS_SIDE_TAG = "нужен гарнир"
_SELF_CONTAINED_KEYWORDS = (
    "картоф", "рис", "греч", "паста", "макарон", "спагет", "лапш", "пюре",
    "овощ", "брокколи", "капуст", "фасол", "горош", "кукуруз", "булгур",
    "кус-кус", "киноа", "плов", "пельмен", "вареник", "лазань", "пицц",
    "бургер", "шаурм", "запекан", "рагу", "суп",
)
MAX_SIDE_USES = 2


def course_kind(recipe: dict[str, Any]) -> str:
    """Тип блюда: main / side / salad / dessert / soup / breakfast / drink.

    Смотрим сначала tags/courses/categories, а имя — только как fallback.
    Описание не используем: в нём часто пишут «подавать с салатом», и это
    ломало бы классификацию.
    """
    course_values: list[str] = []
    for key in ("tags", "courses", "categories", "collections", "category"):
        value = recipe.get(key)
        items = value if isinstance(value, list) else [value]
        for item in items:
            text = _norm(item)
            if text:
                course_values.append(text)
    course_text = " ".join(course_values)
    name_text = _norm(recipe.get("name"))

    if "завтрак" in course_text:
        return "breakfast"
    if any(word in course_text for word in _SIDE):
        return "side"
    if any(word in course_text for word in _SALAD):
        return "salad"
    if any(word in course_text for word in _DESSERT):
        return "dessert"
    if any(word in course_text for word in _SOUP):
        return "soup"
    if any(word in course_text for word in _DRINK):
        return "drink"
    if any(word in course_text for word in _MAIN_COURSE):
        return "main"

    if any(word in name_text for word in _BREAKFAST):
        return "breakfast"
    if any(word in name_text for word in _SIDE):
        return "side"
    if any(word in name_text for word in _SALAD):
        return "salad"
    if any(word in name_text for word in _DESSERT):
        return "dessert"
    if any(word in name_text for word in _SOUP):
        return "soup"
    if any(word in name_text for word in _DRINK):
        return "drink"
    if any(word in name_text for word in _MAIN_KEYWORDS):
        return "main"
    return "other"


def classify_recipe(recipe: dict[str, Any]) -> set[str]:
    """Определяет приёмы пищи по типу блюда и явным тегам.

    Салаты и гарниры не считаются полноценным обедом/ужином: на ужин
    не должно попадать «только рис» или «только салат». Их место — полдник.
    Пользователь всегда может заменить блюдо в предпросмотре.
    """
    kind = course_kind(recipe)
    course_values = [
        _norm(item)
        for key in ("tags", "courses", "categories", "collections", "category")
        for item in (
            recipe.get(key) if isinstance(recipe.get(key), list) else [recipe.get(key)]
        )
        if _norm(item)
    ]
    course_text = " ".join(course_values)

    explicit: set[str] = set()
    if "завтрак" in course_text:
        explicit.add("breakfast")
    if "обед" in course_text:
        explicit.add("lunch")
    if "полдник" in course_text or "перекус" in course_text:
        explicit.add("snack")
    if "ужин" in course_text:
        explicit.add("dinner")

    out: set[str] = set()
    if kind == "breakfast" or "breakfast" in explicit:
        out.add("breakfast")
    elif kind in ("main", "soup", "other"):
        out.update({"lunch", "dinner"})
    elif kind == "salad":
        # Салат — самостоятельный перекус, но не полноценный обед/ужин.
        out.add("snack")
    elif kind in ("dessert", "drink"):
        out.add("snack")
        if "breakfast" in explicit:
            out.add("breakfast")
    elif kind == "side":
        # Отдельный гарнир не должен занимать слот обеда или ужина.
        out.clear()

    if not out and kind != "side":
        out.update({"lunch", "dinner"})
    return out


def effective_recipes(user_id: str | None) -> list[dict[str, Any]]:
    """Рецепты, которые пользователь реально видит в списке.

    Учитывает личные версии, скрытые, sub-рецепты аэрогриля и чужие клоны.
    """
    all_recipes = recipe_store.get_all()
    adapted_children: set[str] = set()
    personal_by_base: dict[str, dict[str, Any]] = {}

    for recipe in all_recipes:
        for child_id in (recipe.get("adapted_versions") or {}).values():
            if child_id:
                adapted_children.add(str(child_id))
        if (
            recipe.get("personal_of")
            and user_id
            and recipe.get("owner_id") == user_id
        ):
            personal_by_base[str(recipe["personal_of"])] = recipe

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for recipe in all_recipes:
        rid = str(recipe.get("id"))
        if recipe.get("personal_of"):
            continue
        if rid in adapted_children:
            continue
        clone = personal_by_base.get(rid)
        chosen = clone if clone and clone.get("personal_selected") is not False else recipe
        if user_id and user_id in (recipe.get("hidden_by") or []):
            continue
        if clone and user_id and user_id in (clone.get("hidden_by") or []):
            continue
        out.append(chosen)
        seen.add(rid)

    # Личная версия, у которой база удалена/недоступна.
    for base_id, clone in personal_by_base.items():
        if base_id in seen:
            continue
        if user_id and user_id in (clone.get("hidden_by") or []):
            continue
        out.append(clone)

    return out


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ingredient_names(recipe: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for ing in recipe.get("ingredients") or []:
        if isinstance(ing, str):
            names.append(_norm(ing))
        elif isinstance(ing, dict):
            names.append(_norm(ing.get("name")))
    return [name for name in names if name]


def _self_contained_text(recipe: dict[str, Any]) -> str:
    parts = [_norm(recipe.get("name"))]
    parts.extend(_ingredient_names(recipe))
    return " ".join(part for part in parts if part)


def is_self_contained(recipe: dict[str, Any]) -> bool:
    """Есть ли у блюда уже гарнир/овощи в составе.

    Явные теги важнее эвристики. Без тегов смотрим название и ингредиенты.
    """
    tags = {_norm(tag) for tag in (recipe.get("tags") or [])}
    if SELF_CONTAINED_TAG in tags:
        return True
    if NEEDS_SIDE_TAG in tags:
        return False
    text = _self_contained_text(recipe)
    return any(word in text for word in _SELF_CONTAINED_KEYWORDS)


def _side_candidates(
    recipes: list[dict[str, Any]],
    profile: dict[str, Any] | None,
) -> list[tuple[float, dict[str, Any]]]:
    pool: list[tuple[float, dict[str, Any]]] = []
    for recipe in recipes:
        if course_kind(recipe) not in ("side", "salad"):
            continue
        ok, score = profile_fit(recipe, profile)
        if not ok:
            continue
        pool.append((score, recipe))
    random.shuffle(pool)
    pool.sort(key=lambda item: item[0], reverse=True)
    return pool


def _pick_side(
    pool: list[tuple[float, dict[str, Any]]],
    usage: dict[str, int],
    main_id: str | None,
) -> dict[str, Any] | None:
    best: tuple[int, float, dict[str, Any]] | None = None
    for score, recipe in pool:
        rid = str(recipe.get("id"))
        if rid == main_id:
            continue
        used = usage.get(rid, 0)
        if used >= MAX_SIDE_USES:
            continue
        candidate = (used, -score, recipe)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        return None
    recipe = best[2]
    usage[str(recipe.get("id"))] = usage.get(str(recipe.get("id")), 0) + 1
    return recipe


def _total_time(recipe: dict[str, Any]) -> float | None:
    value = _num(recipe.get("total_time"))
    if value is None:
        value = _num(recipe.get("time"))
    if value is None:
        prep = _num(recipe.get("prep_time")) or 0
        cook = _num(recipe.get("cook_time")) or 0
        if prep or cook:
            value = prep + cook
    return value


def profile_fit(recipe: dict[str, Any], profile: dict[str, Any] | None) -> tuple[bool, float]:
    """Мягкая проверка профиля.

    Жёстко отбрасываем только явные нарушения. Неизвестные значения
    (например, active_time) не выбрасывают рецепт, а лишь снижают score:
    в базе active_time размечен далеко не у всех.
    """
    if not profile:
        return True, 0.0
    c = profile.get("constraints") or {}
    score = 0.0

    max_cal = _num(c.get("max_calories_per_serving"))
    if max_cal is not None:
        cal = _num((recipe.get("nutrition") or {}).get("calories"))
        if cal is None:
            score -= 0.5
        elif cal > max_cal:
            return False, 0.0
        else:
            score += 1.0

    max_total = _num(c.get("max_total_time_min"))
    if max_total is not None:
        total = _total_time(recipe)
        if total is None:
            score -= 0.25
        elif total > max_total:
            return False, 0.0
        else:
            score += 1.0

    max_active = _num(c.get("max_active_time_min"))
    if max_active is not None:
        active = _num(recipe.get("active_time"))
        if active is None:
            score -= 0.25
        elif active > max_active:
            return False, 0.0
        else:
            score += 1.0

    min_protein = _num(c.get("min_protein_per_serving_g"))
    if min_protein is not None:
        protein = _num((recipe.get("nutrition") or {}).get("protein"))
        if protein is None:
            score -= 0.25
        elif protein < min_protein:
            return False, 0.0
        else:
            score += 1.0

    max_sugar = _num(c.get("max_sugar_per_serving_g"))
    if max_sugar is not None:
        sugar = _num((recipe.get("nutrition") or {}).get("sugar"))
        if sugar is not None and sugar > max_sugar:
            return False, 0.0
        if sugar is not None:
            score += 0.5

    text = " ".join(_values(recipe))
    ingredients = " ".join(_ingredient_names(recipe))
    for item in c.get("avoid_ingredients") or []:
        needle = _norm(item)
        if needle and (needle in text or needle in ingredients):
            return False, 0.0
    for item in c.get("prefer_ingredients") or []:
        needle = _norm(item)
        if needle and (needle in text or needle in ingredients):
            score += 1.0
    for item in c.get("avoid_methods") or []:
        needle = _norm(item)
        if needle and needle in text:
            return False, 0.0
    for item in c.get("prefer_methods") or []:
        needle = _norm(item)
        if needle and needle in text:
            score += 1.0

    return True, score


def _samples_for_meal(
    recipes: list[dict[str, Any]],
    meal: str,
    limit: int = 2,
) -> list[dict[str, Any]]:
    pool = [r for r in recipes if meal in classify_recipe(r)]
    if not pool:
        pool = list(recipes)
    random.shuffle(pool)
    return pool[:limit]


def _build_candidates(
    recipes: list[dict[str, Any]],
    meal: str,
    profile: dict[str, Any] | None,
) -> list[tuple[float, dict[str, Any]]]:
    pool: list[tuple[float, dict[str, Any]]] = []
    for recipe in recipes:
        if meal not in classify_recipe(recipe):
            continue
        ok, score = profile_fit(recipe, profile)
        if not ok:
            continue
        if recipe.get("is_favourite") or recipe.get("favorite"):
            score += 0.75
        pool.append((score, recipe))
    random.shuffle(pool)
    pool.sort(key=lambda item: item[0], reverse=True)
    return pool


def _recipe_summary(recipe: dict[str, Any] | None) -> dict[str, Any] | None:
    if not recipe:
        return None
    return {
        "id": recipe.get("id"),
        "name": recipe.get("name"),
        "image_url": recipe.get("image_url"),
        "nutrition": recipe.get("nutrition"),
        "servings": recipe.get("servings"),
        "total_time": _total_time(recipe),
        "active_time": recipe.get("active_time"),
    }


def _slot(
    *,
    day: str,
    meal: str,
    source: str,
    recipe: dict[str, Any] | None = None,
    side_recipe: dict[str, Any] | None = None,
    needs_side: bool = False,
    suggestion_id: str | None = None,
    servings: float = 1,
    locked: bool = False,
) -> dict[str, Any]:
    return {
        "date": day,
        "meal_type": meal,
        "source": source,
        "locked": locked,
        "recipe_id": (recipe or {}).get("id") or None,
        "recipe": _recipe_summary(recipe),
        "side_recipe_id": (side_recipe or {}).get("id") or None,
        "side_recipe": _recipe_summary(side_recipe),
        "needs_side": bool(needs_side),
        "suggestion_id": suggestion_id,
        "approved": bool(recipe),
        "servings": servings,
    }


def build_base_slots(
    *,
    recipes: list[dict[str, Any]],
    profile: dict[str, Any] | None,
    week_start: str,
    meals: list[str],
    servings: float,
    existing_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    start = date.fromisoformat(week_start)
    days = [(start + timedelta(days=i)).isoformat() for i in range(7)]

    existing: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in existing_entries:
        key = (str(entry.get("date")), str(entry.get("meal_type")))
        existing.setdefault(key, []).append(entry)

    by_meal: dict[str, list[tuple[float, dict[str, Any]]]] = {
        meal: _build_candidates(recipes, meal, profile) for meal in meals
    }
    side_pool = _side_candidates(recipes, profile)
    used: set[str] = set()
    side_usage: dict[str, int] = {}
    for entries in existing.values():
        for entry in entries:
            rid = entry.get("recipe_id")
            if not rid:
                continue
            used.add(str(rid))
            recipe = recipe_store.get(str(rid))
            if recipe and course_kind(recipe) in ("side", "salad"):
                side_usage[str(rid)] = side_usage.get(str(rid), 0) + 1

    def wants_side(recipe: dict[str, Any] | None, meal: str) -> bool:
        return bool(
            recipe
            and meal in ("lunch", "dinner")
            and course_kind(recipe) in ("main", "other")
            and not is_self_contained(recipe)
        )

    slots: list[dict[str, Any]] = []
    for day in days:
        for meal in meals:
            entries = existing.get((day, meal)) or []
            if entries:
                entry = entries[0]
                recipe = recipe_store.get(str(entry.get("recipe_id") or ""))
                side_recipe = None
                for extra in entries[1:]:
                    extra_recipe = recipe_store.get(str(extra.get("recipe_id") or ""))
                    if extra_recipe and course_kind(extra_recipe) in ("side", "salad"):
                        side_recipe = extra_recipe
                        break
                slot = _slot(
                    day=day,
                    meal=meal,
                    source="existing",
                    recipe=recipe,
                    side_recipe=side_recipe,
                    needs_side=wants_side(recipe, meal) and not side_recipe,
                    servings=float(entry.get("servings") or servings),
                    locked=True,
                )
                slot["entry_id"] = entry.get("id")
                slot["existing_count"] = len(entries)
                slots.append(slot)
                continue

            picked = None
            for _score, candidate in by_meal.get(meal, []):
                rid = str(candidate.get("id"))
                if rid in used:
                    continue
                picked = candidate
                break
            if picked is not None:
                used.add(str(picked.get("id")))
                needs_side = wants_side(picked, meal)
                side_recipe = (
                    _pick_side(side_pool, side_usage, str(picked.get("id")))
                    if needs_side
                    else None
                )
                slots.append(_slot(
                    day=day, meal=meal, source="base",
                    recipe=picked, side_recipe=side_recipe,
                    needs_side=needs_side and not side_recipe,
                    servings=servings,
                ))
            else:
                slots.append(_slot(
                    day=day, meal=meal, source="empty", servings=servings,
                ))
    return slots


def build_meal_prompt(
    *,
    profile: dict[str, Any] | None,
    meal: str,
    count: int,
    servings: float,
    user_prompt: str | None,
    avoid_titles: list[str],
    samples: list[dict[str, Any]],
) -> tuple[str, str]:
    label = MEAL_LABELS.get(meal, meal)
    system = (
        "Ты — опытный повар и диетолог, составляющий меню для домашней кухни. "
        f"Сейчас нужны только рецепты для приёма пищи «{label}». "
        "Формат ответа: Markdown с YAML front matter. "
        "СТРОГОЕ ПРАВИЛО: ответ должен начинаться сразу с ---. "
        "В ингредиентах используй ключ name:, а не item:. "
        "Обязательно указывай courses: и tags: с названием приёма пищи. "
        "Пиши на русском языке. Не выдумывай бренды. "
        "Не добавляй рецепты для других приёмов пищи."
    )

    c = (profile or {}).get("constraints") or {}
    lines: list[str] = []
    if profile:
        lines.append(f"Профиль: {profile.get('name', '—')} — {profile.get('description') or ''}".rstrip(" —"))
        lines.append("Ограничения профиля:")
        lines.append(f"- Максимум калорий на порцию: {_fmt_num(c.get('max_calories_per_serving'), 'ккал')}")
        lines.append(f"- Максимум активного времени: {_fmt_num(c.get('max_active_time_min'), 'мин')}")
        lines.append(f"- Максимум общего времени: {_fmt_num(c.get('max_total_time_min'), 'мин')}")
        lines.append(f"- Избегать способов готовки: {_fmt_list(c.get('avoid_methods'))}")
        lines.append(f"- Предпочитать способы готовки: {_fmt_list(c.get('prefer_methods'))}")
        lines.append(f"- Избегать ингредиентов: {_fmt_list(c.get('avoid_ingredients'))}")
        lines.append(f"- Предпочитать ингредиенты: {_fmt_list(c.get('prefer_ingredients'))}")
        lines.append(f"- Минимум белка на порцию: {_fmt_num(c.get('min_protein_per_serving_g'), 'г')}")
        lines.append("")
    else:
        lines.append("Профиль не задан — готовь без специальных ограничений.")
        lines.append("")

    meal_hint = {
        "breakfast": "Это завтрак: каши, омлеты, сырники, тосты, творог, выпечка к чаю.",
        "lunch": "Это обед: полноценное основное блюдо или сытный суп.",
        "snack": "Это полдник: лёгкий перекус, салат, десерт, фрукты или йогурт.",
        "dinner": "Это ужин: полноценное горячее основное блюдо.",
    }.get(meal, "")
    lines.append(f"Приём пищи: {label}. Сгенерируй ровно {count} рецепт(ов).")
    if meal_hint:
        lines.append(meal_hint)
    if meal in ("lunch", "dinner"):
        lines.append(
            "Не предлагай отдельный гарнир или салат как единственное блюдо "
            "на обед/ужин. Нужно самостоятельное основное блюдо: гарнир "
            "(крупа, картофель, паста или овощи) уже должен входить в состав."
        )
    lines.append(f"Каждый рецепт должен быть на {servings:g} порций.")
    lines.append(f"В YAML укажи courses: [{label}] и tags: [{label}].")
    if user_prompt:
        lines.append(f"Пожелания пользователя: {user_prompt.strip()}")
    if avoid_titles:
        lines.append("")
        lines.append("Не повторяй эти блюда:")
        for title in avoid_titles[:80]:
            lines.append(f"- {title}")

    if samples:
        lines.append("")
        lines.append("Примеры стиля (не копируй, только структура):")
        for sample in samples:
            lines.append("---")
            lines.append(_recipe_to_md(sample))

    lines.append("")
    lines.append("Верни только Markdown-рецепты.")
    if count > 1:
        lines.append("Между рецептами разделитель: строка `---SPLIT---`.")
    lines.append("Без ``` вокруг. Без пояснений до или после.")
    return system, "\n".join(lines)


async def generate_batch(
    *,
    profile: dict[str, Any] | None,
    meal: str,
    count: int,
    servings: float,
    user_prompt: str | None,
    avoid_titles: list[str],
    samples: list[dict[str, Any]],
    user_id: str,
    job_id: str,
) -> tuple[list[dict[str, Any]], str]:
    system, user = build_meal_prompt(
        profile=profile,
        meal=meal,
        count=count,
        servings=servings,
        user_prompt=user_prompt,
        avoid_titles=avoid_titles,
        samples=samples,
    )
    raw, provider = await call_llm_cascade(
        user_id=user_id,
        prompt=user,
        system=system,
        max_tokens=int(settings_store.get("generator_max_tokens", GENERATOR_MAX_TOKENS)),
        temperature=0.7,
        job_id=job_id,
    )
    raw = _clean_md(raw)
    if not raw:
        raise HTTPException(502, "LLM вернул пустой ответ")

    if count > 1 and _SPLIT_RE.search(raw):
        parts = _SPLIT_RE.split(raw)
    else:
        parts = [raw]
    parts = [part.strip() for part in parts if part.strip()]

    results: list[dict[str, Any]] = []
    for markdown in parts:
        if len(results) >= count:
            break
        recipe_data = None
        error = None
        try:
            recipe_data = parse_markdown_recipe(markdown)
            if not recipe_data.get("ingredients"):
                error = "parse_failed: нет ингредиентов"
            elif not recipe_data.get("instructions"):
                error = "parse_failed: нет шагов"
        except Exception as exc:  # noqa: BLE001
            error = f"parse_failed: {exc}"
        results.append({
            "markdown": markdown,
            "recipe_data": recipe_data,
            "error": error,
        })
    return results, provider


def _suggestion_item(
    *,
    result: dict[str, Any],
    provider: str,
    user_id: str,
    draft_id: str,
    slot: dict[str, Any],
    profile: dict[str, Any] | None,
    user_prompt: str | None,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "status": "pending",
        "origin": "meal_plan",
        "owner_id": user_id,
        "draft_id": draft_id,
        "slot_date": slot.get("date"),
        "slot_meal": slot.get("meal_type"),
        "created_at": _now(),
        "profile_id": (profile or {}).get("id"),
        "profile_name": (profile or {}).get("name"),
        "topic": user_prompt,
        "provider": provider,
        "model": provider,
        "markdown": result.get("markdown"),
        "recipe_data": result.get("recipe_data"),
        "error": result.get("error"),
    }


def _empty_by_meal(slots: list[dict[str, Any]], meals: list[str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {meal: [] for meal in meals}
    for slot in slots:
        if slot.get("source") == "empty":
            out.setdefault(slot.get("meal_type"), []).append(slot)
    return out


def _avoid_titles(
    recipes: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    suggestions: list[dict[str, Any]],
) -> list[str]:
    titles: list[str] = []
    for recipe in recipes:
        name = (recipe.get("name") or "").strip()
        if name:
            titles.append(name)
    for slot in slots:
        name = ((slot.get("recipe") or {}).get("name") or "").strip()
        if name:
            titles.append(name)
    for suggestion in suggestions:
        name = ((suggestion.get("recipe_data") or {}).get("name") or "").strip()
        if name:
            titles.append(name)
    return list(dict.fromkeys(titles))


async def run_plan_generation(
    *,
    draft_id: str,
    job_id: str,
    user_id: str,
    profile: dict[str, Any] | None,
    week_start: str,
    meals: list[str],
    servings: float,
    user_prompt: str | None,
    max_new: int,
) -> int:
    """Собирает план, генерирует недостающее. Возвращает число suggestions."""
    draft = meal_plan_drafts_store.get(draft_id)
    if not draft:
        raise RuntimeError("draft not found")

    recipes = effective_recipes(user_id)
    start = date.fromisoformat(week_start)
    end = (start + timedelta(days=6)).isoformat()
    existing_entries = []
    for entry in meal_plan_store.get_range(week_start, end):
        recipe = recipe_store.get(str(entry.get("recipe_id") or ""))
        if recipe and recipe.get("personal_of") and recipe.get("owner_id") != user_id:
            continue
        existing_entries.append(entry)

    slots = build_base_slots(
        recipes=recipes,
        profile=profile,
        week_start=week_start,
        meals=meals,
        servings=servings,
        existing_entries=existing_entries,
    )
    warnings: list[str] = []

    empty_initial = _empty_by_meal(slots, meals)
    total_needed = sum(len(items) for items in empty_initial.values())
    await meal_plan_drafts_store.update(draft_id, {
        "slots": slots,
        "status": "generating",
        "progress": {
            "stage": "Подбираем рецепты из базы",
            "done": 0,
            "total": max(1, total_needed),
        },
        "warnings": warnings,
        "generated_count": 0,
    })
    await jobs_store.update(
        job_id,
        progress={"stage": "Подбираем рецепты из базы", "done": 0, "total": 1},
    )

    empty = empty_initial
    cap = max(0, int(max_new))
    generated = 0
    avoid_titles = _avoid_titles(recipes, slots, [])
    processed_meals = 0

    for meal in meals:
        meal_slots = [s for s in empty.get(meal, []) if s.get("source") == "empty"]
        if generated >= cap:
            break
        need = min(len(meal_slots), cap - generated)
        index = 0
        while need > 0:
            batch_n = min(BATCH_SIZE, need)
            await jobs_store.update(
                job_id,
                progress={
                    "stage": f"Генерируем: {MEAL_LABELS.get(meal, meal)}",
                    "done": processed_meals,
                    "total": max(1, len(meals)),
                    "generated": generated,
                },
            )
            try:
                results, provider = await generate_batch(
                    profile=profile,
                    meal=meal,
                    count=batch_n,
                    servings=servings,
                    user_prompt=user_prompt,
                    avoid_titles=avoid_titles,
                    samples=_samples_for_meal(recipes, meal),
                    user_id=user_id,
                    job_id=job_id,
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(
                    f"{MEAL_LABELS.get(meal, meal)}: {type(exc).__name__}: {exc}"
                )
                break
            if not results:
                warnings.append(f"{MEAL_LABELS.get(meal, meal)}: LLM не вернул рецепты")
                break

            for result in results:
                if index >= len(meal_slots) or generated >= cap:
                    break
                slot = meal_slots[index]
                suggestion = _suggestion_item(
                    result=result,
                    provider=provider,
                    user_id=user_id,
                    draft_id=draft_id,
                    slot=slot,
                    profile=profile,
                    user_prompt=user_prompt,
                )
                await suggestions_store.add_many([suggestion])
                slot["suggestion_id"] = suggestion["id"]
                slot["source"] = "generated"
                slot["approved"] = False
                slot["recipe"] = None
                slot["recipe_id"] = None
                name = (result.get("recipe_data") or {}).get("name")
                if name:
                    avoid_titles.append(name)
                index += 1
                generated += 1

            need = min(len(meal_slots) - index, cap - generated)
            await meal_plan_drafts_store.update(draft_id, {
                "slots": slots,
                "warnings": warnings,
                "generated_count": generated,
                "progress": {
                    "stage": f"Сгенерировано {generated} из {min(total_needed, cap)}",
                    "done": generated,
                    "total": max(1, min(total_needed, cap)),
                },
            })
        processed_meals += 1

    await meal_plan_drafts_store.update(draft_id, {
        "slots": slots,
        "status": "ready",
        "warnings": warnings,
        "generated_count": generated,
        "progress": {
            "stage": "Готово",
            "done": generated,
            "total": max(1, min(total_needed, cap)),
        },
    })
    await jobs_store.update(
        job_id,
        progress={
            "stage": "Готово",
            "done": generated,
            "total": max(1, min(total_needed, cap)),
        },
    )
    return generated


async def run_replacement(
    *,
    draft_id: str,
    job_id: str,
    user_id: str,
    profile: dict[str, Any] | None,
    slot_date: str,
    slot_meal: str,
    servings: float,
    user_prompt: str | None,
) -> int:
    draft = meal_plan_drafts_store.get(draft_id)
    if not draft:
        raise RuntimeError("draft not found")

    slots = draft.get("slots") or []
    slot = next(
        (s for s in slots if s.get("date") == slot_date and s.get("meal_type") == slot_meal),
        None,
    )
    if not slot:
        raise RuntimeError("slot not found")

    recipes = effective_recipes(user_id)
    existing_titles = [
        ((s.get("recipe") or {}).get("name") or "") for s in slots
    ]
    avoid_titles = _avoid_titles(recipes, slots, [])
    for name in existing_titles:
        if name and name not in avoid_titles:
            avoid_titles.append(name)

    await jobs_store.update(
        job_id,
        progress={"stage": f"Генерируем замену: {MEAL_LABELS.get(slot_meal, slot_meal)}", "done": 0, "total": 1},
    )
    results, provider = await generate_batch(
        profile=profile,
        meal=slot_meal,
        count=1,
        servings=servings,
        user_prompt=user_prompt,
        avoid_titles=avoid_titles,
        samples=_samples_for_meal(recipes, slot_meal),
        user_id=user_id,
        job_id=job_id,
    )
    if not results:
        raise RuntimeError("LLM не вернул рецепт")

    suggestion = _suggestion_item(
        result=results[0],
        provider=provider,
        user_id=user_id,
        draft_id=draft_id,
        slot=slot,
        profile=profile,
        user_prompt=user_prompt,
    )
    await suggestions_store.add_many([suggestion])
    slot["suggestion_id"] = suggestion["id"]
    slot["source"] = "generated"
    slot["approved"] = False
    slot["recipe"] = None
    slot["recipe_id"] = None

    await meal_plan_drafts_store.update(draft_id, {
        "slots": slots,
        "status": "ready",
        "generated_count": int(draft.get("generated_count") or 0) + 1,
        "progress": {"stage": "Готово", "done": 1, "total": 1},
    })
    await jobs_store.update(
        job_id,
        progress={"stage": "Готово", "done": 1, "total": 1},
    )
    return 1
