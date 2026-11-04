"""Offline-ответы BFF из cache.sqlite + постановка операций в очередь."""
from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from services import remote_cache
from recipe_manager.importer import parse_markdown_recipe


def _json(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=data)


def _offline_error(message: str = "Сервер недоступен. Действие требует соединения.") -> JSONResponse:
    return _json({"detail": message}, 503)


def _parse_body(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(body.decode("utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _match(recipe: dict[str, Any], query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return True
    if q in str(recipe.get("name") or "").lower():
        return True
    for ing in recipe.get("ingredients") or []:
        name = ing.get("name") if isinstance(ing, dict) else str(ing)
        if name and q in str(name).lower():
            return True
    return False


async def handle(request: Request, body: bytes) -> JSONResponse | None:
    method = request.method.upper()
    path = request.scope.get("path") or request.url.path

    if path == "/api/me" and method == "GET":
        me = remote_cache.get_me()
        return _json(me or {
            "authenticated": True,
            "name": "Offline",
            "id": "offline",
            "role": "user",
            "source": "cache",
        })

    if path == "/api/recipes":
        if method == "GET":
            items = remote_cache.recipes()
            if request.query_params.get("include_adapted") not in ("1", "true", "True"):
                sub_ids = set()
                for parent in items:
                    for child_id in (parent.get("adapted_versions") or {}).values():
                        if child_id:
                            sub_ids.add(str(child_id))
                items = [r for r in items if str(r.get("id")) not in sub_ids]
            q = request.query_params.get("q") or ""
            items = [r for r in items if _match(r, q)]
            return _json({"recipes": items, "count": len(items)})
        if method == "POST":
            data = _parse_body(body)
            md = data.get("markdown_content")
            explicit = {k: v for k, v in data.items() if k != "markdown_content"}
            if md:
                try:
                    parsed = parse_markdown_recipe(md)
                except ValueError as exc:
                    return _json({"detail": f"markdown_parse_failed: {exc}"}, 400)
                recipe = {**parsed, **explicit}
            else:
                if not explicit.get("name"):
                    return _json({"detail": "'name' is required"}, 400)
                recipe = explicit
            created = remote_cache.add_pending_recipe(recipe)
            return _json({"recipe": created})
        return _offline_error()

    if path.startswith("/api/recipes/"):
        recipe_id = path[len("/api/recipes/"):].strip("/")
        if not recipe_id:
            return _offline_error()
        if method == "GET":
            recipe = remote_cache.recipe(recipe_id)
            if not recipe:
                return _json({"detail": "Recipe not found"}, 404)
            return _json({"recipe": recipe})
        if method == "PATCH":
            updated = remote_cache.update_pending_recipe(recipe_id, _parse_body(body))
            if not updated:
                return _offline_error("Правка синхронизированного рецепта требует соединения.")
            return _json({"recipe": updated})
        if method == "DELETE":
            if remote_cache.delete_pending_recipe(recipe_id):
                return _json({"deleted": True, "meal_plan_entries_removed": 0})
            return _offline_error("Удаление синхронизированного рецепта требует соединения.")
        return _offline_error()

    if path == "/api/shopping":
        if method == "GET":
            items = remote_cache.shopping()
            only_active = request.query_params.get("only_active") in ("1", "true", "True")
            if only_active:
                items = [i for i in items if not i.get("checked")]
            return _json({
                "items": items,
                "count": len(items),
                "active": sum(1 for i in items if not i.get("checked")),
            })
        if method == "POST":
            data = _parse_body(body)
            if not str(data.get("name") or "").strip():
                return _json({"detail": "'name' is required"}, 400)
            item = remote_cache.add_pending_shopping(data)
            return _json({"item": item})
        return _offline_error()

    if path == "/api/shopping/checked" and method == "DELETE":
        removed = remote_cache.clear_pending_shopping(only_checked=True)
        return _json({"removed": removed})
    if path == "/api/shopping/all" and method == "DELETE":
        removed = remote_cache.clear_pending_shopping(only_checked=False)
        return _json({"removed": removed})

    if path.startswith("/api/shopping/"):
        rest = path[len("/api/shopping/"):].strip("/")
        if rest.endswith("/toggle") and method == "POST":
            item_id = rest[:-len("/toggle")].strip("/")
            current = next(
                (i for i in remote_cache.shopping() if str(i.get("id")) == item_id),
                None,
            )
            if not current:
                return _json({"detail": "Item not found"}, 404)
            updated = remote_cache.set_pending_checked(
                item_id, not bool(current.get("checked"))
            )
            return _json({"item": updated}) if updated else _json({"detail": "Item not found"}, 404)

        item_id = rest
        if method == "PATCH":
            patch = _parse_body(body)
            if set(patch.keys()) - {"checked"}:
                return _offline_error("Офлайн можно менять только отметку «куплено».")
            if "checked" not in patch:
                return _offline_error()
            updated = remote_cache.set_pending_checked(item_id, bool(patch["checked"]))
            return _json({"item": updated}) if updated else _json({"detail": "Item not found"}, 404)
        if method == "DELETE":
            if remote_cache.remove_pending_shopping(item_id):
                return _json({"deleted": True})
            return _json({"detail": "Item not found"}, 404)
        return _offline_error()

    return None
