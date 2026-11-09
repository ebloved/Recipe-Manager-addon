"""Журнал действий пользователей, администраторов и автоматизаций.

Пишет только изменения и фоновые операции. Просмотры рецептов, meal plan
и список покупок не логируются — это личные действия.
"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import delete, func, select

from db import SessionLocal
from stores.db_models import AuditEvent

_MAX_ERROR = 2000
_MAX_DETAILS_CHARS = 4000
_MAX_BODY = 65536

_SENSITIVE = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|cookie|credential|private)",
    re.I,
)
_TEXT_KEYS = {
    "markdown_content", "content", "text", "instructions",
    "recipe_md", "html", "body", "prompt", "system",
}
_EXCLUDE_PREFIXES = (
    "/api/meal-plan",
    "/api/shopping",
    "/api/products",
    "/api/cooking",
    "/api/me/activity",
    "/api/embeddings",
    "/api/auth/",
    "/api/admin/audit",
    "/api/v1/shopping",
)
_EXCLUDE_EXACT = {
    "/api/health",
    "/api/v1/auth/device/poll",
    "/api/remote/pair/poll",
    "/api/voice/tts",
    "/api/voice/live-token",
}
_EXCLUDE_CART = re.compile(r"^/api/stores/[^/]+/cart$")

Rule = tuple[str, re.Pattern[str], str, str, str | None, int | None]


def _r(
    method: str,
    pattern: str,
    action: str,
    label: str,
    target_type: str | None = None,
    group: int | None = None,
) -> Rule:
    return (method, re.compile(pattern), action, label, target_type, group)


_RULES: tuple[Rule, ...] = (
    # --- Рецепты -----------------------------------------------------
    _r("POST", r"^/api/recipes$", "recipe.create", "Создание рецепта", "recipe"),
    _r("PATCH", r"^/api/recipes/([^/]+)$", "recipe.update", "Редактирование рецепта", "recipe", 1),
    _r("DELETE", r"^/api/recipes/([^/]+)$", "recipe.delete", "Удаление рецепта", "recipe", 1),
    _r("POST", r"^/api/recipes/([^/]+)/restore$", "recipe.restore", "Восстановление рецепта", "recipe", 1),
    _r("DELETE", r"^/api/recipes/([^/]+)/permanent$", "recipe.delete_permanent", "Окончательное удаление рецепта", "recipe", 1),
    _r("POST", r"^/api/recipes/([^/]+)/hide$", "recipe.hide", "Скрытие рецепта", "recipe", 1),
    _r("POST", r"^/api/recipes/([^/]+)/unhide$", "recipe.unhide", "Возврат рецепта", "recipe", 1),
    _r("POST", r"^/api/recipes/([^/]+)/fork$", "recipe.fork", "Копирование рецепта", "recipe", 1),
    _r("POST", r"^/api/recipes/([^/]+)/clone-personal$", "recipe.clone_personal", "Клонирование рецепта для себя", "recipe", 1),
    _r("POST", r"^/api/recipes/([^/]+)/personal-select$", "recipe.personal_select", "Переключение версии рецепта", "recipe", 1),
    _r("PUT", r"^/api/recipes/([^/]+)/import-md$", "recipe.import_md", "Импорт Markdown в рецепт", "recipe", 1),
    _r("POST", r"^/api/recipes/-/from-markdown$", "recipe.from_markdown", "Создание рецепта из Markdown", "recipe"),
    _r("POST", r"^/api/recipes/([^/]+)/estimate-active-time$", "recipe.estimate_active_time", "Оценка активного времени", "recipe", 1),
    _r("POST", r"^/api/recipes/estimate-active-time$", "recipe.estimate_active_time_all", "Оценка активного времени (все рецепты)"),
    _r("POST", r"^/api/recipes/([^/]+)/adapt-to-airfryer$", "recipe.airfryer", "Пересчёт под аэрогриль", "recipe", 1),
    _r("POST", r"^/api/recipes/-/find-by-ingredients$", "recipe.find_by_ingredients", "Поиск рецептов по ингредиентам"),
    _r("POST", r"^/api/recipes/([^/]+)/step-audio/(\d+)$", "recipe.step_audio", "Генерация озвучки шага", "recipe", 1),
    # --- Импорт / YouTube -------------------------------------------
    _r("POST", r"^/api/voice/recipe-parse$", "recipe.voice_parse", "Разбор рецепта голосом"),
    _r("POST", r"^/api/recipes/import-url$", "recipe.import_url", "Импорт рецепта по URL"),
    _r("POST", r"^/api/recipes/import-text$", "recipe.import_text", "Импорт рецепта из текста"),
    _r("POST", r"^/api/recipes/import-batch$", "recipe.import_batch", "Массовый импорт рецептов"),
    _r("POST", r"^/api/scrape$", "recipe.scrape", "Скрапинг рецепта"),
    _r("POST", r"^/api/youtube/generate-recipe$", "recipe.youtube", "Генерация рецепта из YouTube"),
    _r("POST", r"^/api/youtube/download$", "youtube.download", "Скачивание YouTube"),
    _r("DELETE", r"^/api/youtube/cache/([^/]+)$", "youtube.cache_clear", "Очистка кэша YouTube", "youtube", 1),
    # --- Генератор ---------------------------------------------------
    _r("POST", r"^/api/generator/run$", "recipe.generate", "Генерация рецептов"),
    _r("POST", r"^/api/generator/suggestions/([^/]+)/accept$", "suggestion.accept", "Принятие сгенерированного рецепта", "suggestion", 1),
    _r("DELETE", r"^/api/generator/suggestions/([^/]+)$", "suggestion.delete", "Удаление сгенерированного рецепта", "suggestion", 1),
    # --- Меню на неделю ---------------------------------------------
    _r("POST", r"^/api/meal-plan/generate$", "meal_plan.generate", "Генерация меню на неделю", "meal_plan"),
    _r("POST", r"^/api/meal-plan/drafts/([^/]+)/approve$", "meal_plan.approve", "Одобрение рецепта в меню", "meal_plan", 1),
    _r("POST", r"^/api/meal-plan/drafts/([^/]+)/reject$", "meal_plan.reject", "Отклонение рецепта в меню", "meal_plan", 1),
    _r("POST", r"^/api/meal-plan/drafts/([^/]+)/replace$", "meal_plan.replace", "Генерация замены в меню", "meal_plan", 1),
    _r("POST", r"^/api/meal-plan/drafts/([^/]+)/save$", "meal_plan.save", "Сохранение меню на неделю", "meal_plan", 1),
    _r("DELETE", r"^/api/meal-plan/drafts/([^/]+)$", "meal_plan.discard", "Отмена меню на неделю", "meal_plan", 1),
    # --- Админ / настройки ------------------------------------------
    _r("POST", r"^/api/settings$", "settings.update", "Изменение системных настроек", "settings"),
    _r("POST", r"^/api/admin/users$", "admin.user_add", "Добавление пользователя", "user"),
    _r("DELETE", r"^/api/admin/users/(.+)$", "admin.user_delete", "Удаление пользователя", "user", 1),
    _r("POST", r"^/api/admin/piece_weights$", "admin.weight_set", "Изменение веса продукта", "product"),
    _r("DELETE", r"^/api/admin/piece_weights/(.+)$", "admin.weight_delete", "Удаление веса продукта", "product", 1),
    # --- Продукты / профили -----------------------------------------
    _r("POST", r"^/api/ingredients$", "ingredient.create", "Добавление продукта", "product"),
    _r("PATCH", r"^/api/ingredients/([^/]+)$", "ingredient.update", "Редактирование продукта", "product", 1),
    _r("DELETE", r"^/api/ingredients/([^/]+)$", "ingredient.delete", "Удаление продукта", "product", 1),
    _r("POST", r"^/api/ingredients/([^/]+)/restore$", "ingredient.restore", "Восстановление продукта", "product", 1),
    _r("POST", r"^/api/ingredients/([^/]+)/aliases$", "ingredient.alias_add", "Добавление синонима продукта", "product", 1),
    _r("DELETE", r"^/api/ingredients/([^/]+)/aliases$", "ingredient.alias_delete", "Удаление синонима продукта", "product", 1),
    _r("POST", r"^/api/ingredients/lookup$", "ingredient.lookup", "Поиск продукта"),
    _r("POST", r"^/api/ingredients/import-from-off$", "ingredient.import_off", "Импорт продуктов из OpenFoodFacts"),
    _r("POST", r"^/api/ingredients/([^/]+)/contribute$", "ingredient.contribute", "Отправка продукта в OpenFoodFacts", "product", 1),
    _r("DELETE", r"^/api/ingredients/cache$", "ingredient.cache_clear", "Очистка кэша продуктов"),
    _r("POST", r"^/api/profiles$", "profile.create", "Создание профиля", "profile"),
    _r("PATCH", r"^/api/profiles/([^/]+)$", "profile.update", "Редактирование профиля", "profile", 1),
    _r("DELETE", r"^/api/profiles/([^/]+)$", "profile.delete", "Удаление профиля", "profile", 1),
    _r("POST", r"^/api/profiles/([^/]+)/restore$", "profile.restore", "Восстановление профиля", "profile", 1),
    _r("POST", r"^/api/profiles/active$", "profile.activate", "Выбор активного профиля", "profile"),
    # --- Матчер ------------------------------------------------------
    _r("POST", r"^/api/matcher/match$", "matcher.match", "Сопоставление ингредиентов"),
    _r("POST", r"^/api/matcher/match-batch$", "matcher.match_batch", "Пакетное сопоставление ингредиентов"),
    _r("POST", r"^/api/matcher/validate$", "matcher.validate", "Проверка сопоставления"),
    _r("POST", r"^/api/matcher/confirm$", "matcher.confirm", "Подтверждение сопоставления"),
    _r("POST", r"^/api/matcher/apply-to-recipe$", "matcher.apply", "Применение сопоставления к рецепту"),
    _r("POST", r"^/api/matcher/provider-check$", "matcher.provider_check", "Проверка провайдера матчера"),
    _r("POST", r"^/api/matcher/queue/remove$", "matcher.queue_remove", "Удаление из очереди матчера"),
    _r("POST", r"^/api/matcher/queue/clear$", "matcher.queue_clear", "Очистка очереди матчера"),
    # --- Публикация / синхронизация ---------------------------------
    _r("POST", r"^/api/sharing/([^/]+)/share$", "share.create", "Публикация рецепта", "recipe", 1),
    _r("DELETE", r"^/api/sharing/([^/]+)/share$", "share.delete", "Снятие публикации", "recipe", 1),
    _r("POST", r"^/api/sharing/([^/]+)/fork$", "share.fork", "Копирование публичного рецепта"),
    _r("POST", r"^/api/sync/push$", "sync.push", "Отправка синхронизации"),
    _r("POST", r"^/api/sync/pull$", "sync.pull", "Получение синхронизации"),
    _r("POST", r"^/api/v1/recipes$", "sync.recipe_upsert", "Синхронизация рецепта", "recipe"),
    # --- Устройства / remote ----------------------------------------
    _r("POST", r"^/api/v1/auth/device/init$", "device.init", "Начало привязки устройства"),
    _r("POST", r"^/api/v1/auth/device/approve$", "device.approve", "Одобрение устройства"),
    _r("POST", r"^/api/remote/pair/init$", "remote.pair_init", "Начало привязки сервера"),
    _r("POST", r"^/api/remote/sync$", "remote.sync", "Синхронизация с сервером"),
    _r("POST", r"^/api/remote/disconnect$", "remote.disconnect", "Отключение от сервера"),
    # --- Пользователь -----------------------------------------------
    _r("POST", r"^/api/me/llm$", "user.llm_update", "Изменение LLM-настроек"),
    _r("POST", r"^/api/me/llm/validate$", "user.llm_validate", "Проверка LLM-ключа"),
    _r("POST", r"^/api/me/llm/validate/orcarouter$", "user.llm_validate", "Проверка OrcaRouter"),
    _r("POST", r"^/api/me/llm/validate/custom$", "user.llm_validate", "Проверка Custom LLM"),
    _r("POST", r"^/api/me/llm/custom/models$", "user.llm_models", "Загрузка моделей Custom LLM"),
    _r("POST", r"^/api/me/weights$", "user.weight", "Ответ на вопрос о весе"),
    # --- Медиа / магазины -------------------------------------------
    _r("POST", r"^/api/media/image$", "media.upload", "Загрузка изображения"),
    _r("POST", r"^/api/stores/([^/]+)/disconnect$", "store.disconnect", "Отключение магазина", "store", 1),
    _r("POST", r"^/api/stores/([^/]+)/test$", "store.test", "Проверка магазина", "store", 1),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _short(value: Any, limit: int = 500) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[:limit]


def _sanitize_url(value: Any) -> str:
    raw = str(value or "")
    try:
        parts = urlsplit(raw)
        query = parts.query
        if query and _SENSITIVE.search(query):
            query = "[redacted]"
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))[:500]
    except Exception:  # noqa: BLE001
        return raw[:500]


def safe_details(value: Any, depth: int = 0) -> Any:
    """Убирает секреты и тяжёлый контент из тела запроса."""
    if depth > 3:
        return "…"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:30]:
            key_str = str(key)
            if _SENSITIVE.search(key_str):
                out[key_str] = "[redacted]"
            elif key_str == "url":
                out[key_str] = _sanitize_url(item)
            elif key_str in _TEXT_KEYS and isinstance(item, str):
                out[key_str] = f"<{len(item)} chars>"
            elif isinstance(item, (dict, list)):
                out[key_str] = safe_details(item, depth + 1)
            elif isinstance(item, str):
                out[key_str] = item[:300]
            else:
                out[key_str] = item
        return out
    if isinstance(value, list):
        items = [safe_details(item, depth + 1) for item in value[:10]]
        if len(value) > 10:
            items.append("…")
        return items
    if isinstance(value, str):
        return value[:300]
    return value


def _search_blob(*values: Any) -> str:
    return " ".join(
        str(value) for value in values if value not in (None, "")
    ).lower()[:4000]


_HTTP_HUMAN = {
    400: "Некорректный запрос",
    401: "Требуется авторизация",
    403: "Доступ запрещён",
    404: "Не найдено",
    409: "Конфликт состояния",
    413: "Слишком большой запрос",
    422: "Ошибка валидации",
    429: "Слишком много запросов",
    500: "Внутренняя ошибка сервера",
    502: "Ошибка внешнего сервиса",
    503: "Сервис недоступен",
    504: "Таймаут внешнего сервиса",
}


def _uuid7() -> uuid.UUID:
    """UUIDv7 для Python < 3.14; на 3.14+ используем встроенный."""
    if hasattr(uuid, "uuid7"):
        return uuid.uuid7()
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0x2 << 62)
        | rand_b
    )
    return uuid.UUID(int=value)


def _new_event_id() -> str:
    """UUIDv7: сортируемый по времени, с случайной частью."""
    return str(_uuid7())


def error_code_for_status(code: int | None) -> str | None:
    if not code:
        return None
    if code == 429:
        return "http_429"
    if 400 <= code < 500:
        return f"http_{code}"
    if code >= 500:
        return "http_5xx"
    return None


def humanize_error(
    error: str | None,
    *,
    http_status: int | None = None,
    error_code: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """Превращает код/сырой текст в понятное человеку сообщение."""
    text = str(error or "").strip()

    if error_code == "tts_quota":
        parts = [
            "Gemini TTS: слишком много запросов (429). "
            "Лимит Gemini исчерпан или превышен."
        ]
        if model:
            parts.append(f"Модель: {model}.")
        if provider:
            parts.append(f"Провайдер: {provider}.")
        return " ".join(parts)

    if error_code == "tts_daily_limit":
        parts = ["Дневной лимит озвучки исчерпан."]
        if model:
            parts.append(f"Модель: {model}.")
        if text and "Дневной лимит" not in text:
            parts.append(text[:500])
        return " ".join(parts)

    if error_code == "tts_disabled":
        return "Озвучка отключена в админке."

    if error_code == "tts_not_generated":
        return "Аудио шага ещё не сгенерировано."

    if error_code == "step_not_found":
        return "Шаг рецепта не найден."

    if error_code == "tts_error":
        parts = ["Ошибка Gemini TTS."]
        if model:
            parts.append(f"Модель: {model}.")
        if text and not text.startswith("Gemini TTS"):
            parts.append(text[:1000])
        return " ".join(parts)

    if "TTSError" in text and "429" in text:
        parts = [
            "Gemini TTS: слишком много запросов (429). "
            "Лимит Gemini исчерпан или превышен."
        ]
        if model:
            parts.append(f"Модель: {model}.")
        return " ".join(parts)

    if error_code == "exception":
        return "Внутренняя ошибка сервера." + (f" {text[:1500]}" if text else "")

    if http_status in _HTTP_HUMAN:
        base = f"{_HTTP_HUMAN[http_status]} ({http_status})."
        if text and text not in (str(http_status), "429"):
            base += f" {text[:1500]}"
        return base

    if any(
        token in text.lower()
        for token in ("timeout", "timed out", "readtimeout", "connecttimeout")
    ):
        return "Внешний сервис не ответил вовремя (таймаут)." + (
            f" {text[:500]}" if text else ""
        )

    return text[:2000] if text else "Неизвестная ошибка"


def _limit_details(details: Any) -> Any:
    try:
        raw = json.dumps(details, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return {"error": "details are not serializable"}
    if len(raw) > _MAX_DETAILS_CHARS:
        return {"truncated": True, "preview": raw[:_MAX_DETAILS_CHARS]}
    return details


def _actor_dict(user: dict[str, Any] | None) -> dict[str, Any]:
    user = user or {}
    role = user.get("role")
    source = user.get("source")
    if source == "device":
        kind = "device"
    elif role == "admin":
        kind = "admin"
    elif not user.get("id"):
        kind = "anonymous"
    else:
        kind = "user"
    return {
        "kind": kind,
        "id": user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": role,
    }


def actor_from_request(request) -> dict[str, Any]:
    from services.auth import get_current_user

    return _actor_dict(get_current_user(request))


def resolve_actor(user_id: str | None) -> dict[str, Any]:
    """Актор для фоновой задачи по id пользователя."""
    if not user_id or user_id == "system":
        return {
            "kind": "automation",
            "id": user_id or "system",
            "name": "Автоматизация",
            "email": None,
            "role": "system",
        }
    from services.auth import users_store

    user = users_store.users.get(str(user_id))
    if user:
        return _actor_dict(user)
    return {
        "kind": "user",
        "id": str(user_id),
        "name": str(user_id),
        "email": None,
        "role": None,
    }


def _target_name(
    target_type: str | None, target_id: str | None, body: Any
) -> str | None:
    body = body if isinstance(body, dict) else {}
    if target_type == "recipe" and target_id:
        try:
            from stores import recipe_store

            recipe = recipe_store.get(str(target_id))
            if recipe:
                return _short(body.get("name") or recipe.get("name"), 500) or None
        except Exception:  # noqa: BLE001
            pass
    if target_type == "user" and target_id:
        try:
            from services.auth import users_store

            for user in users_store.users.values():
                if user.get("email") == target_id or user.get("id") == target_id:
                    return _short(user.get("name") or user.get("email"), 500) or None
        except Exception:  # noqa: BLE001
            pass
    if target_type == "product" and target_id:
        try:
            from stores import ingredients_store

            product = ingredients_store.get(str(target_id))
            if product:
                return _short(body.get("name") or product.get("name"), 500) or None
        except Exception:  # noqa: BLE001
            pass
    if target_type == "profile" and target_id:
        try:
            from stores import gen_profiles_store

            profile = gen_profiles_store.get(str(target_id))
            if profile:
                return _short(body.get("name") or profile.get("name"), 500) or None
        except Exception:  # noqa: BLE001
            pass
    if target_type == "suggestion" and target_id:
        try:
            from stores import suggestions_store

            suggestion = suggestions_store.get(str(target_id))
            if suggestion:
                return _short(
                    body.get("name") or suggestion.get("name"), 500
                ) or None
        except Exception:  # noqa: BLE001
            pass
    return _short(body.get("name") or body.get("title") or body.get("email"), 500) or None


def classify_request(
    method: str, path: str, body: Any
) -> dict[str, Any]:
    method = method.upper()
    for rule_method, pattern, action, label, target_type, group in _RULES:
        if rule_method != method:
            continue
        match = pattern.match(path)
        if not match:
            continue
        target_id = match.group(group) if group else None
        if action == "admin.user_add" and isinstance(body, dict):
            target_id = body.get("email") or target_id
        details = safe_details(body) if body else {}
        if isinstance(details, dict):
            if action in ("settings.update", "user.llm_update", "user.llm_validate") and isinstance(body, dict):
                details["changed"] = sorted(body.keys())
            if action == "recipe.step_audio":
                try:
                    details["step_index"] = int(match.group(2))
                except (ValueError, IndexError):
                    pass
        return {
            "action": action,
            "action_label": label,
            "target_type": target_type,
            "target_id": str(target_id) if target_id else None,
            "target_name": _target_name(target_type, target_id, body),
            "details": _limit_details(details),
        }
    # Всё, что не описано выше, всё равно фиксируем — лучше generic,
    # чем потерять действие.
    return {
        "action": "api.mutation",
        "action_label": f"{method} {path}",
        "target_type": None,
        "target_id": None,
        "target_name": None,
        "details": _limit_details(safe_details(body) if body else {}),
    }


def should_audit(request) -> bool:
    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    path = request.url.path
    if not path.startswith("/api/"):
        return False
    if path in _EXCLUDE_EXACT:
        return False
    # Генерация меню — важное действие, хотя обычный meal plan не логируем.
    if path.startswith("/api/meal-plan/generate") or path.startswith("/api/meal-plan/drafts"):
        return True
    for prefix in _EXCLUDE_PREFIXES:
        if path.startswith(prefix):
            return False
    if _EXCLUDE_CART.match(path):
        return False
    return True


async def _read_body(request) -> Any:
    try:
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type:
            return None
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) > _MAX_BODY:
                    return None
            except ValueError:
                pass
        raw = await request.body()
        if not raw or len(raw) > _MAX_BODY:
            return None
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


def _client_ip(request) -> str | None:
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get(
        "x-forwarded-for", ""
    )
    if forwarded:
        return forwarded.split(",")[0].strip()[:64] or None
    return request.client.host[:64] if request.client else None


async def start_request_event(request) -> str | None:
    """Создаёт событие до выполнения запроса. Возвращает id или None."""
    if not should_audit(request):
        return None
    try:
        path = request.url.path
        body = await _read_body(request)
        info = classify_request(request.method, path, body)
        actor = actor_from_request(request)
        event_id = _new_event_id()
        row = AuditEvent(
            id=event_id,
            created_at=_now(),
            actor_kind=actor["kind"],
            actor_id=actor["id"],
            actor_name=actor["name"],
            actor_email=actor["email"],
            actor_role=actor["role"],
            action=info["action"],
            action_label=info["action_label"],
            target_type=info["target_type"],
            target_id=info["target_id"],
            target_name=info["target_name"],
            method=request.method.upper(),
            path=path[:500],
            status="running",
            details=info["details"],
            search_text=_search_blob(
                event_id, event_id.replace("-", ""),
                info["action"], info["action_label"], actor["name"], actor["email"],
                actor["id"], info["target_type"], info["target_id"],
                info["target_name"], path,
            ),
            ip=_client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        )
        async with SessionLocal() as session:
            session.add(row)
            await session.commit()
        return event_id
    except Exception as exc:  # noqa: BLE001
        print(f"[audit] start failed: {type(exc).__name__}: {exc}")
        return None


async def finish_event(
    event_id: str | None,
    *,
    status: str,
    http_status: int | None = None,
    error: str | None = None,
    error_code: str | None = None,
    error_provider: str | None = None,
    error_model: str | None = None,
    details_extra: dict[str, Any] | None = None,
) -> None:
    if not event_id:
        return
    try:
        now = _now()
        raw_error = str(error) if error else None
        effective_code = error_code or error_code_for_status(http_status)
        human_error = (
            humanize_error(
                raw_error,
                http_status=http_status,
                error_code=effective_code,
                provider=error_provider,
                model=error_model,
            )
            if (raw_error or effective_code)
            else None
        )
        async with SessionLocal() as session:
            row = await session.get(AuditEvent, event_id)
            if row is None:
                return
            row.status = status
            row.http_status = http_status
            row.error = human_error[:_MAX_ERROR] if human_error else None
            row.error_code = effective_code
            row.error_provider = error_provider
            row.error_model = error_model
            row.finished_at = now
            created = row.created_at
            if created is not None:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                row.duration_ms = max(0, int((now - created).total_seconds() * 1000))
            merged = dict(row.details or {})
            if details_extra:
                merged.update(details_extra)
            if raw_error and human_error and raw_error != human_error:
                merged.setdefault("raw_error", raw_error[:1000])
            if merged:
                row.details = _limit_details(merged)
            model_names = []
            if isinstance(details_extra, dict):
                for attempt in details_extra.get("models_tried") or []:
                    if isinstance(attempt, dict) and attempt.get("model"):
                        model_names.append(str(attempt["model"]))
            row.search_text = _search_blob(
                row.search_text, effective_code, error_provider,
                error_model, human_error, raw_error, *model_names,
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[audit] finish failed: {type(exc).__name__}: {exc}")


def error_from_body(body: bytes | None) -> str | None:
    if not body:
        return None
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001
        try:
            return body.decode("utf-8", "replace")[:_MAX_ERROR]
        except Exception:  # noqa: BLE001
            return None
    if isinstance(data, dict):
        value = data.get("detail") or data.get("error") or data.get("message")
        if value:
            return str(value)[:_MAX_ERROR]
        return json.dumps(data, ensure_ascii=False)[:_MAX_ERROR]
    return str(data)[:_MAX_ERROR]


def _error_from_response(response) -> str | None:
    return error_from_body(getattr(response, "body", None))


def response_status(response) -> str:
    code = int(response.status_code)
    if code < 400:
        return "ok"
    if code in (401, 403):
        return "denied"
    return "error"


async def finish_from_response(
    event_id: str | None,
    response,
    *,
    audit_error: dict[str, Any] | None = None,
    details_extra: dict[str, Any] | None = None,
) -> None:
    if not event_id:
        return
    info = audit_error or {}
    code = int(response.status_code)
    status = response_status(response)
    error = _error_from_response(response) if code >= 400 else None
    extra = dict(details_extra or {})
    extra.update(info.get("details") or {})
    await finish_event(
        event_id,
        status=status,
        http_status=code,
        error=error,
        error_code=info.get("code") or error_code_for_status(code),
        error_provider=info.get("provider"),
        error_model=info.get("model"),
        details_extra=extra or None,
    )


async def log_event(
    *,
    action: str,
    label: str,
    actor_kind: str = "automation",
    actor_id: str | None = None,
    actor_name: str | None = None,
    actor_email: str | None = None,
    actor_role: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
    status: str = "ok",
    error: str | None = None,
    error_code: str | None = None,
    error_provider: str | None = None,
    error_model: str | None = None,
    details: Any = None,
    method: str | None = None,
    path: str | None = None,
    http_status: int | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    correlation_id: str | None = None,
) -> str | None:
    """Записывает одно завершённое событие (фон, автоматизация, auth)."""
    try:
        if actor_kind == "automation" and not actor_name:
            actor_name = "Автоматизация"
        now = _now()
        event_id = _new_event_id()
        raw_error = str(error) if error else None
        effective_code = error_code or error_code_for_status(http_status)
        human_error = (
            humanize_error(
                raw_error,
                http_status=http_status,
                error_code=effective_code,
                provider=error_provider,
                model=error_model,
            )
            if (raw_error or effective_code)
            else None
        )
        detail_value = safe_details(details) if details else {}
        if raw_error and human_error and raw_error != human_error:
            if not isinstance(detail_value, dict):
                detail_value = {"details": detail_value}
            detail_value.setdefault("raw_error", raw_error[:1000])
        row = AuditEvent(
            id=event_id,
            created_at=now,
            finished_at=now,
            duration_ms=0,
            actor_kind=actor_kind,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_email=actor_email,
            actor_role=actor_role,
            action=action,
            action_label=label,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            method=method,
            path=path[:500] if path else None,
            status=status,
            http_status=http_status,
            error=(human_error[:_MAX_ERROR] if human_error else None),
            error_code=effective_code,
            error_provider=error_provider,
            error_model=error_model,
            details=_limit_details(detail_value) if detail_value else None,
            ip=ip[:64] if ip else None,
            user_agent=user_agent[:300] if user_agent else None,
            search_text=_search_blob(
                event_id, event_id.replace("-", ""),
                action, label, actor_name, actor_email, actor_id,
                target_type, target_id, target_name, path,
                raw_error, effective_code, error_provider, error_model,
            ),
            correlation_id=correlation_id,
        )
        async with SessionLocal() as session:
            session.add(row)
            await session.commit()
        return event_id
    except Exception as exc:  # noqa: BLE001
        print(f"[audit] log failed: {type(exc).__name__}: {exc}")
        return None


def _to_dict(row: AuditEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": _iso(row.created_at),
        "finished_at": _iso(row.finished_at),
        "duration_ms": row.duration_ms,
        "actor_kind": row.actor_kind,
        "actor_id": row.actor_id,
        "actor_name": row.actor_name,
        "actor_email": row.actor_email,
        "actor_role": row.actor_role,
        "action": row.action,
        "action_label": row.action_label,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "target_name": row.target_name,
        "method": row.method,
        "path": row.path,
        "status": row.status,
        "http_status": row.http_status,
        "error": row.error,
        "error_code": row.error_code,
        "error_provider": row.error_provider,
        "error_model": row.error_model,
        "details": row.details,
        "ip": row.ip,
        "user_agent": row.user_agent,
        "correlation_id": row.correlation_id,
    }


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def list_events(
    *,
    q: str | None = None,
    status: str | None = None,
    action: str | None = None,
    error_code: str | None = None,
    error_provider: str | None = None,
    error_model: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    filters = []
    if q:
        like = f"%{q.strip().lower()}%"
        filters.append(AuditEvent.search_text.like(like))
    if status:
        filters.append(AuditEvent.status == status)
    if action:
        filters.append(AuditEvent.action == action)
    if error_code:
        filters.append(AuditEvent.error_code == error_code)
    if error_provider:
        filters.append(AuditEvent.error_provider == error_provider)
    if error_model:
        filters.append(AuditEvent.error_model == error_model)
    if target_type:
        filters.append(AuditEvent.target_type == target_type)
    if target_id:
        filters.append(AuditEvent.target_id == target_id)
    since_dt = _parse_dt(since)
    if since_dt:
        filters.append(AuditEvent.created_at >= since_dt)
    until_dt = _parse_dt(until)
    if until_dt:
        filters.append(AuditEvent.created_at <= until_dt)

    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    async with SessionLocal() as session:
        total = await session.scalar(
            select(func.count()).select_from(AuditEvent).where(*filters)
        )
        rows = (
            await session.execute(
                select(AuditEvent)
                .where(*filters)
                .order_by(AuditEvent.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    return {"items": [_to_dict(row) for row in rows], "total": int(total or 0)}


async def list_actions() -> list[dict[str, str]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(AuditEvent.action, AuditEvent.action_label)
                .distinct()
                .order_by(AuditEvent.action)
            )
        ).all()
    return [
        {"action": str(action), "label": str(label)}
        for action, label in rows
    ]


async def error_stats(
    *, since: str | None = None, until: str | None = None
) -> dict[str, Any]:
    """Сводка ошибок по коду и модели — для быстрой статистики."""
    filters = [AuditEvent.status == "error"]
    since_dt = _parse_dt(since)
    if since_dt:
        filters.append(AuditEvent.created_at >= since_dt)
    until_dt = _parse_dt(until)
    if until_dt:
        filters.append(AuditEvent.created_at <= until_dt)

    async with SessionLocal() as session:
        total = await session.scalar(
            select(func.count()).select_from(AuditEvent).where(*filters)
        )
        code_rows = (
            await session.execute(
                select(AuditEvent.error_code, func.count())
                .where(*filters, AuditEvent.error_code.is_not(None))
                .group_by(AuditEvent.error_code)
                .order_by(func.count().desc())
            )
        ).all()
        model_rows = (
            await session.execute(
                select(
                    AuditEvent.error_provider,
                    AuditEvent.error_model,
                    func.count(),
                )
                .where(*filters, AuditEvent.error_model.is_not(None))
                .group_by(AuditEvent.error_provider, AuditEvent.error_model)
                .order_by(func.count().desc())
            )
        ).all()

    return {
        "total_errors": int(total or 0),
        "by_code": [
            {"code": str(code), "count": int(count)}
            for code, count in code_rows
        ],
        "by_model": [
            {
                "provider": str(provider) if provider else None,
                "model": str(model),
                "count": int(count),
            }
            for provider, model, count in model_rows
        ],
    }


async def get_event(event_id: str) -> dict[str, Any] | None:
    async with SessionLocal() as session:
        row = await session.get(AuditEvent, event_id)
    return _to_dict(row) if row else None


async def mark_stale_running() -> int:
    """Помечает незавершённые события прошлого запуска как прерванные."""
    try:
        now = _now()
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.status == "running",
                        AuditEvent.finished_at.is_(None),
                    )
                )
            ).scalars().all()
            for row in rows:
                row.status = "error"
                row.error = "Прервано перезапуском сервера"
                row.finished_at = now
                created = row.created_at
                if created is not None:
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    row.duration_ms = max(
                        0, int((now - created).total_seconds() * 1000)
                    )
            await session.commit()
        if rows:
            print(f"[audit] marked {len(rows)} interrupted events")
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        print(f"[audit] stale check failed: {type(exc).__name__}: {exc}")
        return 0


async def cleanup(retention_days: int) -> int:
    days = max(1, min(int(retention_days or 90), 3650))
    cutoff = _now() - timedelta(days=days)
    async with SessionLocal() as session:
        result = await session.execute(
            delete(AuditEvent).where(AuditEvent.created_at < cutoff)
        )
        await session.commit()
        return int(result.rowcount or 0)


async def audit_cleanup_worker() -> None:
    """Раз в сутки удаляет события старше настроенного срока."""
    await asyncio.sleep(600)
    while True:
        try:
            from stores.settings import settings_store

            days = int(settings_store.get("audit_retention_days", 90) or 90)
            removed = await cleanup(days)
            if removed:
                print(f"[audit] removed {removed} events older than {days} days")
            try:
                from services.auth_sessions import cleanup_old as cleanup_sessions

                sessions = await cleanup_sessions(30)
                if sessions:
                    print(f"[auth-session] removed {sessions} old sessions")
            except Exception as exc:  # noqa: BLE001
                print(f"[auth-session] cleanup failed: {exc}")
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[audit] cleanup failed: {type(exc).__name__}: {exc}")
        await asyncio.sleep(24 * 3600)
