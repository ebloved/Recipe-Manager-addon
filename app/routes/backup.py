"""API для управления rolling-бэкапами.

Эндпоинты:
    GET    /api/backup              — сводка + список бэкапов
    POST   /api/backup              — создать бэкап вручную
    POST   /api/backup/restore      — восстановить файлы из бэкапа
    DELETE /api/backup/{name}       — удалить бэкап
    POST   /api/backup/cleanup      — принудительная ротация старых
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from services.backup import backup_manager
from stores import (
    ingredients_store,
    meal_plan_store,
    recipe_store,
    shopping_store,
)

router = APIRouter(prefix="/api/backup", tags=["backup"])


# ---------------------------------------------------------------------------
# List / stats
# ---------------------------------------------------------------------------

@router.get("")
async def list_backups():
    """Возвращает сводку и список бэкапов (свежие первыми)."""
    return {
        "stats": backup_manager.stats(),
        "backups": backup_manager.list_backups(),
    }


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@router.post("")
async def create_backup(payload: dict[str, Any] = Body(default={})):
    """Создаёт бэкап вручную.

    Payload (опционально):
        message: str  — комментарий, попадёт в _meta.json

    Возвращает метаданные созданного бэкапа.
    """
    # Перед снимком убеждаемся, что все сторы записаны на диск.
    # В норме они сохраняются автоматически после каждой мутации,
    # но ручной бэкап — это тот случай, когда стоит подстраховаться.
    await recipe_store.save()
    await meal_plan_store.save()
    await shopping_store.save()
    await ingredients_store.save()

    meta = await backup_manager.make_backup(manual=True)

    message = (payload.get("message") or "").strip() if isinstance(payload, dict) else ""
    if message:
        # Просто добавляем в ответ — файл _meta.json уже записан.
        # Перезаписывать его ради одного поля не хочется.
        meta = {**meta, "message": message}

    return {"ok": True, "backup": meta}


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

@router.post("/restore")
async def restore_backup(payload: dict[str, Any] = Body(...)):
    """Восстанавливает файлы из бэкапа.

    Payload:
        name: str         — имя папки в /data/backups/
        files: list[str]  — какие файлы восстановить.
                            Если не указано — восстанавливаются все.

    Перед заменой делает pre-restore копию текущего состояния
    в /data/backups/_pre-restore_<name>/.

    После успешного восстановления перезагружает сторы в память.
    """
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "'name' is required")

    files = payload.get("files")
    if files is not None and not isinstance(files, list):
        raise HTTPException(400, "'files' must be a list or omitted")

    try:
        result = await backup_manager.restore(name, files=files)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    # Перезагружаем сторы, чтобы память соответствовала восстановленным файлам
    try:
        if not files or "recipes.json" in files:
            await recipe_store.load()
        if not files or "meal_plan.json" in files:
            await meal_plan_store.load()
        if not files or "shopping_list.json" in files:
            await shopping_store.load()
        if not files or "ingredients.json" in files:
            await ingredients_store.load()
    except Exception as exc:  # noqa: BLE001
        # Восстановление уже произошло — просто предупреждаем
        return {
            **result,
            "reload_warning": f"Файлы восстановлены, но перезагрузка в память упала: {exc}",
        }

    # Сбрасываем кэш cascade — данные изменились
    try:
        from services.matcher.cascade import invalidate_cache  # type: ignore[import]
        invalidate_cache()
    except Exception:  # noqa: BLE001
        pass

    return result


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/{name}")
async def delete_backup(name: str):
    """Удаляет папку бэкапа. `_pre-restore_*` удаляются так же, вручную."""
    try:
        ok = await backup_manager.delete(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not ok:
        raise HTTPException(404, "Backup not found")
    return {"deleted": True, "name": name}


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

@router.post("/cleanup")
async def cleanup_old():
    """Принудительно прогоняет ротацию (удаляет старше BACKUP_KEEP_DAYS)."""
    removed = await backup_manager._cleanup_old()  # noqa: SLF001 — внутренний метод, но нужен для ручного вызова
    return {"removed": removed}