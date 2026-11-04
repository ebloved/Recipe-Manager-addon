"""SQLite (SQLAlchemy 2.0 + aiosqlite): engine, сессии и миграция JSON.

БД лежит в DATA_DIR (в контейнерах это /data), файл rm.sqlite3.
Перед первой миграцией JSON-файлы копируются в DATA_DIR/backups/.
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import DATA_DIR

DB_FILE: Path = DATA_DIR / "rm.sqlite3"
DATABASE_URL: str = f"sqlite+aiosqlite:///{DB_FILE}"
SCHEMA_VERSION = 1


class Base(DeclarativeBase):
    pass


engine = create_async_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


async def _get_user_version() -> int:
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA user_version"))
        return int(result.scalar() or 0)


async def _set_user_version(version: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"PRAGMA user_version = {int(version)}"))


def _backup_json_files() -> Path | None:
    """Копирует JSON-файлы в DATA_DIR/backups перед миграцией."""
    sources = [
        DATA_DIR / "shopping_list.json",
        DATA_DIR / "users.json",
    ]
    existing = [p for p in sources if p.exists()]
    if not existing:
        return None

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = DATA_DIR / "backups" / f"pre_sqlite_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for src in existing:
        shutil.copy2(src, backup_dir / src.name)
    return backup_dir


async def _migrate_shopping_json() -> int:
    """Импортирует shopping_list.json в SQLite. Возвращает число записей."""
    from stores.db_models import ShoppingItem

    path = DATA_DIR / "shopping_list.json"
    if not path.exists():
        return 0

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[db] shopping_list.json read failed: {exc}")
        return 0

    items = data.get("items", []) if isinstance(data, dict) else []
    imported = 0
    async with SessionLocal() as session:
        for raw in items:
            if not isinstance(raw, dict):
                continue
            item_id = raw.get("id") or uuid.uuid4().hex
            if await session.get(ShoppingItem, item_id):
                continue
            session.add(
                ShoppingItem(
                    id=item_id,
                    owner_id=raw.get("owner_id") or "family",
                    name=(raw.get("name") or "").strip(),
                    amount=raw.get("amount"),
                    unit=raw.get("unit"),
                    brand=raw.get("brand"),
                    barcode=raw.get("barcode"),
                    image_url=raw.get("image_url"),
                    category=raw.get("category"),
                    note=raw.get("note"),
                    checked=bool(raw.get("checked", False)),
                    recipe_id=raw.get("recipe_id"),
                    recipe_name=raw.get("recipe_name"),
                    source=raw.get("source") or "manual",
                    product_id=raw.get("product_id"),
                    created_at=raw.get("created_at") or datetime.now().isoformat(),
                )
            )
            imported += 1
        await session.commit()
    return imported


async def init_db() -> None:
    """Создаёт схему и один раз импортирует JSON."""
    # Импорт нужен, чтобы метаданные моделей зарегистрировались.
    from stores import db_models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Одноразовая перешифровка данных со старого дефолтного SECRET_KEY.
    try:
        from services.secret_store import migrate_legacy_secrets
        await migrate_legacy_secrets()
    except Exception as exc:  # noqa: BLE001
        print(f"[secret] legacy migration skipped: {exc}")

    async with engine.begin() as conn:
        # Лёгкая миграция: колонка match_version появилась в v3.10.1.
        cols = (await conn.execute(text("PRAGMA table_info(product_offers)"))).all()
        names = {str(c[1]) for c in cols}
        if "match_version" not in names:
            await conn.execute(text(
                "ALTER TABLE product_offers "
                "ADD COLUMN match_version INTEGER DEFAULT 1"
            ))
            print("[db] product_offers.match_version added (default 1)")

        # v3.1 phase 2b: поля sync для shopping_items (owner_id уже есть).
        shop_cols = (await conn.execute(text("PRAGMA table_info(shopping_items)"))).all()
        shop_names = {str(c[1]) for c in shop_cols}
        if "revision" not in shop_names:
            await conn.execute(text(
                "ALTER TABLE shopping_items ADD COLUMN revision INTEGER DEFAULT 0"
            ))
            print("[db] shopping_items.revision added")
        if "deleted_at" not in shop_names:
            await conn.execute(text(
                "ALTER TABLE shopping_items ADD COLUMN deleted_at TIMESTAMP"
            ))
            print("[db] shopping_items.deleted_at added")

        # v3.22.2: структурированные ошибки в журнале действий.
        audit_cols = (await conn.execute(text("PRAGMA table_info(audit_events)"))).all()
        audit_names = {str(c[1]) for c in audit_cols}
        for column, ddl in (
            ("error_code", "ALTER TABLE audit_events ADD COLUMN error_code VARCHAR(64)"),
            ("error_provider", "ALTER TABLE audit_events ADD COLUMN error_provider VARCHAR(64)"),
            ("error_model", "ALTER TABLE audit_events ADD COLUMN error_model VARCHAR(128)"),
        ):
            if audit_names and column not in audit_names:
                await conn.execute(text(ddl))
                print(f"[db] audit_events.{column} added")
        if audit_names:
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_audit_events_error_code "
                "ON audit_events(error_code)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_audit_events_error_provider "
                "ON audit_events(error_provider)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_audit_events_error_model "
                "ON audit_events(error_model)"
            ))

    # Backfill revision для существующих shopping-позиций (phase 2b).
    try:
        from stores.db_models import RecipeChange, ShoppingItem
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(ShoppingItem).where(ShoppingItem.revision == 0)
                )
            ).scalars().all()
            for row in rows:
                change = RecipeChange(
                    entity_type="shopping_item",
                    entity_id=row.id,
                    op="upsert",
                    owner_id=row.owner_id or "family",
                )
                session.add(change)
                await session.flush()
                row.revision = change.revision
            if rows:
                await session.commit()
                print(f"[db] backfilled shopping revisions: {len(rows)}")
    except Exception as exc:  # noqa: BLE001
        print(f"[db] shopping revision backfill skipped: {exc}")

    version = await _get_user_version()
    if version >= SCHEMA_VERSION:
        return

    backup_dir = _backup_json_files()
    if backup_dir:
        print(f"[db] JSON backup: {backup_dir}")

    imported = await _migrate_shopping_json()
    await _set_user_version(SCHEMA_VERSION)
    print(f"[db] migrated shopping_list.json -> {DB_FILE} ({imported} items)")
