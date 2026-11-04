"""Фоновая нормализация рецептов.

Раз в N секунд берёт один рецепт, приводит к стандарту и сохраняет патч.
LLM-обогащение (product links, active_time) — опционально.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from config import (
    RECIPE_ENRICHER_ENABLED,
    RECIPE_NORMALIZER_ENABLED,
    RECIPE_NORMALIZER_INTERVAL,
    RECIPE_NORMALIZER_START_DELAY,
)
from services import audit
from services.activity import is_active
from services.background_gate import background_task
from services.recipe_enricher import enrich_recipe
from services.recipe_linter import summarize
from services.recipe_normalizer import needs_normalization, normalize_recipe
from services.recipe_standard import source_hash
from stores import recipe_store

PATCH_FIELDS = {
    "name", "description", "ingredients", "instructions",
    "prep_time", "cook_time", "total_time",
    "servings", "servings_text",
    "tags", "courses", "categories", "collections",
    "cuisine", "category", "nutrition", "notes",
    "schema_version", "normalized_at", "normalization_hash",
    "normalization_issues", "normalization_status", "normalization_error",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status(issues: list[dict[str, Any]]) -> str:
    severities = {i.get("severity") for i in issues}
    return "issues" if severities & {"error", "warning"} else "ok"


async def _normalize_one(recipe: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_recipe(recipe)
    if RECIPE_ENRICHER_ENABLED:
        enriched, enrich_issues = await enrich_recipe(normalized)
        normalized = enriched
        issues = list(normalized.get("normalization_issues") or []) + enrich_issues
        normalized["normalization_issues"] = issues
        normalized["normalization_hash"] = source_hash(normalized)
        normalized["normalized_at"] = _now()
        normalized["normalization_status"] = _status(issues)
    return normalized


async def recipe_normalizer_worker() -> None:
    if not RECIPE_NORMALIZER_ENABLED:
        print("[normalizer] disabled")
        return

    await asyncio.sleep(RECIPE_NORMALIZER_START_DELAY)
    print(
        f"[normalizer] started (enricher={RECIPE_ENRICHER_ENABLED}, "
        f"interval={RECIPE_NORMALIZER_INTERVAL}s)"
    )

    while True:
        try:
            if is_active(1800):
                await asyncio.sleep(300)
                continue

            candidates = [
                r for r in recipe_store.get_all()
                if needs_normalization(r)
            ]
            if not candidates:
                await asyncio.sleep(RECIPE_NORMALIZER_INTERVAL)
                continue

            recipe = candidates[0]
            recipe_id = recipe.get("id")
            base_hash = source_hash(recipe)
            try:
                async with background_task("recipe_normalizer"):
                    normalized = await _normalize_one(recipe)
                    patch = {k: normalized[k] for k in PATCH_FIELDS if k in normalized}
                    updated = await recipe_store.patch_if_unchanged(
                        recipe_id, base_hash, patch,
                    )
                    if updated is None:
                        print(f"[normalizer] skip {str(recipe_id)[:8]} (changed during normalization)")
                        await audit.log_event(
                            action="automation.recipe_normalizer",
                            label="Нормализация рецепта",
                            target_type="recipe",
                            target_id=str(recipe_id),
                            target_name=recipe.get("name"),
                            status="ok",
                            details={"skipped": "changed_during_normalization"},
                        )
                    else:
                        issues = normalized.get("normalization_issues") or []
                        print(
                            f"[normalizer] {str(recipe_id)[:8]} "
                            f"{recipe.get('name')!r} -> {normalized.get('normalization_status')} "
                            f"{summarize(issues)}"
                        )
                        await audit.log_event(
                            action="automation.recipe_normalizer",
                            label="Нормализация рецепта",
                            target_type="recipe",
                            target_id=str(recipe_id),
                            target_name=recipe.get("name"),
                            status="ok",
                            details={
                                "normalization_status": normalized.get("normalization_status"),
                                "issues": summarize(issues),
                            },
                        )
            except Exception as exc:  # noqa: BLE001
                await audit.log_event(
                    action="automation.recipe_normalizer",
                    label="Нормализация рецепта",
                    target_type="recipe",
                    target_id=str(recipe_id),
                    target_name=recipe.get("name"),
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[normalizer] error: {type(exc).__name__}: {exc}")
            await asyncio.sleep(60)
