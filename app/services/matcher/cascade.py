"""Оркестратор каскада матчинга.

Только здесь известно, какие провайдеры существуют, в каком порядке
вызываются и как обрабатываются ошибки. Все остальные модули
(matcher/*.py) — независимые компоненты.

Публичный контракт (реэкспортируется через __init__.py):
    match_name(name, context=None, thresholds=None) -> dict
    match_batch(names, context=None, thresholds=None, deduplicate=True) -> dict
    validate_pair(name, product) -> dict
    apply_link_to_recipe(recipe_id, ingredient_name, product_id) -> bool
    apply_links_to_recipe(recipe_id, links) -> int
    status() -> dict
    check_provider(provider) -> dict
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timezone
from typing import Any

from config import (
    LOCAL_EMBEDDER_ENABLED,
    MATCHER_AUTO_THRESHOLD,
    MATCHER_CONFIRM_MODE,
    MATCHER_DAILY_LIMIT,
    MATCHER_EXTERNAL_EMBEDDING_MODEL,
    MATCHER_EXTERNAL_ENABLED,
    MATCHER_PROVIDER,
    MATCHER_SUGGEST_THRESHOLD,
)
from stores import ingredients_store, recipe_store

from .base import (
    MatchCandidate,
    MatchDecision,
    MatchMethod,
    MatchResult,
    ProviderInfo,
    ProviderUnavailable,
    RateLimited,
    Thresholds,
    ValidationResult,
    cosine_similarity,
    normalize_name,
    top_n,
)
from .local_fuzzy import local_fuzzy_matcher

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ленивые импорты провайдеров. Если модуль ещё не собран — провайдер = None
# и просто пропускается каскадом. Это позволяет запускать аддон, пока
# часть инфраструктуры не готова.
# ---------------------------------------------------------------------------

try:
    from .gemini_embedder import gemini_embedder  # type: ignore[import]
except Exception as _exc:  # noqa: BLE001
    gemini_embedder = None  # type: ignore[assignment]
    logger.info("gemini_embedder недоступен: %s", _exc)

try:
    from .external_llm import external_llm  # type: ignore[import]
except Exception as _exc:  # noqa: BLE001
    external_llm = None  # type: ignore[assignment]
    logger.info("external_llm недоступен: %s", _exc)

try:
    from .local_embedder import local_embedder  # type: ignore[import]
except Exception as _exc:  # noqa: BLE001
    local_embedder = None  # type: ignore[assignment]
    logger.info("local_embedder недоступен: %s", _exc)


# ---------------------------------------------------------------------------
# Кэш результатов (in-memory, сбрасывается при перезапуске аддона).
# ---------------------------------------------------------------------------

_RESULT_CACHE: dict[str, MatchResult] = {}
_VECTOR_CACHE: dict[str, list[float]] = {}   # "model_key::text" -> vector
_VALIDATION_CACHE: dict[str, ValidationResult] = {}  # "name::product_id" -> result

_DAILY_COUNTER: dict[str, dict[str, Any]] = {}  # provider -> {"date": "...", "count": N}


# ---------------------------------------------------------------------------
# Публичные функции
# ---------------------------------------------------------------------------

async def match_name(
    name: str,
    context: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Матч одного имени ингредиента."""
    thr = Thresholds.from_dict(thresholds)
    if thresholds is None:
        thr = Thresholds(
            auto=MATCHER_AUTO_THRESHOLD,
            suggest=MATCHER_SUGGEST_THRESHOLD,
        )

    q_norm = normalize_name(name)
    if not q_norm:
        return MatchResult(
            query=name, normalized="", decision=MatchDecision.NOT_FOUND,
        ).to_dict()

    # Кэш
    cache_key = f"{q_norm}|{thr.auto}|{thr.suggest}"
    cached = _RESULT_CACHE.get(cache_key)
    if cached is not None:
        result = MatchResult(**{**cached.__dict__, "from_cache": True})
        return result.to_dict()

    result = await _match_internal(name, q_norm, thr, context)
    _RESULT_CACHE[cache_key] = result
    return result.to_dict()


async def match_batch(
    names: list[str],
    context: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    deduplicate: bool = True,
) -> dict[str, Any]:
    """Матч массива имён с опциональной дедупликацией."""
    thr = Thresholds.from_dict(thresholds)
    if thresholds is None:
        thr = Thresholds(
            auto=MATCHER_AUTO_THRESHOLD,
            suggest=MATCHER_SUGGEST_THRESHOLD,
        )

    original_count = len(names)

    if deduplicate:
        seen: dict[str, str] = {}  # norm -> original
        for n in names:
            n_norm = normalize_name(n)
            if n_norm and n_norm not in seen:
                seen[n_norm] = n
        unique_names = list(seen.values())
    else:
        unique_names = [n for n in names if normalize_name(n)]

    unique_count = len(unique_names)

    # Параллелим, но с ограничением (10 одновременных)
    sem = asyncio.Semaphore(10)

    async def _one(n: str) -> dict[str, Any]:
        async with sem:
            return await match_name(n, context=context, thresholds=thresholds)

    results = await asyncio.gather(*[_one(n) for n in unique_names])

    # Если была дедупликация — «размножаем» результат обратно по исходным именам
    if deduplicate:
        by_norm = {r["normalized"]: r for r in results}
        expanded = []
        for n in names:
            r = by_norm.get(normalize_name(n))
            if r:
                expanded.append({**r, "query": n})
        results = expanded

    stats = {
        "total": original_count,
        "unique": unique_count,
        "matched_auto": sum(1 for r in results if r.get("decision") == "matched"),
        "need_confirmation": sum(1 for r in results if r.get("needs_confirmation")),
        "not_found": sum(1 for r in results if r.get("decision") == "not_found"),
        "errors": sum(1 for r in results if r.get("error")),
    }

    return {"results": results, "stats": stats}


async def validate_pair(name: str, product: dict[str, Any]) -> dict[str, Any]:
    """Генеративная валидация пары (имя, продукт)."""
    cache_key = f"{normalize_name(name)}::{product.get('product_id')}"
    cached = _VALIDATION_CACHE.get(cache_key)
    if cached is not None:
        return {**cached.to_dict(), "from_cache": True}

    result = await _validate_internal(name, product)
    _VALIDATION_CACHE[cache_key] = result
    return result.to_dict()


async def apply_link_to_recipe(
    recipe_id: str,
    ingredient_name: str,
    product_id: str,
) -> bool:
    """Проставляет product_id в ингредиентах рецепта, чьё имя совпадает."""
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        return False

    target_norm = normalize_name(ingredient_name)
    changed = False

    ingredients = recipe.get("ingredients") or []
    for i, ing in enumerate(ingredients):
        if isinstance(ing, str):
            if normalize_name(ing) == target_norm:
                ingredients[i] = {
                    "name": ing,
                    "product_id": product_id,
                }
                changed = True
        elif isinstance(ing, dict):
            if normalize_name(ing.get("name") or "") == target_norm:
                if ing.get("product_id") != product_id:
                    ingredients[i] = {**ing, "product_id": product_id}
                    changed = True

    if changed:
        await recipe_store.update(recipe_id, {"ingredients": ingredients})

    return changed


async def apply_links_to_recipe(
    recipe_id: str,
    links: list[dict[str, Any]],
) -> int:
    """Массово применяет связки к рецепту. Возвращает число обновлённых ингредиентов."""
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        return 0

    by_norm: dict[str, str] = {}
    for link in links or []:
        n = normalize_name(link.get("name") or "")
        pid = link.get("product_id")
        if n and pid:
            by_norm[n] = pid

    if not by_norm:
        return 0

    changed_count = 0
    ingredients = recipe.get("ingredients") or []

    for i, ing in enumerate(ingredients):
        if isinstance(ing, str):
            n = normalize_name(ing)
            if n in by_norm:
                ingredients[i] = {"name": ing, "product_id": by_norm[n]}
                changed_count += 1
        elif isinstance(ing, dict):
            n = normalize_name(ing.get("name") or "")
            if n in by_norm and ing.get("product_id") != by_norm[n]:
                ingredients[i] = {**ing, "product_id": by_norm[n]}
                changed_count += 1

    if changed_count:
        await recipe_store.update(recipe_id, {"ingredients": ingredients})

    return changed_count


async def status() -> dict[str, Any]:
    """Состояние каскада: провайдеры, приоритеты, лимиты."""
    providers_info: list[ProviderInfo] = []

    # Локальный fuzzy — всегда
    providers_info.append(await local_fuzzy_matcher.health())

    # Внешний OpenAI-совместимый (Hermes)
    if external_llm is not None and MATCHER_EXTERNAL_ENABLED:
        try:
            providers_info.append(await external_llm.health())
        except Exception as exc:  # noqa: BLE001
            providers_info.append(ProviderInfo(
                name="hermes",
                kind=external_llm.__class__.__mro__[1].__dict__.get("kind", "generative") if hasattr(external_llm, "__class__") else "generative",
                enabled=True, available=False, priority=20,
                error=str(exc),
            ))

    # Gemini
    if gemini_embedder is not None:
        try:
            providers_info.append(await gemini_embedder.health())
        except Exception as exc:  # noqa: BLE001
            providers_info.append(ProviderInfo(
                name="gemini", kind="embedding",  # type: ignore[arg-type]
                enabled=True, available=False, priority=40, error=str(exc),
            ))

    # Локальный эмбеддер
    if local_embedder is not None and LOCAL_EMBEDDER_ENABLED:
        try:
            providers_info.append(await local_embedder.health())
        except Exception as exc:  # noqa: BLE001
            providers_info.append(ProviderInfo(
                name="local_embedder", kind="embedding",  # type: ignore[arg-type]
                enabled=True, available=False, priority=30, error=str(exc),
            ))

    providers_info.sort(key=lambda p: p.priority)

    return {
        "mode": MATCHER_PROVIDER,
        "thresholds": {
            "auto": MATCHER_AUTO_THRESHOLD,
            "suggest": MATCHER_SUGGEST_THRESHOLD,
        },
        "confirm_mode": MATCHER_CONFIRM_MODE,
        "daily_limit": MATCHER_DAILY_LIMIT,
        "daily_usage": _daily_usage_snapshot(),
        "products_count": ingredients_store.count(),
        "providers": [p.to_dict() for p in providers_info],
        "priority": [p.name for p in providers_info if p.enabled],
    }


async def check_provider(provider: str) -> dict[str, Any]:
    """Проверка доступности конкретного провайдера."""
    provider = (provider or "").strip().lower()
    started = datetime.now(timezone.utc)

    if provider in ("local", "local_fuzzy", "fuzzy"):
        info = await local_fuzzy_matcher.health()
        return _provider_check_result(info, started)

    if provider == "hermes" or provider == "external":
        if external_llm is None:
            return _unavailable("external_llm не собран", started)
        if not MATCHER_EXTERNAL_ENABLED:
            return _unavailable("matcher_external_enabled=false", started)
        try:
            info = await external_llm.health()
            return _provider_check_result(info, started)
        except Exception as exc:  # noqa: BLE001
            return _unavailable(str(exc), started)

    if provider == "gemini":
        if gemini_embedder is None:
            return _unavailable("gemini_embedder не собран", started)
        try:
            info = await gemini_embedder.health()
            return _provider_check_result(info, started)
        except Exception as exc:  # noqa: BLE001
            return _unavailable(str(exc), started)

    if provider in ("local_embedder", "local_emb"):
        if local_embedder is None:
            return _unavailable("local_embedder не собран", started)
        if not LOCAL_EMBEDDER_ENABLED:
            return _unavailable("local_embedder_enabled=false", started)
        try:
            info = await local_embedder.health()
            return _provider_check_result(info, started)
        except Exception as exc:  # noqa: BLE001
            return _unavailable(str(exc), started)

    return _unavailable(f"неизвестный провайдер '{provider}'", started)


# ---------------------------------------------------------------------------
# Внутренняя логика матчинга
# ---------------------------------------------------------------------------

async def _match_internal(
    name: str,
    q_norm: str,
    thr: Thresholds,
    context: dict[str, Any] | None,
) -> MatchResult:
    """Реализация каскада."""

    # --- Уровень 0: exact через store (с учётом алиасов) ---
    exact = ingredients_store.find_by_name(name)
    if exact:
        candidate = _candidate_from_product(exact, score=1.0, method=MatchMethod.EXACT)
        return MatchResult(
            query=name, normalized=q_norm,
            decision=MatchDecision.MATCHED,
            match=candidate, candidates=[candidate],
        )

    # --- Уровень A: локальный fuzzy ---
    products = ingredients_store.list_all()
    if not products:
        return MatchResult(
            query=name, normalized=q_norm,
            decision=MatchDecision.NOT_FOUND,
        )

    fuzzy_candidates = local_fuzzy_matcher.find(name, products, limit=5)

    best_fuzzy = fuzzy_candidates[0] if fuzzy_candidates else None
    if best_fuzzy and best_fuzzy.score >= thr.auto:
        return MatchResult(
            query=name, normalized=q_norm,
            decision=MatchDecision.MATCHED,
            match=best_fuzzy, candidates=fuzzy_candidates,
        )

    # --- Уровень B: эмбеддинги ---
    vector_candidates: list[MatchCandidate] = []
    if MATCHER_PROVIDER not in ("none", "local"):
        try:
            vector_candidates = await _vector_match(name, thr)
        except ProviderUnavailable as exc:
            logger.debug("embedding providers unavailable: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vector match failed: %s", exc)

    all_candidates = _merge_candidates(fuzzy_candidates, vector_candidates)
    best = all_candidates[0] if all_candidates else None

    if best and best.score >= thr.auto:
        return MatchResult(
            query=name, normalized=q_norm,
            decision=MatchDecision.MATCHED,
            match=best, candidates=all_candidates,
        )

    # --- Уровень C: генеративная валидация ---
    if best and best.score >= thr.suggest and MATCHER_PROVIDER in ("auto", "external", "gemini"):
        validated = await _try_generative_validate(name, best)
        if validated and validated.valid is True:
            promoted = MatchCandidate(
                product_id=best.product_id,
                name=best.name,
                brand=best.brand,
                barcode=best.barcode,
                image_url=best.image_url,
                nutrition_per_100g=best.nutrition_per_100g,
                score=min(0.99, best.score + 0.05),
                method=MatchMethod.GENERATIVE,
                provider=validated.provider or "generative",
                matched_alias=best.matched_alias,
            )
            return MatchResult(
                query=name, normalized=q_norm,
                decision=MatchDecision.MATCHED,
                match=promoted, candidates=[promoted] + all_candidates,
            )
        elif validated and validated.valid is False:
            # Явно отвергли — убираем этого кандидата
            all_candidates = [c for c in all_candidates if c.product_id != best.product_id]
            best = all_candidates[0] if all_candidates else None

    if best and best.score >= thr.suggest:
        return MatchResult(
            query=name, normalized=q_norm,
            decision=MatchDecision.SUGGEST,
            match=best, candidates=all_candidates,
        )

    return MatchResult(
        query=name, normalized=q_norm,
        decision=MatchDecision.NOT_FOUND,
        candidates=all_candidates,
    )


async def _vector_match(name: str, thr: Thresholds) -> list[MatchCandidate]:
    """Уровень B: через эмбеддинги. Возвращает кандидатов.

    Score нормализуется через provider.baseline_similarity: разные
    embedding-модели дают разное «фоновое» сходство между семантически
    далёкими текстами. Например, Gemini embedding-001 для случайных пар
    обычно выдаёт 0.6–0.85, тогда как OpenAI и MiniLM — 0.0–0.3.

    Без нормализации Gemini засоряет выдачу мусорными кандидатами
    с score 0.85, которые ошибочно попадают в диапазон suggest.
    """
    provider = await _get_embedding_provider()
    if provider is None:
        return []

    model_key = provider.model_key
    baseline = float(getattr(provider, "baseline_similarity", 0.0) or 0.0)

    # Вектор запроса (с кэшем)
    query_vec = await _embed_one(provider, name, model_key)
    if not query_vec:
        return []

    # Все векторы продуктов для этой модели
    stored = ingredients_store.list_vectors(model_key)
    if not stored:
        # Ничего не проиндексировано — попробуем проиндексировать лениво (не более 50 за раз)
        await _lazy_index_products(provider, model_key, limit=50)
        stored = ingredients_store.list_vectors(model_key)

    if not stored:
        return []

    # Предварительный порог применяем к «сырому» score с учётом baseline:
    # отсекаем всё, что ниже (suggest - 0.05) после нормализации.
    raw_threshold = _denormalize_score(thr.suggest - 0.05, baseline)

    scored: list[MatchCandidate] = []
    for product_id, vec in stored:
        try:
            raw_score = cosine_similarity(query_vec, vec)
        except ValueError:
            continue

        if raw_score < raw_threshold:
            continue

        adjusted = _normalize_score(raw_score, baseline)
        if adjusted <= 0.0:
            continue

        product = ingredients_store.get_active(product_id)
        if not product:
            continue
        scored.append(_candidate_from_product(
            product, score=adjusted, method=MatchMethod.VECTOR, provider=provider.name,
        ))

    scored.sort(key=lambda c: -c.score)
    return scored[:5]


def _normalize_score(raw: float, baseline: float) -> float:
    """Приводит «сырое» косинусное сходство к единому диапазону [0, 1].

    Формула: adjusted = (raw - baseline) / (1 - baseline)

    Примеры для baseline=0.75:
        0.60 → 0.00 (ниже фона, отсекается)
        0.75 → 0.00
        0.85 → 0.40
        0.90 → 0.60
        0.95 → 0.80
        0.99 → 0.96

    Для baseline=0.0 (модели типа OpenAI/MiniLM) формула вырождается
    в тождество: adjusted = raw.
    """
    if baseline <= 0.0:
        return raw
    if baseline >= 1.0:
        return 0.0
    adjusted = (raw - baseline) / (1.0 - baseline)
    if adjusted < 0.0:
        return 0.0
    if adjusted > 1.0:
        return 1.0
    return adjusted


def _denormalize_score(adjusted: float, baseline: float) -> float:
    """Обратная операция к _normalize_score.

    Нужна для предварительного отсечения: мы хотим применять порог
    к «сырому» score, не считая косинус для всех продуктов.

    Формула: raw = adjusted * (1 - baseline) + baseline
    """
    if baseline <= 0.0:
        return adjusted
    return adjusted * (1.0 - baseline) + baseline

async def _get_embedding_provider() -> Any:
    """Возвращает первый доступный embedding-провайдер по приоритету."""
    # 1. External (Hermes с проксированием эмбеддингов)
    if (
        external_llm is not None
        and MATCHER_EXTERNAL_ENABLED
        and MATCHER_EXTERNAL_EMBEDDING_MODEL
        and hasattr(external_llm, "embed")
    ):
        if await _provider_is_healthy(external_llm, "hermes_embed"):
            return external_llm

    # 2. Локальный sentence-transformers
    if local_embedder is not None and LOCAL_EMBEDDER_ENABLED:
        if await _provider_is_healthy(local_embedder, "local_embedder"):
            return local_embedder

    # 3. Gemini
    if gemini_embedder is not None:
        if await _provider_is_healthy(gemini_embedder, "gemini"):
            return gemini_embedder

    return None


async def _provider_is_healthy(provider: Any, cache_key: str) -> bool:
    """Быстрый health-check с кэшем на 60 секунд."""
    now = datetime.now(timezone.utc).timestamp()
    entry = _DAILY_COUNTER.get(f"health::{cache_key}")
    if entry and now - entry.get("ts", 0) < 60:
        return bool(entry.get("ok"))

    try:
        info = await provider.health()
        ok = bool(getattr(info, "available", False))
    except Exception:  # noqa: BLE001
        ok = False

    _DAILY_COUNTER[f"health::{cache_key}"] = {"ts": now, "ok": ok}
    return ok


async def _embed_one(provider: Any, text: str, model_key: str) -> list[float] | None:
    """Возвращает вектор для одного текста (с кэшем)."""
    cache_key = f"{model_key}::{normalize_name(text)}"
    cached = _VECTOR_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if not await _check_daily_limit(provider.name):
        return None

    try:
        vectors = await provider.embed([text])
    except RateLimited:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.debug("embed_one failed for %s: %s", provider.name, exc)
        return None

    if not vectors:
        return None

    _VECTOR_CACHE[cache_key] = vectors[0]
    _increment_daily(provider.name)
    return vectors[0]


async def _lazy_index_products(provider: Any, model_key: str, limit: int = 50) -> None:
    """Считает векторы для продуктов, у которых их ещё нет."""
    products = ingredients_store.list_all()
    to_index = []
    for p in products:
        pid = p.get("product_id")
        if not pid:
            continue
        if ingredients_store.get_vector(pid, model_key):
            continue
        to_index.append(p)
        if len(to_index) >= limit:
            break

    if not to_index:
        return

    texts = [p.get("name") or "" for p in to_index]
    try:
        vectors = await provider.embed(texts)
    except Exception as exc:  # noqa: BLE001
        logger.warning("lazy index failed: %s", exc)
        return

    for p, vec in zip(to_index, vectors):
        await ingredients_store.set_vector(p["product_id"], model_key, vec)


async def _try_generative_validate(name: str, candidate: MatchCandidate) -> ValidationResult | None:
    """Пытается подтвердить пару через генеративный провайдер."""
    product = ingredients_store.get_active(candidate.product_id)
    if not product:
        return None

    # Приоритет: external (Hermes) → gemini
    for prov in _generative_providers():
        if not await _check_daily_limit(prov.name):
            continue
        try:
            result = await _ask_llm(prov, name, product)
            _increment_daily(prov.name)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.debug("generative validate via %s failed: %s", prov.name, exc)
            continue
    return None


def _generative_providers() -> list[Any]:
    out: list[Any] = []
    if external_llm is not None and MATCHER_EXTERNAL_ENABLED:
        out.append(external_llm)
    if gemini_embedder is not None and hasattr(gemini_embedder, "complete"):
        out.append(gemini_embedder)
    return out


async def _ask_llm(provider: Any, name: str, product: dict[str, Any]) -> ValidationResult:
    """Задаёт LLM вопрос «это один продукт?» и парсит ответ."""
    product_name = product.get("name") or ""
    brand = product.get("brand") or ""
    prompt = (
        f"Вопрос: это один и тот же продукт?\n"
        f"A: \"{name}\"\n"
        f"B: \"{product_name}\"{(' (' + brand + ')') if brand else ''}\n\n"
        f"Ответь одной строкой: ДА или НЕТ, и через дефис краткая причина."
    )
    system = (
        "Ты сопоставляешь названия продуктов из кулинарных рецептов. "
        "Твоя задача — определить, является ли B тем же самым продуктом, что и A. "
        "Учитывай синонимы, бренды, порядок слов. Игнорируй разницу в весе/упаковке. "
        "Если A — общее название (например, «масло»), а B — конкретный продукт, "
        "ответь НЕТ."
    )

    text = await provider.complete(prompt=prompt, system=system, max_tokens=60, temperature=0.0)
    return _parse_llm_validation(text, provider.name)


_VALID_RE = re.compile(r"^\s*(ДА|НЕТ|YES|NO)\b[\s\-—:]*(.*)$", re.IGNORECASE | re.DOTALL)


def _parse_llm_validation(text: str, provider_name: str) -> ValidationResult:
    m = _VALID_RE.match(text or "")
    if not m:
        return ValidationResult(
            valid=None, provider=provider_name, confidence=None,
            reason=(text or "").strip()[:200] or None,
        )

    answer = m.group(1).upper()
    reason = (m.group(2) or "").strip()[:200] or None
    valid = answer in ("ДА", "YES")
    return ValidationResult(
        valid=valid,
        provider=provider_name,
        confidence=0.85 if valid else 0.85,  # LLM часто не даёт число — ставим дефолт
        reason=reason,
    )


async def _validate_internal(name: str, product: dict[str, Any]) -> ValidationResult:
    """Реализация validate_pair."""
    for prov in _generative_providers():
        if not await _check_daily_limit(prov.name):
            continue
        try:
            result = await _ask_llm(prov, name, product)
            _increment_daily(prov.name)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.debug("validate via %s failed: %s", prov.name, exc)

    return ValidationResult(
        valid=None, provider=None,
        reason="Все генеративные провайдеры недоступны",
    )


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _candidate_from_product(
    p: dict[str, Any],
    score: float,
    method: MatchMethod,
    provider: str = "",
) -> MatchCandidate:
    return MatchCandidate(
        product_id=p.get("product_id") or "",
        name=p.get("name") or "",
        brand=p.get("brand"),
        barcode=p.get("barcode"),
        image_url=p.get("image_url"),
        nutrition_per_100g=p.get("nutrition_per_100g"),
        score=score,
        method=method,
        provider=provider,
    )


def _merge_candidates(
    fuzzy: list[MatchCandidate],
    vector: list[MatchCandidate],
) -> list[MatchCandidate]:
    """Объединяет кандидатов из двух уровней: один product_id — один кандидат, max score."""
    by_id: dict[str, MatchCandidate] = {}
    for c in fuzzy + vector:
        prev = by_id.get(c.product_id)
        if prev is None or c.score > prev.score:
            by_id[c.product_id] = c
    merged = list(by_id.values())
    merged.sort(key=lambda c: -c.score)
    return merged[:8]


# ---------------------------------------------------------------------------
# Daily limit (rate limiting)
# ---------------------------------------------------------------------------

def _today_str() -> str:
    return date.today().isoformat()


async def _check_daily_limit(provider_name: str) -> bool:
    """Проверяет, не исчерпан ли дневной лимит."""
    if MATCHER_DAILY_LIMIT <= 0:
        return True
    entry = _DAILY_COUNTER.get(provider_name)
    if not entry or entry.get("date") != _today_str():
        return True
    return int(entry.get("count", 0)) < MATCHER_DAILY_LIMIT


def _increment_daily(provider_name: str) -> None:
    if MATCHER_DAILY_LIMIT <= 0:
        return
    today = _today_str()
    entry = _DAILY_COUNTER.get(provider_name)
    if not entry or entry.get("date") != today:
        _DAILY_COUNTER[provider_name] = {"date": today, "count": 1}
    else:
        entry["count"] = int(entry.get("count", 0)) + 1


def _daily_usage_snapshot() -> dict[str, Any]:
    today = _today_str()
    out: dict[str, Any] = {}
    for name, entry in _DAILY_COUNTER.items():
        if name.startswith("health::"):
            continue
        if entry.get("date") != today:
            continue
        out[name] = {
            "count": int(entry.get("count", 0)),
            "limit": MATCHER_DAILY_LIMIT,
        }
    return out


# ---------------------------------------------------------------------------
# Сброс кэшей (используется при изменении состава продуктов)
# ---------------------------------------------------------------------------

def invalidate_cache() -> None:
    """Полная очистка кэшей результатов и векторов."""
    _RESULT_CACHE.clear()
    _VECTOR_CACHE.clear()
    _VALIDATION_CACHE.clear()


def invalidate_product_cache(product_id: str) -> None:
    """Убирает из кэшей всё, что связано с конкретным продуктом."""
    # Результаты — не знаем, где встречается product_id, чистим полностью
    _RESULT_CACHE.clear()
    # Валидации — только с этим product_id
    for key in list(_VALIDATION_CACHE.keys()):
        if key.endswith(f"::{product_id}"):
            _VALIDATION_CACHE.pop(key, None)


# ---------------------------------------------------------------------------
# Helpers для check_provider
# ---------------------------------------------------------------------------

def _provider_check_result(info: ProviderInfo, started: datetime) -> dict[str, Any]:
    latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
    return {
        "provider": info.name,
        "ok": bool(info.available),
        "latency_ms": round(latency_ms, 1),
        "detail": info.notes or (info.error or None),
        "model": info.model_key,
    }


def _unavailable(detail: str, started: datetime) -> dict[str, Any]:
    latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
    return {
        "provider": None,
        "ok": False,
        "latency_ms": round(latency_ms, 1),
        "detail": detail,
    }