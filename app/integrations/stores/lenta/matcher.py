"""LLM-матчинг позиций списка покупок с товарами Ленты.

Если LLM недоступен, используется детерминированный fallback по сходству
названий — интеграция не должна полностью ломаться из-за модели.
"""
from __future__ import annotations

import asyncio
import json
import re
from difflib import SequenceMatcher
from typing import Any

from config import LENTA_LLM_TIMEOUT
from integrations.stores.lenta.models import (
    BatchPick,
    LentaProduct,
    MatchItem,
    ProductPick,
)
from services.llm_cascade import call_llm_cascade

SYSTEM_PROMPT = """\
Ты — эксперт по ассортименту магазина Лента.
На вход подаётся массив задач (JSON). В каждой задаче:
  task_index         — номер (1..N), НЕ МЕНЯЙ его
  name               — название ингредиента
  suggested_quantity — сколько нужно купить (Recipe Manager уже сконвертировал)
  suggested_unit     — "г", "мл", "шт" (иногда "кг", "л")
  piece_weight_g     — вес 1 шт в граммах для штучных товаров
  sku_hint           — необязательные подсказки: barcode / brand / name
  notes              — заметка пользователя
  candidates         — товары Ленты: id / name / price_rub / price_per_kg /
                       weight_g / package / stock / rating / brand

Для КАЖДОЙ задачи верни РОВНО ОДИН элемент в items ответа.
Количество элементов items ДОЛЖНО совпадать с количеством задач.
product_id = 0, если ни один кандидат не подходит.

Правила:
1. Выбирай товар того же базового типа, что и ингредиент.
2. Учитывай бренд из sku_hint.brand и заметки пользователя.
3. Для весовых ингредиентов ("г", "кг") предпочитай весовой аналог,
   если он есть и заметка не требует упаковку/бренд.
4. Сравнивай price_per_kg, а не цену упаковки, когда выбираешь между
   весовым и фасованным товаром.
5. Не выбирай товар с stock = 0.
6. Используй ТОЛЬКО id из candidates. Никогда не выдумывай id.
7. packages — приблизительное число упаковок/квантов; окончательное
   количество всё равно пересчитает код. Округляй вверх.
8. reason — короткая строка, confidence — 0..1.

Формат ответа — строго JSON:
{"items": [{"task_index": 1, "product_id": 123, "packages": 1, "reason": "...", "confidence": 0.8}]}
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_RE.search(text)
        if not match:
            raise
        return json.loads(match.group(0))


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(value or "") if len(token) > 1}


def _similarity(item_name: str, product_name: str) -> float:
    item_tokens = _tokens(item_name)
    product_tokens = _tokens(product_name)
    if not item_tokens or not product_tokens:
        return 0.0
    overlap = len(item_tokens & product_tokens) / len(item_tokens)
    ratio = SequenceMatcher(None, item_name.lower(), product_name.lower()).ratio()
    return overlap * 0.7 + ratio * 0.3


def _fallback_pick(item: MatchItem, candidates: list[LentaProduct]) -> ProductPick:
    available = [p for p in candidates if (p.stock or 0) > 0]
    if not available:
        return ProductPick(product_id=0, reason="нет товара в наличии")
    scored = sorted(
        available,
        key=lambda p: (_similarity(item.name, p.name), p.rating or 0),
        reverse=True,
    )
    best = scored[0]
    score = _similarity(item.name, best.name)
    if score < 0.18:
        return ProductPick(product_id=0, reason="нет подходящего товара")
    return ProductPick(
        product_id=best.id,
        packages=1.0,
        reason=f"fallback: {best.name}",
        confidence=round(min(0.75, max(0.25, score)), 2),
    )


def build_tasks_payload(
    items: list[MatchItem],
    candidates_by_item: dict[str, list[LentaProduct]],
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        candidates = []
        for product in candidates_by_item.get(item.id, []):
            candidates.append({
                "id": product.id,
                "name": product.name.replace("&nbsp;", " "),
                "price_rub": product.price,
                "price_per_kg": product.pricePerKg,
                "weight_g": product.weight_g(),
                "package": product.package,
                "stock": product.stock,
                "rating": product.rating,
                "brand": product.brand,
            })
        payload.append({
            "task_index": index,
            "name": item.name,
            "suggested_quantity": item.quantity,
            "suggested_unit": item.unit,
            "piece_weight_g": item.piece_weight_g,
            "sku_hint": item.sku_hint,
            "notes": (item.notes or "")[:300],
            "candidates": candidates,
        })
    return payload


def _map_batch(
    batch: BatchPick,
    task_map: dict[int, MatchItem],
) -> dict[str, ProductPick]:
    out: dict[str, ProductPick] = {}
    seen: set[int] = set()
    for result in batch.items:
        if result.task_index not in task_map or result.task_index in seen:
            continue
        seen.add(result.task_index)
        item = task_map[result.task_index]
        out[item.id] = ProductPick(
            product_id=result.product_id,
            packages=max(0.01, min(100.0, result.packages or 1.0)),
            reason=(result.reason or "")[:2000],
            confidence=min(max(result.confidence, 0.0), 1.0),
        )
    for index, item in task_map.items():
        if index not in seen:
            out[item.id] = ProductPick(
                product_id=0,
                reason="missing_from_batch_response",
            )
    return out


async def pick_batch(
    *,
    user_id: str,
    items: list[MatchItem],
    candidates_by_item: dict[str, list[LentaProduct]],
    batch_size: int = 10,
) -> dict[str, ProductPick]:
    picks: dict[str, ProductPick] = {}
    for start in range(0, len(items), batch_size):
        chunk = items[start:start + batch_size]
        task_map = {index: item for index, item in enumerate(chunk, start=1)}
        tasks = build_tasks_payload(chunk, candidates_by_item)
        try:
            text, provider = await asyncio.wait_for(
                call_llm_cascade(
                    user_id=user_id,
                    prompt=json.dumps(tasks, ensure_ascii=False),
                    system=SYSTEM_PROMPT,
                    max_tokens=8192,
                    temperature=0.1,
                ),
                timeout=LENTA_LLM_TIMEOUT,
            )
            batch = BatchPick.model_validate(_extract_json(text))
            chunk_picks = _map_batch(batch, task_map)
            matched = sum(1 for p in chunk_picks.values() if p.product_id)
            print(
                f"[lenta] LLM match: provider={provider} "
                f"chunk={len(chunk)} matched={matched}"
            )
            picks.update(chunk_picks)
        except Exception as exc:  # noqa: BLE001
            print(f"[lenta] LLM match failed: {type(exc).__name__}: {exc}")
            for item in chunk:
                picks[item.id] = _fallback_pick(
                    item, candidates_by_item.get(item.id, [])
                )
    return picks
