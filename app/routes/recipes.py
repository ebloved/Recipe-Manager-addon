"""CRUD рецептов + экспорт/импорт .md.

Изменения относительно предыдущей версии:
  - В `POST /api/recipes` и `PUT /{id}/import-md` после парсинга Markdown
    вызывается `link_recipe_ingredients()` — блоки `product.barcode/uuid`
    из front matter превращаются в `product_id` из базы продуктов.
  - Эндпоинт `POST /api/recipes/import-url` УБРАН отсюда — он переехал
    в `routes/imports.py` (вместе с `import-text` и `import-batch`).
  - Эндпоинт `GET /api/tags` тоже в `imports.py` — здесь его больше нет,
    чтобы не было двойной регистрации.
  - Всё, что касается парсинга и массового импорта, живёт в imports.py;
    recipes.py отвечает только за CRUD над уже сохранёнными рецептами
    и за экспорт/импорт отдельного рецепта.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from config import AUTH_MODE
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response

from recipe_manager.importer import parse_markdown_recipe
from services.active_time import estimate_active_time
from services.equipment_adapter import adapt_recipe_to_airfryer
from recipe_manager.importer import parse_markdown_recipe
from services.linker import link_recipe_ingredients
from services.md_export import recipe_filename, recipe_to_md
from stores import meal_plan_store, recipe_store
from services.auth import get_current_user
from services.auth import users_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


async def _maybe_estimate_active_time(recipe: dict, force: bool = False) -> dict:
    """Оценивает active_time и возвращает patch. При ошибке — {active_time_error}."""
    try:
        return await estimate_active_time(recipe, force=force)
    except Exception as e:  # noqa: BLE001
        logger.warning("active_time estimation crashed: %s", exc)
        return {"active_time_error": str(exc)[:200]}


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------

@router.get("")
async def list_recipes(request: Request, q: str | None = None, show_hidden: bool = False):
    """Возвращает список рецептов с опциональным поиском."""
    user = get_current_user(request)
    uid = user["id"] if user else None
    items = [r for r in recipe_store.get_all() if show_hidden or uid not in (r.get("hidden_by") or [])]

    if q:
        lower = q.strip().lower()

        def matches(r: dict[str, Any]) -> bool:
            if lower in (r.get("name") or "").lower():
                return True
            if lower in (r.get("description") or "").lower():
                return True
            for key in ("tags", "courses", "categories", "collections"):
                for v in r.get(key) or []:
                    if isinstance(v, str) and lower in v.lower():
                        return True
            for ing in r.get("ingredients") or []:
                name = ing.get("name") if isinstance(ing, dict) else str(ing)
                if name and lower in str(name).lower():
                    return True
            return False

        items = [r for r in items if matches(r)]

    return {"recipes": items, "count": len(items)}


@router.get("/{recipe_id}")
async def get_recipe(recipe_id: str):
    """Возвращает один рецепт по id."""
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    return {"recipe": recipe}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@router.post("")
async def create_recipe(request: Request, payload: dict[str, Any] = Body(...)):
    user = get_current_user(request)
    """Создаёт рецепт.

    Два режима:
      - markdown_content задан → парсим Markdown, линкуем ингредиенты,
        мержим с явными полями (явные имеют приоритет).
      - markdown_content нет → создаём из явных полей (name обязателен).
    """
    md = payload.get("markdown_content")
    explicit = {k: v for k, v in payload.items() if k != "markdown_content"}

    if md:
        try:
            parsed = parse_markdown_recipe(md)
        except ValueError as exc:
            raise HTTPException(400, f"markdown_parse_failed: {exc}") from exc

        # Связываем product.barcode/uuid с реальными product_id из store
        try:
            parsed = await link_recipe_ingredients(parsed)
        except Exception as e:  # noqa: BLE001
            logger.warning("Linker упал при создании из Markdown: %s", exc)

        # Убираем служебную статистику перед сохранением
        parsed.pop("_linker_stats", None)

        data = {**parsed, **explicit}
    else:
        if not explicit.get("name"):
            raise HTTPException(400, "Either 'name' or 'markdown_content' is required")

        # Если среди явных полей есть ingredients с product-блоками —
        # прогоним их через линкер тоже.
        if isinstance(explicit.get("ingredients"), list):
            wrapper = {"name": explicit["name"], "ingredients": explicit["ingredients"]}
            try:
                wrapper = await link_recipe_ingredients(wrapper)
                explicit["ingredients"] = wrapper.get("ingredients", explicit["ingredients"])
            except Exception as e:  # noqa: BLE001
                logger.warning("Linker упал при создании из явных полей: %s", exc)

        data = explicit

    if user:
        data["owner_id"] = user["id"]
        data["owner_name"] = user.get("name", "User")
    recipe = await recipe_store.add(data)

    # B1: оценить active_time через LLM (graceful — рецепт уже сохранён)
    patch = await _maybe_estimate_active_time(recipe)
    if patch:
        updated = await recipe_store.update(recipe["id"], patch)
        if updated:
            recipe = updated

    return {"recipe": recipe}


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

@router.patch("/{recipe_id}")
async def update_recipe(recipe_id: str, request: Request, patch: dict[str, Any] = Body(...)):
    """Обновляет рецепт частично."""
    user = get_current_user(request)
    existing = recipe_store.get(recipe_id)
    if not existing:
        raise HTTPException(404, "Recipe not found")
    
    # Проверка прав (если не админ и не владелец)
    if user and user["role"] != "admin" and existing.get("owner_id") and existing.get("owner_id") != user["id"]:
        raise HTTPException(403, "Только автор может редактировать (сделайте копию)")

    if isinstance(patch.get("ingredients"), list):
        wrapper = {
            "name": patch.get("name") or existing.get("name"),
            "ingredients": patch["ingredients"],
        }
        try:
            wrapper = await link_recipe_ingredients(wrapper)
            patch = {**patch, "ingredients": wrapper.get("ingredients", patch["ingredients"])}
        except Exception as e:  # noqa: BLE001
            logger.warning("Linker упал при обновлении рецепта: %s", exc)

    recipe = await recipe_store.update(recipe_id, patch)
    if not recipe:
        raise HTTPException(404, "Recipe not found")

    # B1: пересчитать active_time если instructions изменились
    # (estimate_active_time сам проверяет hash — если не менялись, вернёт {})
    if "instructions" in patch:
        at_patch = await _maybe_estimate_active_time(recipe)
        if at_patch:
            updated = await recipe_store.update(recipe_id, at_patch)
            if updated:
                recipe = updated

    return {"recipe": recipe}


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.post("/{recipe_id}/hide")
async def hide_recipe(recipe_id: str, request: Request):
    user = get_current_user(request)
    if not user: raise HTTPException(401, "Auth required")
    recipe = recipe_store.get(recipe_id)
    if not recipe: raise HTTPException(404, "Not found")
    hidden = recipe.get("hidden_by") or []
    if user["id"] not in hidden:
        hidden.append(user["id"])
        await recipe_store.update(recipe_id, {"hidden_by": hidden})
    return {"status": "ok"}

@router.post("/{recipe_id}/unhide")
async def unhide_recipe(recipe_id: str, request: Request):
    user = get_current_user(request)
    if not user: raise HTTPException(401, "Auth required")
    recipe = recipe_store.get(recipe_id)
    if not recipe: raise HTTPException(404, "Not found")
    hidden = recipe.get("hidden_by") or []
    if user["id"] in hidden:
        hidden.remove(user["id"])
        await recipe_store.update(recipe_id, {"hidden_by": hidden})
    return {"status": "ok"}

@router.post("/{recipe_id}/fork")
async def fork_recipe(recipe_id: str, request: Request):
    user = get_current_user(request)
    if not user: raise HTTPException(401, "Auth required")
    original = recipe_store.get(recipe_id)
    if not original: raise HTTPException(404, "Not found")
    new_r = {**original}
    new_r["id"] = uuid.uuid4().hex
    new_r["name"] = f"{original.get('name')} (копия)"
    new_r["owner_id"] = user["id"]
    new_r["owner_name"] = user.get("name", "User")
    new_r["hidden_by"] = []
    new_r["parent_id"] = original["id"]
    created = await recipe_store.add(new_r)
    return {"recipe": created}

@router.delete("/{recipe_id}")
async def delete_recipe(recipe_id: str, request: Request):
    """Удаляет рецепт и связанные записи плана питания."""
    user = get_current_user(request)
    existing = recipe_store.get(recipe_id)
    if not existing: raise HTTPException(404, "Recipe not found")
    
    if user and user["role"] != "admin" and existing.get("owner_id") and existing.get("owner_id") != user["id"]:
        raise HTTPException(403, "Только автор или админ может удалить")
        
    # Чистим ссылку в родительском рецепте, если это была адаптация/форк
    parent_id = existing.get("parent_id")
    if parent_id:
        parent = recipe_store.get(parent_id)
        if parent and parent.get("adapted_versions"):
            adapted = parent["adapted_versions"]
            for k, v in list(adapted.items()):
                if v == recipe_id:
                    del adapted[k]
            await recipe_store.update(parent_id, {"adapted_versions": adapted})

    ok = await recipe_store.delete(recipe_id)
    if not ok:
        raise HTTPException(404, "Recipe not found")
    removed = await meal_plan_store.delete_by_recipe(recipe_id)
    return {"deleted": True, "meal_plan_entries_removed": removed}


# ---------------------------------------------------------------------------
# Export to Markdown
# ---------------------------------------------------------------------------

@router.get("/{recipe_id}/export.md")
async def export_recipe_md(recipe_id: str):
    """Отдаёт .md файл с рецептом.

    Формат имени: <transliterated-slug>_<8-символов-id>.md
    Содержимое: YAML front matter + тело, включая блоки product.barcode
    для связанных ингредиентов (см. services/md_export.py).
    """
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")

    md = recipe_to_md(recipe)
    filename = recipe_filename(recipe)

    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Import from Markdown (replace existing recipe)
# ---------------------------------------------------------------------------

@router.put("/{recipe_id}/import-md")
async def import_recipe_md(recipe_id: str, payload: dict[str, Any] = Body(...)):
    """Заменяет поля существующего рецепта содержимым Markdown.

    Payload: {"markdown_content": "..."}

    Сохраняет `id` и `created_at` исходного рецепта.
    Ингредиенты линкуются через linker (обрабатывает product.barcode/uuid).
    """
    md = payload.get("markdown_content")
    if not md or not isinstance(md, str):
        raise HTTPException(400, "'markdown_content' is required")

    existing = recipe_store.get(recipe_id)
    if not existing:
        raise HTTPException(404, "Recipe not found")

    try:
        parsed = parse_markdown_recipe(md)
    except ValueError as exc:
        raise HTTPException(400, f"markdown_parse_failed: {exc}") from exc

    # Связываем продукт-блоки с product_id
    try:
        parsed = await link_recipe_ingredients(parsed)
    except Exception as e:  # noqa: BLE001
        logger.warning("Linker упал при import-md: %s", exc)

    parsed.pop("_linker_stats", None)

    # Сохраняем неизменяемые поля
    parsed["id"] = existing.get("id")
    parsed["created_at"] = existing.get("created_at")

    updated = await recipe_store.update(recipe_id, parsed)
    if not updated:
        raise HTTPException(404, "Recipe not found")

    # B1: пересчитать active_time после замены содержимого
    at_patch = await _maybe_estimate_active_time(updated)
    if at_patch:
        updated2 = await recipe_store.update(recipe_id, at_patch)
        if updated2:
            updated = updated2

    return {"recipe": updated}


# ---------------------------------------------------------------------------
# Import from Markdown (create new — короткий алиас для recipe_store.add)
# ---------------------------------------------------------------------------

@router.post("/-/from-markdown")
async def create_from_markdown(payload: dict[str, Any] = Body(...)):
    """Создаёт новый рецепт из Markdown.

    Отличие от POST /api/recipes с markdown_content:
      - всегда создаёт новый рецепт (не мержит с явными полями),
      - не принимает дополнительных полей — только markdown_content.

    Удобно для быстрых интеграций и скриптов.
    """
    md = payload.get("markdown_content")
    if not md or not isinstance(md, str):
        raise HTTPException(400, "'markdown_content' is required")

    try:
        parsed = parse_markdown_recipe(md)
    except ValueError as exc:
        raise HTTPException(400, f"markdown_parse_failed: {exc}") from exc

    try:
        parsed = await link_recipe_ingredients(parsed)
    except Exception as e:  # noqa: BLE001
        logger.warning("Linker упал при create-from-markdown: %s", exc)

    parsed.pop("_linker_stats", None)

    recipe = await recipe_store.add(parsed)
    return {"recipe": recipe}

# ---------------------------------------------------------------------------
# Batch estimate active_time
# ---------------------------------------------------------------------------

@router.post("/{recipe_id}/estimate-active-time", status_code=202)
async def estimate_one_active_time(recipe_id: str, force: bool = True):
    """Запускает оценку active_time одного рецепта в фоне (job-based).

    Sync-версия падала по nginx-таймауту (~60s), если Gemini думал дольше.
    Теперь 202 {job_id}, фронт поллит /api/generator/jobs/{id}.

    force=True по умолчанию — пересчитать даже если hash совпадает.
    """
    import asyncio
    from services.generator.generator import _now
    from stores import jobs_store

    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")

    job = await jobs_store.create({
        "kind": "estimate_active_time_one",
        "recipe_id": recipe_id,
        "force": force,
    })
    asyncio.create_task(_run_estimate_one_job(job["id"], recipe_id, force=force))
    return {"job_id": job["id"], "status": "pending"}


async def _run_estimate_one_job(job_id: str, recipe_id: str, *, force: bool = True):
    import time
    from services.generator.generator import _now
    from stores import jobs_store

    from services.telegram_service import telegram_service
    t0 = time.monotonic()
    await telegram_service.send(f"♨️ <b>Начата адаптация под аэрогриль</b>\nJob ID: <code>{job_id}</code>\nРецепт: {recipe_id}")
    try:
        recipe = recipe_store.get(recipe_id)
        if not recipe:
            await jobs_store.update(
                job_id, status="error", error="recipe not found",
                finished_at=_now(),
            )
            return
        patch = await _maybe_estimate_active_time(recipe, force=force)
        if not patch:
            await jobs_store.update(
                job_id, status="done", created=0, finished_at=_now(),
            )
            logger.info(
                "[active_time] one %s: no change (%.1fs)",
                recipe_id[:8], time.monotonic() - t0,
            )
            return
        await recipe_store.update(recipe_id, patch)
        at_err = patch.get("active_time_error")
        if at_err:
            await jobs_store.update(
                job_id, status="error", error=str(at_err)[:200],
                finished_at=_now(),
            )
        else:
            await jobs_store.update(
                job_id, status="done", created=1, finished_at=_now(),
            )
        logger.info(
            "[active_time] one %s done in %.1fs: active=%s",
            recipe_id[:8], time.monotonic() - t0, patch.get("active_time"),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("[active_time] one job crashed")
        await jobs_store.update(
            job_id, status="error", error=str(exc)[:200], finished_at=_now(),
        )


@router.post("/estimate-active-time")
async def estimate_all_active_time(force: bool = False):
    """Запускает фоновую переоценку active_time для всех рецептов.

    Возвращает job_id (async через JobsStore). Клиент поллит
    GET /api/generator/jobs/{id} или /api/jobs/{id}.

    force=True — пересчитать даже если hash не изменился.
    """
    import asyncio
    from services.generator.generator import _now
    from stores import jobs_store

    job = await jobs_store.create({"kind": "estimate_active_time", "force": force})
    asyncio.create_task(_run_estimate_job(job["id"], force=force))
    return {"job_id": job["id"], "status": "pending"}


async def _run_estimate_job(job_id: str, *, force: bool = False):
    import time
    from services.generator.generator import _now
    from stores import jobs_store

    t0 = time.monotonic()
    try:
        recipes = recipe_store.get_all()
        total = len(recipes)
        done = 0
        errors = 0
        skipped = 0
        for r in recipes:
            try:
                patch = await estimate_active_time(r, force=force)
                if not patch:
                    skipped += 1
                    done += 1
                elif patch.get("active_time_error"):
                    await recipe_store.update(r["id"], patch)
                    errors += 1
                    done += 1
                else:
                    await recipe_store.update(r["id"], patch)
                    done += 1
                await jobs_store.update(job_id, created=done)
            except Exception as e:  # noqa: BLE001
                logger.warning("estimate failed for %s: %s", r.get("id"), exc)
                errors += 1
                done += 1
        elapsed = round(time.monotonic() - t0, 2)
        err_msg = None
        if errors:
            err_msg = f"{errors} ошибок из {total}"
        await jobs_store.update(
            job_id, status="done", created=done,
            finished_at=_now(),
            error=err_msg,
        )
        logger.info(
            "[active_time] batch done in %.1fs: %d/%d ok, %d skipped, %d errors",
            elapsed, done, total, skipped, errors,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("active_time batch crashed")
        await jobs_store.update(
            job_id, status="error", error=str(exc)[:200], finished_at=_now(),
        )


def _require_auth(request: Request):
    if AUTH_MODE == "oauth":
        session_id = request.cookies.get("rm_session")
        if not session_id or session_id not in users_store.users:
            raise HTTPException(401, "Unauthorized")

@router.post("/{recipe_id}/adapt-to-airfryer", status_code=202)
async def adapt_to_airfryer(recipe_id: str, request: Request):
    _require_auth(request)
    user = get_current_user(request)
    """Запускает фоновую адаптацию рецепта под аэрогриль."""
    import asyncio
    from stores import jobs_store
    from services.generator.generator import _now, _pick_samples
    
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
        
    job = await jobs_store.create({"kind": "adapt_airfryer", "recipe_id": recipe_id})
    asyncio.create_task(_run_adapt_job(job["id"], recipe, user["id"] if user else "family"))
    return {"job_id": job["id"], "status": "pending"}

async def _run_adapt_job(job_id: str, recipe: dict, job_id_user: str):
    import time
    from stores import jobs_store
    from services.generator.generator import _now
    from services.telegram_service import telegram_service
    
    t0 = time.monotonic()
    try:
        msg = f"""♨️ <b>Начата адаптация под аэрогриль</b>
Job ID: <code>{job_id}</code>
Рецепт: {recipe.get('name')}"""
        await telegram_service.send(msg)
        
        adapt_data = await adapt_recipe_to_airfryer(recipe, job_id=job_id, user_id=job_id_user)
        
        new_recipe = {**recipe}
        new_recipe["id"] = uuid.uuid4().hex
        new_recipe["name"] = f"{recipe.get('name')} (аэрогриль)"
        new_recipe["instructions"] = adapt_data.get("instructions", recipe.get("instructions"))
        if adapt_data.get("cook_time"):
            new_recipe["cook_time"] = adapt_data["cook_time"]
        if adapt_data.get("total_time"):
            new_recipe["total_time"] = adapt_data["total_time"]
            
        new_recipe["equipment"] = ["airfryer"]
        new_recipe["parent_id"] = recipe.get("id")
        new_recipe.pop("share_token", None)
        new_recipe.pop("adapted_versions", None)
            
        created = await recipe_store.add(new_recipe)
        
        parent = recipe_store.get(recipe["id"])
        adapted = parent.get("adapted_versions", {})
        adapted["airfryer"] = created["id"]
        await recipe_store.update(parent["id"], {"adapted_versions": adapted})
        
        await jobs_store.update(job_id, status="done", created=1, finished_at=_now())
        
        msg2 = f"""✅ <b>Адаптация завершена</b>
Job ID: <code>{job_id}</code>"""
        await telegram_service.send(msg2)
        
        logger.info(f"[adapter] job {job_id} done in {time.monotonic()-t0:.1f}s")
    except Exception as e:
        logger.exception(f"[adapter] job failed")
        await jobs_store.update(job_id, status="error", error=str(e), finished_at=_now())
        
        msg3 = f"""❌ <b>Ошибка адаптации</b>
Job ID: <code>{job_id}</code>
{str(e)}"""
        await telegram_service.send(msg3)
