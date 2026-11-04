"""LLM-матчинг позиций списка покупок с товарами ВкусВилла.

Использует общий каскад RM: Custom -> Orca -> Gemini -> admin Gemini -> Hermes.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from config import VKUSVILL_LLM_TIMEOUT
from integrations.stores.vkusvill.models import (
    BatchPick,
    MatchItem,
    ProductPick,
    VVProduct,
)
from integrations.stores.vkusvill.models import VVWeight
from services.llm_cascade import call_llm_cascade

SYSTEM_PROMPT = """\
Ты — эксперт по ассортименту магазина ВкусВилл.
На вход подаётся массив задач (JSON). Каждая задача содержит:
  task_index        — числовой номер (1..N), НЕ МЕНЯЙ его
  name              — название ингредиента
  suggested_quantity — сколько нужно купить (УЖЕ сконвертировано Recipe Manager)
  suggested_unit    — единица: "г", "мл", "шт" (иногда "кг", "л")
  piece_weight_g    — вес 1 шт в граммах (для штучных), иначе null
  sku_hint          — необязательные подсказки: barcode / brand / name
  notes             — заметка пользователя (может влиять на выбор)
  candidates        — товары ВкусВилл: id / name / unit / weight_g /
                      price_rub / price_per_kg / rating

Для КАЖДОЙ задачи верни РОВНО ОДИН элемент в items ответа.
Количество элементов items ДОЛЖНО совпадать с количеством задач.

КРИТИЧНО: не конвертируй units. Recipe Manager уже всё сконвертировал.

1) product_id — id наиболее подходящего кандидата.
   Критерии: базовый тип продукта, бренд из sku_hint.brand, объём/вес,
   notes, рейтинг. Если ничего не подходит — product_id = 0.
   Используй ТОЛЬКО id из candidates. Никогда не выдумывай id.

   Если suggested_unit — "г", "кг", "мл" или "л":
   - сначала рассмотри ВЕСОВЫЕ товары (unit = "кг" или "л", weight_g = null):
     они продаются на развес и обычно дешевле за килограмм;
   - упакованный товар выбирай, только если весового аналога нет
     или в notes явно указана упаковка/бренд;
   - сравнивай price_per_kg (₽ за кг/л), а не цену упаковки:
     у упакованного price_rub — это цена за пачку, её нельзя сравнивать
     с ценой весового товара напрямую.
   Для штучных ингредиентов ("шт") это правило не применяется.

   Соответствия ВкусВилла:
   - «белый хлеб», «хлеб без корки», «батон» → «Батон нарезной» (это белый хлеб);
   - «тостовый» → тостовый хлеб (например, Harrys);
   - «цельнозерновой»/«зерновой» → цельнозерновой/зерновой хлеб.
   Если точного товара нет, но есть явный эквивалент из этого списка —
   выбирай его, не возвращай 0.

2) packages — сколько УПАКОВОК купить (0.01..40).
   Всегда округляй ВВЕРХ.
   - "г"/"кг" → base в граммах; packages = ceil(base / weight_g)
   - "мл"/"л" → base в мл; packages = ceil(base / weight_g)
   - "шт" → packages = suggested_quantity
   Если weight_g неизвестен — packages = 1, confidence = 0.5.

3) reason — краткая строка (≤200 символов), не JSON.
4) confidence — 0..1.

Формат ответа — строго JSON вида {"items": [ {...}, {...} ]}."""


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _weight_to_grams(weight: VVWeight | float | None) -> float | None:
    if weight is None:
        return None
    if isinstance(weight, VVWeight):
        return weight.to_grams()
    if isinstance(weight, (int, float)):
        return float(weight)
    return None


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


def build_tasks_payload(
    items: list[MatchItem],
    candidates_by_item: dict[str, list[VVProduct]],
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        candidates = []
        for product in candidates_by_item.get(item.id, []):
            price = product.price.current if product.price else None
            unit = (product.unit or "").strip().lower()
            weight_g = _weight_to_grams(product.weight)
            price_per_kg = None
            if price is not None:
                if unit in ("кг", "kg", "л", "l"):
                    price_per_kg = price
                elif weight_g:
                    price_per_kg = round(price * 1000.0 / weight_g, 2)
            candidates.append({
                "id": product.id,
                "name": product.name.replace("&nbsp;", " "),
                "unit": product.unit,
                "price_rub": price,
                "price_per_kg": price_per_kg,
                "weight_g": weight_g,
                "rating": product.rating.average if product.rating else None,
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
        packages = result.packages
        if result.product_id > 0:
            packages = max(1.0, min(40.0, packages if packages > 0 else 1.0))
        else:
            packages = 1.0
        out[item.id] = ProductPick(
            product_id=result.product_id,
            packages=packages,
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
    candidates_by_item: dict[str, list[VVProduct]],
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
                timeout=VKUSVILL_LLM_TIMEOUT,
            )
            batch = BatchPick.model_validate(_extract_json(text))
            chunk_picks = _map_batch(batch, task_map)
            matched = sum(1 for p in chunk_picks.values() if p.product_id)
            print(
                f"[vkusvill] LLM match: provider={provider} "
                f"chunk={len(chunk)} matched={matched}"
            )
            picks.update(chunk_picks)
        except Exception as exc:  # noqa: BLE001
            print(f"[vkusvill] LLM match failed: {type(exc).__name__}: {exc}")
            for item in chunk:
                picks[item.id] = ProductPick(
                    product_id=0,
                    reason=f"llm_failed:{type(exc).__name__}",
                )
    return picks
