"""Обратная связь от сервиса покупок: отметить/удалить купленное."""
from __future__ import annotations

from typing import Any

from services.shopping_normalizer import normalize_for_connector
from stores import shopping_store

_ALLOWED_ACTIONS = {"check", "delete"}


def _matches(owner_id: str, item: dict[str, Any]) -> list[dict[str, Any]]:
    all_items = shopping_store.get_all(owner_id)
    targets: dict[str, dict[str, Any]] = {}

    shopping_item_id = str(item.get("shopping_item_id") or "").strip()
    if shopping_item_id:
        found = shopping_store.get(shopping_item_id)
        if found and found.get("owner_id") == owner_id:
            targets[found["id"]] = found

    product_id = str(item.get("product_id") or "").strip()
    if product_id:
        for candidate in all_items:
            if str(candidate.get("product_id") or "") == product_id:
                targets[candidate["id"]] = candidate

    barcode = str(item.get("barcode") or item.get("gtin") or "").strip()
    if barcode:
        for candidate in all_items:
            if str(candidate.get("barcode") or "") == barcode:
                targets[candidate["id"]] = candidate

    name = str(item.get("name") or "").strip()
    if name and not targets:
        exact = shopping_store.find_by_name(name, owner_id)
        if exact:
            targets[exact["id"]] = exact
        else:
            needle = normalize_for_connector(name)
            for candidate in all_items:
                if normalize_for_connector(candidate.get("name") or "") == needle:
                    targets[candidate["id"]] = candidate

    return list(targets.values())


async def apply_purchase_feedback(
    owner_id: str,
    items: list[dict[str, Any]],
    *,
    mode: str = "check",
) -> dict[str, Any]:
    default_action = mode if mode in _ALLOWED_ACTIONS else "check"
    checked = 0
    deleted = 0
    already_checked = 0
    skipped = 0
    matched: list[dict[str, Any]] = []
    not_found: list[dict[str, Any]] = []

    for raw in items:
        if not isinstance(raw, dict):
            continue
        if raw.get("purchased") is False:
            skipped += 1
            continue
        action = str(raw.get("action") or default_action).strip().lower()
        if action not in _ALLOWED_ACTIONS:
            action = default_action
        targets = _matches(owner_id, raw)
        if not targets:
            not_found.append({
                "shopping_item_id": raw.get("shopping_item_id"),
                "name": raw.get("name"),
                "barcode": raw.get("barcode"),
                "reason": "not_found",
            })
            continue
        for target in targets:
            if action == "delete":
                ok = await shopping_store.delete(target["id"], owner_id)
                if ok:
                    deleted += 1
                    matched.append({
                        "shopping_item_id": target["id"],
                        "name": target.get("name"),
                        "action": "deleted",
                    })
                continue
            if target.get("checked"):
                already_checked += 1
                matched.append({
                    "shopping_item_id": target["id"],
                    "name": target.get("name"),
                    "action": "already_checked",
                })
                continue
            updated = await shopping_store.update(
                target["id"], owner_id, {"checked": True}
            )
            if updated:
                checked += 1
                matched.append({
                    "shopping_item_id": target["id"],
                    "name": target.get("name"),
                    "action": "checked",
                })

    return {
        "checked": checked,
        "deleted": deleted,
        "already_checked": already_checked,
        "skipped": skipped,
        "matched": matched,
        "not_found": not_found,
    }
