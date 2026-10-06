"""Rolling-бэкапы JSON-файлов состояния.

Раз в BACKUP_INTERVAL_HOURS часов создаёт снимок всех данных:
    /data/backups/<YYYY-MM-DD>/
        ├── recipes.json
        ├── ingredients.json
        ├── meal_plan.json
        ├── shopping_list.json
        └── _meta.json

Хранит BACKUP_KEEP_DAYS последних дней. Старые удаляются автоматически.

Также умеет:
  - сделать ручной бэкап (с суффиксом HHMMSS, не конфликтует с авто)
  - вернуть список существующих бэкапов
  - восстановить файл из конкретного бэкапа

Особенности:
  - Ничего не грузит при импорте. Запуск — только через start_scheduler().
  - Не блокирует старт аддона: первый бэкап делается отложенно.
  - Всё файловое I/O через asyncio.to_thread — event loop не блокируется.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import aiofiles

from config import (
    BACKUP_DIR,
    BACKUP_ENABLED,
    BACKUP_INTERVAL_HOURS,
    BACKUP_KEEP_DAYS,
    DATA_DIR,
    MEAL_PLAN_FILE,
    RECIPES_FILE,
    SHOPPING_FILE,
    INGREDIENTS_FILE,
)

logger = logging.getLogger(__name__)


# Файлы, которые попадают в бэкап.
# Имя в архиве → абсолютный путь источника.
_BACKUP_FILES: dict[str, Path] = {
    "recipes.json": RECIPES_FILE,
    "ingredients.json": INGREDIENTS_FILE,
    "meal_plan.json": MEAL_PLAN_FILE,
    "shopping_list.json": SHOPPING_FILE,
}


class BackupManager:
    """Управляет rolling-бэкапами."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Жизненный цикл
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Запускает фоновую задачу. Идемпотентно."""
        if not BACKUP_ENABLED:
            logger.info("Backup отключён в конфиге")
            return
        if self._task is not None and not self._task.done():
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="backup-scheduler")
        logger.info(
            "Backup scheduler запущен (интервал %d ч, храним %d дней)",
            BACKUP_INTERVAL_HOURS, BACKUP_KEEP_DAYS,
        )

    async def stop(self) -> None:
        """Останавливает фоновую задачу."""
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            self._task.cancel()
        self._task = None
        logger.info("Backup scheduler остановлен")

    async def _run_loop(self) -> None:
        """Основной цикл: спит, просыпается, делает бэкап."""
        # Первый бэкап — не сразу, а через 60 секунд после старта,
        # чтобы не конкурировать с инициализацией stores.
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=60.0)
            return  # stop был вызван
        except asyncio.TimeoutError:
            pass

        while not self._stop_event.is_set():
            try:
                await self._auto_backup_if_needed()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Авто-бэкап упал: %s", exc)

            # Спим до следующего тика или до stop()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=BACKUP_INTERVAL_HOURS * 3600,
                )
                return  # stop
            except asyncio.TimeoutError:
                continue

    # ------------------------------------------------------------------
    # Авто-бэкап
    # ------------------------------------------------------------------

    async def _auto_backup_if_needed(self) -> None:
        """Делает бэкап, если за сегодня его ещё нет."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        target_dir = BACKUP_DIR / today

        if target_dir.exists():
            logger.debug("Бэкап за %s уже существует, пропускаем", today)
            # Заодно почистим старые
            await self._cleanup_old()
            return

        await self._make_snapshot(target_dir)
        await self._cleanup_old()

    # ------------------------------------------------------------------
    # Ручной бэкап
    # ------------------------------------------------------------------

    async def make_backup(self, manual: bool = True) -> dict[str, Any]:
        """Создаёт бэкап. Если manual=True — с суффиксом HHMMSS.

        Возвращает метаданные созданного бэкапа.
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            if manual:
                name = now.strftime("%Y-%m-%d-%H%M%S")
            else:
                name = now.strftime("%Y-%m-%d")

            target_dir = BACKUP_DIR / name
            if target_dir.exists():
                # авто-бэкап за сегодня уже есть
                if not manual:
                    return self._read_meta(target_dir) or {"name": name, "skipped": True}
                # ручной при совпадении времени — добавляем микросекунды
                name = now.strftime("%Y-%m-%d-%H%M%S-%f")
                target_dir = BACKUP_DIR / name

            return await self._make_snapshot(target_dir)

    # ------------------------------------------------------------------
    # Снимок
    # ------------------------------------------------------------------

    async def _make_snapshot(self, target_dir: Path) -> dict[str, Any]:
        """Копирует все файлы состояния в target_dir, пишет _meta.json."""
        target_dir.mkdir(parents=True, exist_ok=True)

        copied: dict[str, int] = {}
        total_bytes = 0

        for name, src in _BACKUP_FILES.items():
            if not src.exists():
                continue
            dst = target_dir / name
            try:
                await asyncio.to_thread(shutil.copy2, src, dst)
                size = dst.stat().st_size
                copied[name] = size
                total_bytes += size
            except Exception as exc:  # noqa: BLE001
                logger.warning("Не удалось скопировать %s: %s", src, exc)

        meta: dict[str, Any] = {
            "name": target_dir.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": copied,
            "total_bytes": total_bytes,
            "schema": 1,
        }

        async with aiofiles.open(target_dir / "_meta.json", "w", encoding="utf-8") as f:
            await f.write(json.dumps(meta, ensure_ascii=False, indent=2))

        logger.info(
            "Backup создан: %s (%d файлов, %.1f КБ)",
            target_dir.name, len(copied), total_bytes / 1024,
        )
        return meta

    # ------------------------------------------------------------------
    # Список и восстановление
    # ------------------------------------------------------------------

    def list_backups(self) -> list[dict[str, Any]]:
        """Возвращает список бэкапов, отсортированный по дате (свежие первыми)."""
        out: list[dict[str, Any]] = []
        if not BACKUP_DIR.exists():
            return out

        for d in sorted(BACKUP_DIR.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            meta = self._read_meta(d)
            if meta:
                out.append(meta)
            else:
                # папка без _meta.json — считаем по файлам
                files = {}
                total = 0
                for f in d.iterdir():
                    if f.is_file() and f.name != "_meta.json":
                        files[f.name] = f.stat().st_size
                        total += files[f.name]
                out.append({
                    "name": d.name,
                    "created_at": None,
                    "files": files,
                    "total_bytes": total,
                    "schema": None,
                })

        return out

    def _read_meta(self, dir_path: Path) -> dict[str, Any] | None:
        meta_file = dir_path / "_meta.json"
        if not meta_file.exists():
            return None
        try:
            return json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    async def restore(self, backup_name: str, files: list[str] | None = None) -> dict[str, Any]:
        """Восстанавливает файлы из бэкапа.

        backup_name: имя папки в /data/backups/
        files: список имён файлов для восстановления.
               Если None — восстанавливает все.

        Перед заменой делает копию текущего файла в /data/backups/_pre-restore_<name>/
        на случай, если пользователь ошибся.
        """
        backup_path = BACKUP_DIR / backup_name
        if not backup_path.exists() or not backup_path.is_dir():
            raise ValueError(f"Бэкап '{backup_name}' не найден")

        # Список файлов для восстановления
        candidates = files if files else list(_BACKUP_FILES.keys())
        restored: list[str] = []

        # Сначала сохраним текущее состояние в pre-restore
        pre_dir = BACKUP_DIR / f"_pre-restore_{backup_name}"
        pre_dir.mkdir(parents=True, exist_ok=True)

        for name in candidates:
            src = backup_path / name
            dst = _BACKUP_FILES.get(name)
            if not src.exists() or dst is None:
                continue

            # Копия текущего — в pre-restore
            if dst.exists():
                try:
                    await asyncio.to_thread(shutil.copy2, dst, pre_dir / name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Не удалось сохранить pre-restore для %s: %s", name, exc)

            # Копируем из бэкапа
            try:
                await asyncio.to_thread(shutil.copy2, src, dst)
                restored.append(name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Не удалось восстановить %s: %s", name, exc)

        logger.info(
            "Restore из '%s': восстановлено %d файлов (pre-restore в %s)",
            backup_name, len(restored), pre_dir.name,
        )

        return {
            "ok": True,
            "backup_name": backup_name,
            "restored": restored,
            "pre_restore": pre_dir.name if restored else None,
        }

    async def delete(self, backup_name: str) -> bool:
        """Удаляет папку бэкапа."""
        if ".." in backup_name or "/" in backup_name:
            raise ValueError("Некорректное имя бэкапа")
        backup_path = BACKUP_DIR / backup_name
        if not backup_path.exists() or not backup_path.is_dir():
            return False
        try:
            await asyncio.to_thread(shutil.rmtree, backup_path)
            logger.info("Backup удалён: %s", backup_name)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось удалить %s: %s", backup_name, exc)
            return False

    # ------------------------------------------------------------------
    # Ротация
    # ------------------------------------------------------------------

    async def _cleanup_old(self) -> int:
        """Удаляет бэкапы старше BACKUP_KEEP_DAYS дней.

        Файлы с префиксом `_` (pre-restore) не удаляются автоматически —
        пользователь сам должен их почистить.
        """
        if not BACKUP_DIR.exists() or BACKUP_KEEP_DAYS <= 0:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=BACKUP_KEEP_DAYS)
        removed = 0

        for d in BACKUP_DIR.iterdir():
            if not d.is_dir():
                continue
            if d.name.startswith("_"):
                continue

            # Дата из имени (первые 10 символов YYYY-MM-DD)
            try:
                dir_date = datetime.strptime(d.name[:10], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                # Если имя не начинается с даты — используем mtime папки
                try:
                    dir_date = datetime.fromtimestamp(d.stat().st_mtime, tz=timezone.utc)
                except Exception:  # noqa: BLE001
                    continue

            if dir_date < cutoff:
                try:
                    await asyncio.to_thread(shutil.rmtree, d)
                    removed += 1
                    logger.info("Удалён старый backup: %s", d.name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Не удалось удалить %s: %s", d, exc)

        return removed

    # ------------------------------------------------------------------
    # Информация
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Сводка: сколько бэкапов, общий размер, последний."""
        backups = self.list_backups()
        total_bytes = sum(b.get("total_bytes", 0) for b in backups)
        return {
            "enabled": BACKUP_ENABLED,
            "keep_days": BACKUP_KEEP_DAYS,
            "interval_hours": BACKUP_INTERVAL_HOURS,
            "backup_dir": str(BACKUP_DIR),
            "count": len(backups),
            "total_bytes": total_bytes,
            "last_backup": backups[0] if backups else None,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

backup_manager = BackupManager()