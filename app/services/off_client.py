"""Клиент Open Food Facts.

Чтение (поиск по штрих-коду) — без авторизации.
Запись (контрибуция) — через логин/пароль от аккаунта OFF, только
если явно включено в config.yaml.

Особенности:
- Кэш продуктов на диск (/data/off_cache.json) с TTL.
- Отдельная обработка внутренних штрих-кодов магазинов (префикс 20–29) —
  они не существуют в OFF, сразу возвращаем "not_found".
- Унифицированный ответ: {found, product, source, cached}.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import aiofiles
import httpx
from fastapi import HTTPException

from config import (
    OFF_CACHE_FILE,
    OFF_CACHE_TTL_DAYS,
    OFF_CONTRIBUTE_ENABLED,
    OFF_ENABLED,
    OFF_PASSWORD,
    OFF_SUBDOMAIN,
    OFF_TIMEOUT_SEC,
    OFF_USER_AGENT,
    OFF_USER_ID,
)
from stores.ingredients import is_internal_barcode


# --- URL-хелперы ----------------------------------------------------------

def _api_base() -> str:
    sub = (OFF_SUBDOMAIN or "world").strip().lower()
    if sub not in ("world", "ru", "us", "fr", "de", "es", "it", "uk"):
        sub = "world"
    # OFF отдаёт API на поддомене: ru.openfoodfacts.org, world.openfoodfacts.org и т.д.
    return f"https://{sub}.openfoodfacts.org"


def _headers() -> dict[str, str]:
    return {
        "User-Agent": OFF_USER_AGENT or "HomeAssistant-RecipeManager/1.0",
        "Accept": "application/json",
    }


# --- Локальный кэш --------------------------------------------------------

class _OffCache:
    """Простой JSON-кэш продуктов из OFF.

    Ключ — штрих-код. Значение — {ts, product}. По истечении TTL —
    перезапрашиваем OFF. Продукты, которых нет в OFF, не кэшируются
    (отрицательный кэш не делаем — товар может появиться позже).
    """

    def __init__(self, path: Path, ttl_days: int) -> None:
        self.path = path
        self.ttl_sec = max(1, ttl_days) * 86400
        self._data: dict[str, Any] = {}
        self._loaded = False

    async def _ensure(self) -> None:
        if self._loaded:
            return
        if self.path.exists():
            try:
                async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.loads(await f.read())
            except Exception as exc:  # noqa: BLE001
                print(f"[off] cache load failed: {exc}")
                self._data = {}
        self._loaded = True

    async def get(self, barcode: str) -> dict[str, Any] | None:
        await self._ensure()
        entry = self._data.get(barcode)
        if not entry:
            return None
        if time.time() - entry.get("ts", 0) > self.ttl_sec:
            # Просрочено — удаляем, вернём None
            self._data.pop(barcode, None)
            await self._save()
            return None
        return entry.get("product")

    async def set(self, barcode: str, product: dict[str, Any]) -> None:
        await self._ensure()
        self._data[barcode] = {"ts": time.time(), "product": product}
        await self._save()

    async def drop(self, barcode: str) -> None:
        await self._ensure()
        if barcode in self._data:
            self._data.pop(barcode, None)
            await self._save()

    async def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
                await f.write(json.dumps(self._data, ensure_ascii=False, indent=2))
            tmp.replace(self.path)
        except Exception as exc:  # noqa: BLE001
            print(f"[off] cache save failed: {exc}")

    async def clear(self) -> int:
        await self._ensure()
        n = len(self._data)
        self._data = {}
        await self._save()
        return n

    async def stats(self) -> dict[str, Any]:
        await self._ensure()
        return {"entries": len(self._data), "ttl_days": self.ttl_sec // 86400}


_cache = _OffCache(OFF_CACHE_FILE, OFF_CACHE_TTL_DAYS)


# --- Парсинг ответа OFF ---------------------------------------------------

def _parse_product(raw: dict[str, Any], barcode: str) -> dict[str, Any] | None:
    """Преобразует ответ OFF в наш внутренний формат продукта.

    Возвращает None, если из ответа невозможно извлечь даже название.
    """
    if not isinstance(raw, dict):
        return None

    # Название: приоритет русскому, потом английскому, потом generic
    name = (
        raw.get("product_name_ru")
        or raw.get("product_name")
        or raw.get("product_name_en")
        or raw.get("generic_name")
        or ""
    ).strip()
    if not name:
        return None

    nutriments = raw.get("nutriments") or {}
    nutrition = _parse_nutriments(nutriments)

    categories_raw = raw.get("categories") or ""
    category = None
    if isinstance(categories_raw, str) and categories_raw.strip():
        category = categories_raw.split(",")[0].strip()

    brands_raw = raw.get("brands") or ""
    brand = None
    if isinstance(brands_raw, str) and brands_raw.strip():
        brand = brands_raw.split(",")[0].strip()

    image_url = (
        raw.get("image_front_url")
        or raw.get("image_url")
        or raw.get("image_front_small_url")
        or None
    )

    serving_size = raw.get("serving_size") or None

    return {
        "name": name,
        "brand": brand,
        "category": category,
        "barcode": barcode,
        "image_url": image_url,
        "nutrition_per_100g": nutrition,
        "serving_size": serving_size,
        "source": "openfoodfacts",
        "raw_last_modified": raw.get("last_modified_t"),
    }


def _parse_nutriments(n: dict[str, Any]) -> dict[str, Any]:
    """Собирает КБЖУ на 100 г из nutriments OFF."""
    out: dict[str, Any] = {}

    def _f(key_100g: str, key_serving: str | None = None) -> float | None:
        for k in (key_100g, key_serving):
            if not k:
                continue
            v = n.get(k)
            if v is None or v == "":
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return None

    calories = _f("energy-kcal_100g", "energy-kcal_serving")
    if calories is None:
        # energy в кДж → ккал
        kj = _f("energy_100g", "energy_serving")
        if kj is not None:
            calories = round(kj / 4.184, 1)

    if calories is not None:
        out["calories"] = calories
    protein = _f("proteins_100g", "proteins_serving")
    if protein is not None:
        out["protein"] = protein
    fat = _f("fat_100g", "fat_serving")
    if fat is not None:
        out["fat"] = fat
    sat = _f("saturated-fat_100g", "saturated-fat_serving")
    if sat is not None:
        out["saturated_fat"] = sat
    carbs = _f("carbohydrates_100g", "carbohydrates_serving")
    if carbs is not None:
        out["carbohydrates"] = carbs
    sugar = _f("sugars_100g", "sugars_serving")
    if sugar is not None:
        out["sugar"] = sugar
    fiber = _f("fiber_100g", "fiber_serving")
    if fiber is not None:
        out["fiber"] = fiber
    sodium_g = _f("sodium_100g", "sodium_serving")
    if sodium_g is not None:
        # OFF хранит натрий в граммах, у нас — в мг
        out["sodium"] = round(sodium_g * 1000, 1)
    salt = _f("salt_100g", "salt_serving")
    if salt is not None and "sodium" not in out:
        # соль → натрий: 1 г соли ≈ 400 мг натрия
        out["sodium"] = round(salt * 400, 1)

    return out


# --- Публичное API --------------------------------------------------------

async def fetch_product(barcode: str, use_cache: bool = True) -> dict[str, Any]:
    """Запрашивает продукт в OFF по штрих-коду.

    Возвращает:
        {
            "found": bool,
            "product": {...} | None,
            "source": "openfoodfacts" | "internal_barcode" | "disabled" | "not_found",
            "cached": bool,
        }

    Не бросает HTTPException при not_found — это нормальный сценарий,
    пользователь введёт продукт вручную.
    """
    code = (barcode or "").strip()
    if not code or not code.isdigit():
        raise HTTPException(400, "Штрих-код должен содержать только цифры")

    if not OFF_ENABLED:
        return {"found": False, "product": None, "source": "disabled", "cached": False}

    # Внутренний код магазина — OFF заведомо не поможет
    if is_internal_barcode(code):
        return {
            "found": False,
            "product": None,
            "source": "internal_barcode",
            "cached": False,
        }

    # Кэш
    if use_cache:
        cached = await _cache.get(code)
        if cached is not None:
            return {"found": True, "product": cached, "source": "openfoodfacts", "cached": True}

    # Запрос к OFF
    url = f"{_api_base()}/api/v2/product/{code}.json"
    params = {
        "fields": (
            "code,product_name,product_name_ru,product_name_en,generic_name,"
            "brands,categories,image_url,image_front_url,image_front_small_url,"
            "nutriments,serving_size,last_modified_t"
        )
    }

    try:
        async with httpx.AsyncClient(timeout=OFF_TIMEOUT_SEC, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=_headers())
    except httpx.TimeoutException:
        print(f"[off] timeout for {code}")
        return {"found": False, "product": None, "source": "timeout", "cached": False}
    except Exception as exc:  # noqa: BLE001
        print(f"[off] request failed for {code}: {exc}")
        return {"found": False, "product": None, "source": "error", "cached": False}

    if resp.status_code == 404:
        return {"found": False, "product": None, "source": "not_found", "cached": False}
    if resp.status_code != 200:
        print(f"[off] http {resp.status_code} for {code}")
        return {"found": False, "product": None, "source": "error", "cached": False}

    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[off] invalid json for {code}: {exc}")
        return {"found": False, "product": None, "source": "error", "cached": False}

    if data.get("status") != 1:
        return {"found": False, "product": None, "source": "not_found", "cached": False}

    raw = data.get("product") or {}
    product = _parse_product(raw, code)
    if not product:
        return {"found": False, "product": None, "source": "not_found", "cached": False}

    if use_cache:
        await _cache.set(code, product)

    return {"found": True, "product": product, "source": "openfoodfacts", "cached": False}


async def fetch_by_barcode_simple(barcode: str) -> dict[str, Any] | None:
    """Упрощённая версия — только продукт или None. Для использования в матчере."""
    res = await fetch_product(barcode)
    return res.get("product") if res.get("found") else None


# --- Контрибуция (заготовка) ----------------------------------------------

async def can_contribute() -> tuple[bool, str | None]:
    """Проверяет, можно ли отправлять продукты в OFF.

    Возвращает (ok, reason). reason — почему нельзя.
    """
    if not OFF_ENABLED:
        return False, "Open Food Facts выключен в настройках"
    if not OFF_CONTRIBUTE_ENABLED:
        return False, "Отправка в Open Food Facts выключена в настройках"
    if not OFF_USER_ID:
        return False, "Не указан off_user_id"
    if not OFF_PASSWORD:
        return False, "Не указан off_password"
    return True, None


async def contribute_product(product: dict[str, Any]) -> dict[str, Any]:
    """Отправляет продукт в Open Food Facts.

    ВНИМАНИЕ: это необратимая операция — данные уйдут в публичную базу.
    В первой итерации используется только через явное подтверждение
    пользователя в UI.

    product должен содержать как минимум:
        barcode, name, nutrition_per_100g

    Возвращает:
        {"ok": bool, "status": int, "message": str}
    """
    ok, reason = await can_contribute()
    if not ok:
        return {"ok": False, "status": 0, "message": reason or "not allowed"}

    barcode = (product.get("barcode") or "").strip()
    if not barcode or not barcode.isdigit():
        return {"ok": False, "status": 0, "message": "Некорректный штрих-код"}

    nutrition = product.get("nutrition_per_100g") or {}
    payload: dict[str, Any] = {
        "code": barcode,
        "user_id": OFF_USER_ID,
        "password": OFF_PASSWORD,
        # Названия. Используем `add_` префикс, чтобы не перезатирать
        # существующие локализации, а дополнять их.
        "add_product_name_ru": product.get("name") or "",
        "add_brands": product.get("brand") or "",
        "add_categories": product.get("category") or "",
    }

    # КБЖУ на 100 г. Также с префиксом add_, чтобы не перезатирать то,
    # что уже введено другими контрибьюторами.
    def _set_num(key: str, value: Any) -> None:
        if value is None or value == "":
            return
        payload[f"add_{key}_100g"] = str(value)

    _set_num("energy-kcal", nutrition.get("calories"))
    _set_num("proteins", nutrition.get("protein"))
    _set_num("fat", nutrition.get("fat"))
    _set_num("saturated-fat", nutrition.get("saturated_fat"))
    _set_num("carbohydrates", nutrition.get("carbohydrates"))
    _set_num("sugars", nutrition.get("sugar"))
    _set_num("fiber", nutrition.get("fiber"))
    # sodium в OFF хранится в граммах
    sodium_mg = nutrition.get("sodium")
    if sodium_mg is not None:
        try:
            payload["add_sodium_100g"] = str(float(sodium_mg) / 1000)
        except (TypeError, ValueError):
            pass

    url = f"{_api_base()}/cgi/product_jqm2.pl"
    try:
        async with httpx.AsyncClient(timeout=OFF_TIMEOUT_SEC * 2, follow_redirects=True) as client:
            resp = await client.post(url, data=payload, headers=_headers())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": 0, "message": f"Ошибка сети: {exc}"}

    if resp.status_code == 200:
        try:
            data = resp.json()
        except Exception:
            data = {}
        if data.get("status") == "success" or data.get("status_code") == 200:
            # Сбрасываем локальный кэш для этого barcode, чтобы не тянуть старое
            await _cache.drop(barcode)
            return {"ok": True, "status": 200, "message": "Продукт отправлен в Open Food Facts"}
        return {
            "ok": False,
            "status": resp.status_code,
            "message": f"OFF вернул: {data.get('status_verbose') or data.get('status') or 'unknown'}",
        }

    return {
        "ok": False,
        "status": resp.status_code,
        "message": f"HTTP {resp.status_code}: {resp.text[:200]}",
    }


# --- Утилиты --------------------------------------------------------------

async def cache_stats() -> dict[str, Any]:
    return await _cache.stats()


async def cache_clear() -> int:
    return await _cache.clear()