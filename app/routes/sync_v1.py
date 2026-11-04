"""Sync API v1: snapshot, changes, create recipe для тонкого клиента."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, HTTPException, Query, Request
from sqlalchemy import func, or_, select

from config import SYNC_CONTRACT_VERSION
from db import SessionLocal
from services.device_auth import require_device_user
from stores import recipe_store, shopping_store
from stores.db_models import ProcessedOp, Recipe, RecipeChange, ShoppingItem
from stores.shopping import ShoppingStore
from stores.recipes import _identity

router = APIRouter(prefix="/api/v1", tags=["sync"])

_OP_TTL_DAYS = 30


def _shopping_item(row: ShoppingItem) -> dict:
    return {
        "id": row.id,
        "owner_id": row.owner_id,
        "name": row.name,
        "amount": row.amount,
        "unit": row.unit,
        "brand": row.brand,
        "barcode": row.barcode,
        "image_url": row.image_url,
        "category": row.category,
        "note": row.note,
        "checked": bool(row.checked),
        "recipe_id": row.recipe_id,
        "recipe_name": row.recipe_name,
        "source": row.source,
        "product_id": row.product_id,
        "created_at": row.created_at,
        "revision": row.revision,
    }


@router.get("/health")
async def sync_health():
    return {"status": "ok", "contract_version": SYNC_CONTRACT_VERSION}


@router.get("/snapshot")
async def sync_snapshot(request: Request):
    owner = await require_device_user(request)
    owner_id = owner["id"]

    async with SessionLocal() as session:
        # Рецепты — общая база (владелец только для прав редактирования).
        max_revision = int(
            await session.scalar(select(func.max(RecipeChange.revision))) or 0
        )
        recipes = (
            await session.execute(
                select(Recipe).where(Recipe.deleted_at.is_(None))
            )
        ).scalars().all()
        items = (
            await session.execute(
                select(ShoppingItem).where(
                    ShoppingItem.owner_id == owner_id,
                    ShoppingItem.deleted_at.is_(None),
                )
            )
        ).scalars().all()

    return {
        "contract_version": SYNC_CONTRACT_VERSION,
        "snapshot_revision": max_revision,
        "recipes": [
            {
                **dict(row.payload or {}),
                "id": row.id,
                "owner_id": row.owner_id,
                "source": row.source,
                "source_id": row.source_id,
                "version": row.version,
            }
            for row in recipes
        ],
        "shopping_items": [_shopping_item(row) for row in items],
    }


@router.get("/changes")
async def sync_changes(
    request: Request,
    since: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=200),
):
    owner = await require_device_user(request)
    owner_id = owner["id"]

    async with SessionLocal() as session:
        # Recipe changes — глобальные; shopping — только свои.
        rows = (
            await session.execute(
                select(RecipeChange)
                .where(
                    RecipeChange.revision > since,
                    or_(
                        RecipeChange.entity_type == "recipe",
                        RecipeChange.owner_id == owner_id,
                    ),
                )
                .order_by(RecipeChange.revision)
                .limit(limit + 1)
            )
        ).scalars().all()
        has_more = len(rows) > limit
        rows = rows[:limit]

        changes: list[dict] = []
        for change in rows:
            if change.entity_type == "recipe":
                row = await session.get(Recipe, change.entity_id)
                if row is None or row.deleted_at is not None:
                    changes.append({
                        "revision": change.revision,
                        "entity_type": "recipe",
                        "entity_id": change.entity_id,
                        "op": "delete",
                    })
                else:
                    changes.append({
                        "revision": change.revision,
                        "entity_type": "recipe",
                        "entity_id": change.entity_id,
                        "op": "upsert",
                        "version": row.version,
                        "payload": {
                            **dict(row.payload or {}),
                            "id": row.id,
                            "owner_id": row.owner_id,
                            "source": row.source,
                            "source_id": row.source_id,
                            "version": row.version,
                        },
                    })
            elif change.entity_type == "shopping_item":
                row = await session.get(ShoppingItem, change.entity_id)
                if row is None or row.deleted_at is not None:
                    changes.append({
                        "revision": change.revision,
                        "entity_type": "shopping_item",
                        "entity_id": change.entity_id,
                        "op": "delete",
                    })
                else:
                    changes.append({
                        "revision": change.revision,
                        "entity_type": "shopping_item",
                        "entity_id": change.entity_id,
                        "op": "upsert",
                        "payload": _shopping_item(row),
                    })

    next_revision = rows[-1].revision if rows else since
    return {
        "contract_version": SYNC_CONTRACT_VERSION,
        "changes": changes,
        "next_revision": next_revision,
        "has_more": has_more,
    }


@router.post("/recipes")
async def sync_create_recipe(request: Request, payload: dict = Body(...)):
    owner = await require_device_user(request)
    owner_id = owner["id"]
    op_uuid = str(payload.get("op_uuid") or "").strip()
    if not op_uuid:
        raise HTTPException(400, "op_uuid is required")

    async with SessionLocal() as session:
        processed = await session.get(ProcessedOp, op_uuid)
        if processed is not None:
            return {**dict(processed.result or {}), "deduplicated": True}

    data = dict(payload.get("payload") or {})
    if payload.get("id"):
        data.setdefault("id", str(payload["id"]))
    data["owner_id"] = owner_id
    if payload.get("source"):
        data["source"] = str(payload["source"])
    if payload.get("source_id"):
        data["source_id"] = str(payload["source_id"])

    source, source_id = _identity(data)
    data["source"] = source
    data["source_id"] = source_id
    if not data.get("id"):
        data["id"] = uuid.uuid4().hex

    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(Recipe).where(
                    Recipe.owner_id == owner_id,
                    Recipe.source == source,
                    Recipe.source_id == source_id,
                )
            )
        ).scalar_one_or_none()
        deduplicated = existing is not None and existing.deleted_at is None

    recipe = await recipe_store.add(data)

    async with SessionLocal() as session:
        row = await session.get(Recipe, recipe["id"])
        if row is None:
            raise HTTPException(500, "recipe not persisted")
        result = {
            "status": "ok",
            "server_id": row.id,
            "revision": row.revision,
            "version": row.version,
            "deduplicated": deduplicated,
        }
        session.add(
            ProcessedOp(
                op_uuid=op_uuid,
                result=result,
                expires_at=datetime.now(timezone.utc) + timedelta(days=_OP_TTL_DAYS),
            )
        )
        await session.commit()
    return result


@router.post("/shopping/ops")
async def sync_shopping_ops(request: Request, payload: dict = Body(...)):
    owner = await require_device_user(request)
    owner_id = owner["id"]
    ops = payload.get("ops") or []
    if not isinstance(ops, list) or len(ops) > 100:
        raise HTTPException(400, "ops must be a list of 1..100")

    results: list[dict] = []
    for op in ops:
        if not isinstance(op, dict):
            continue
        op_uuid = str(op.get("op_uuid") or "").strip()
        op_type = str(op.get("op") or "").strip()
        if not op_uuid:
            results.append({"status": "error", "error": "op_uuid required"})
            continue

        async with SessionLocal() as session:
            processed = await session.get(ProcessedOp, op_uuid)
            if processed is not None:
                results.append({**dict(processed.result or {}), "deduplicated": True})
                continue

            try:
                if op_type == "add":
                    data = dict(op.get("payload") or {})
                    name = str(data.get("name") or "").strip()
                    if not name:
                        raise ValueError("add: name required")
                    item_id = uuid.uuid4().hex
                    row = ShoppingItem(
                        id=item_id,
                        owner_id=owner_id,
                        name=name,
                        amount=data.get("amount"),
                        unit=data.get("unit"),
                        brand=data.get("brand"),
                        barcode=data.get("barcode"),
                        image_url=data.get("image_url"),
                        category=data.get("category"),
                        note=data.get("note"),
                        checked=bool(data.get("checked", False)),
                        recipe_id=data.get("recipe_id"),
                        recipe_name=data.get("recipe_name"),
                        source=data.get("source") or "manual",
                        product_id=data.get("product_id"),
                        created_at=datetime.now(timezone.utc).isoformat(),
                    )
                    session.add(row)
                    change = RecipeChange(
                        entity_type="shopping_item",
                        entity_id=item_id,
                        op="upsert",
                        owner_id=owner_id,
                    )
                    session.add(change)
                    await session.flush()
                    row.revision = change.revision
                    await session.commit()
                    result = {
                        "op_uuid": op_uuid,
                        "status": "ok",
                        "server_id": item_id,
                        "revision": change.revision,
                        "deduplicated": False,
                    }
                elif op_type in ("set_checked", "remove"):
                    item_id = str(op.get("item_id") or "").strip()
                    if not item_id:
                        raise ValueError(f"{op_type}: item_id required")
                    row = await session.get(ShoppingItem, item_id)
                    if row is None or row.owner_id != owner_id:
                        raise ValueError("item not found")
                    if op_type == "set_checked":
                        row.checked = bool(op.get("checked"))
                        change_op = "upsert"
                    else:
                        row.deleted_at = datetime.now(timezone.utc)
                        change_op = "delete"
                    change = RecipeChange(
                        entity_type="shopping_item",
                        entity_id=item_id,
                        op=change_op,
                        owner_id=owner_id,
                    )
                    session.add(change)
                    await session.flush()
                    row.revision = change.revision
                    await session.commit()
                    result = {
                        "op_uuid": op_uuid,
                        "status": "ok",
                        "server_id": item_id,
                        "revision": change.revision,
                        "deduplicated": False,
                    }
                elif op_type == "clear":
                    ids = [
                        r.id for r in (
                            await session.execute(
                                select(ShoppingItem).where(
                                    ShoppingItem.owner_id == owner_id,
                                    ShoppingItem.deleted_at.is_(None),
                                    ShoppingItem.checked.is_(True)
                                    if op.get("only_checked") else True,
                                )
                            )
                        ).scalars().all()
                    ]
                    for item_id in ids:
                        row = await session.get(ShoppingItem, item_id)
                        row.deleted_at = datetime.now(timezone.utc)
                        change = RecipeChange(
                            entity_type="shopping_item",
                            entity_id=item_id,
                            op="delete",
                            owner_id=owner_id,
                        )
                        session.add(change)
                        await session.flush()
                        row.revision = change.revision
                    await session.commit()
                    result = {"op_uuid": op_uuid, "status": "ok", "removed": len(ids)}
                else:
                    raise ValueError(f"unknown op {op_type!r}")

                session.add(
                    ProcessedOp(
                        op_uuid=op_uuid,
                        result=result,
                        expires_at=datetime.now(timezone.utc) + timedelta(days=_OP_TTL_DAYS),
                    )
                )
                await session.commit()
                await shopping_store.load()
                results.append(result)
            except Exception as exc:  # noqa: BLE001
                results.append({
                    "op_uuid": op_uuid,
                    "status": "error",
                    "error": str(exc)[:200],
                })

    return {"results": results}
