"""Локальный кэш и pending-очереди BFF (cache.sqlite)."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from config import DATA_DIR
from services import remote_client

CACHE_FILE: Path = DATA_DIR / "cache.sqlite"
_initialized = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    global _initialized
    conn = sqlite3.connect(str(CACHE_FILE))
    if not _initialized:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS recipes_cache (
                server_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS shopping_cache (
                server_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sync_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_creates (
                op_uuid TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_shopping_ops (
                op_uuid TEXT PRIMARY KEY,
                op TEXT NOT NULL,
                item_id TEXT NOT NULL,
                payload TEXT,
                checked INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        _initialized = True
    return conn


def _state_set(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO sync_state(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )


def _state_get(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except Exception:  # noqa: BLE001
        return default


# --- snapshot / cache -------------------------------------------------------


def save_snapshot(snapshot: dict[str, Any]) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM recipes_cache")
        conn.execute("DELETE FROM shopping_cache")
        for recipe in snapshot.get("recipes") or []:
            rid = str(recipe.get("id") or "")
            if not rid:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO recipes_cache(server_id,payload,revision,updated_at) "
                "VALUES(?,?,?,?)",
                (rid, json.dumps(recipe, ensure_ascii=False), int(recipe.get("version") or 0), _now()),
            )
        for item in snapshot.get("shopping_items") or []:
            iid = str(item.get("id") or "")
            if not iid:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO shopping_cache(server_id,payload,revision) VALUES(?,?,?)",
                (iid, json.dumps(item, ensure_ascii=False), int(item.get("revision") or 0)),
            )
        _state_set(conn, "last_revision", snapshot.get("snapshot_revision") or 0)
        _state_set(conn, "last_sync", _now())
        conn.commit()
    finally:
        conn.close()


def recipes() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT payload FROM recipes_cache ORDER BY updated_at DESC"
        ).fetchall()
        return [json.loads(r[0]) for r in rows]
    finally:
        conn.close()


def recipe(recipe_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT payload FROM recipes_cache WHERE server_id=?", (recipe_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()


def shopping() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT payload FROM shopping_cache").fetchall()
        return [json.loads(r[0]) for r in rows]
    finally:
        conn.close()


def cache_me(me: dict[str, Any]) -> None:
    conn = _connect()
    try:
        _state_set(conn, "me", me)
        conn.commit()
    finally:
        conn.close()


def get_me() -> dict[str, Any] | None:
    conn = _connect()
    try:
        return _state_get(conn, "me")
    finally:
        conn.close()


def status() -> dict[str, Any]:
    conn = _connect()
    try:
        return {
            "last_sync": _state_get(conn, "last_sync"),
            "pending_creates": conn.execute(
                "SELECT COUNT(*) FROM pending_creates WHERE status!='done'"
            ).fetchone()[0],
            "pending_shopping": conn.execute(
                "SELECT COUNT(*) FROM pending_shopping_ops WHERE status!='done'"
            ).fetchone()[0],
        }
    finally:
        conn.close()


# --- pending creates --------------------------------------------------------


def add_pending_recipe(payload: dict[str, Any]) -> dict[str, Any]:
    recipe = dict(payload)
    recipe["id"] = recipe.get("id") or uuid.uuid4().hex
    recipe.setdefault("created_at", _now())
    recipe["updated_at"] = _now()
    op_uuid = uuid.uuid4().hex
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO pending_creates(op_uuid,payload,status,created_at) VALUES(?,?,?,?)",
            (op_uuid, json.dumps(recipe, ensure_ascii=False), "pending", _now()),
        )
        conn.execute(
            "INSERT OR REPLACE INTO recipes_cache(server_id,payload,revision,updated_at) "
            "VALUES(?,?,?,?)",
            (recipe["id"], json.dumps(recipe, ensure_ascii=False), 0, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return recipe


def update_pending_recipe(recipe_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT op_uuid,payload FROM pending_creates WHERE status!='done'"
        ).fetchall()
        for op_uuid, raw in row:
            recipe = json.loads(raw)
            if recipe.get("id") != recipe_id:
                continue
            recipe.update(patch)
            recipe["updated_at"] = _now()
            conn.execute(
                "UPDATE pending_creates SET payload=? WHERE op_uuid=?",
                (json.dumps(recipe, ensure_ascii=False), op_uuid),
            )
            conn.execute(
                "INSERT OR REPLACE INTO recipes_cache(server_id,payload,revision,updated_at) "
                "VALUES(?,?,?,?)",
                (recipe_id, json.dumps(recipe, ensure_ascii=False), 0, _now()),
            )
            conn.commit()
            return recipe
        return None
    finally:
        conn.close()


def delete_pending_recipe(recipe_id: str) -> bool:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT op_uuid,payload FROM pending_creates WHERE status!='done'"
        ).fetchall()
        for op_uuid, raw in row:
            recipe = json.loads(raw)
            if recipe.get("id") != recipe_id:
                continue
            conn.execute("DELETE FROM pending_creates WHERE op_uuid=?", (op_uuid,))
            conn.execute("DELETE FROM recipes_cache WHERE server_id=?", (recipe_id,))
            conn.commit()
            return True
        return False
    finally:
        conn.close()


# --- pending shopping -------------------------------------------------------


def add_pending_shopping(payload: dict[str, Any]) -> dict[str, Any]:
    item = dict(payload)
    item["id"] = item.get("id") or uuid.uuid4().hex
    item.setdefault("created_at", _now())
    item["checked"] = bool(item.get("checked", False))
    op_uuid = uuid.uuid4().hex
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO pending_shopping_ops"
            "(op_uuid,op,item_id,payload,status,created_at) VALUES(?,?,?,?,?,?)",
            (op_uuid, "add", item["id"], json.dumps(item, ensure_ascii=False), "pending", _now()),
        )
        conn.execute(
            "INSERT OR REPLACE INTO shopping_cache(server_id,payload,revision) VALUES(?,?,?)",
            (item["id"], json.dumps(item, ensure_ascii=False), 0),
        )
        conn.commit()
    finally:
        conn.close()
    return item


def set_pending_checked(item_id: str, checked: bool) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT payload FROM shopping_cache WHERE server_id=?", (item_id,)
        ).fetchone()
        if not row:
            return None
        item = json.loads(row[0])
        item["checked"] = bool(checked)

        # Если это ещё не отправленный add — обновляем его payload,
        # а не создаём set_checked с локальным id.
        pending_add = conn.execute(
            "SELECT op_uuid,payload FROM pending_shopping_ops "
            "WHERE op='add' AND item_id=? AND status!='done'",
            (item_id,),
        ).fetchone()
        if pending_add:
            op_uuid, raw = pending_add
            add_item = json.loads(raw or "{}")
            add_item["checked"] = bool(checked)
            conn.execute(
                "UPDATE pending_shopping_ops SET payload=? WHERE op_uuid=?",
                (json.dumps(add_item, ensure_ascii=False), op_uuid),
            )
        else:
            conn.execute(
                "INSERT INTO pending_shopping_ops(op_uuid,op,item_id,checked,status,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, "set_checked", item_id, 1 if checked else 0, "pending", _now()),
            )
        conn.execute(
            "UPDATE shopping_cache SET payload=? WHERE server_id=?",
            (json.dumps(item, ensure_ascii=False), item_id),
        )
        conn.commit()
        return item
    finally:
        conn.close()


def remove_pending_shopping(item_id: str) -> bool:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT payload FROM shopping_cache WHERE server_id=?", (item_id,)
        ).fetchone()
        if not row:
            return False
        pending_add = conn.execute(
            "SELECT op_uuid FROM pending_shopping_ops "
            "WHERE op='add' AND item_id=? AND status!='done'",
            (item_id,),
        ).fetchone()
        if pending_add:
            conn.execute(
                "DELETE FROM pending_shopping_ops WHERE op_uuid=?", (pending_add[0],)
            )
        else:
            conn.execute(
                "INSERT INTO pending_shopping_ops(op_uuid,op,item_id,status,created_at) "
                "VALUES(?,?,?,?,?)",
                (uuid.uuid4().hex, "remove", item_id, "pending", _now()),
            )
        conn.execute("DELETE FROM shopping_cache WHERE server_id=?", (item_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def clear_pending_shopping(only_checked: bool = False) -> int:
    items = shopping()
    removed = 0
    for item in items:
        if only_checked and not item.get("checked"):
            continue
        if remove_pending_shopping(str(item.get("id") or "")):
            removed += 1
    return removed


# --- sync -------------------------------------------------------------------


async def _post(client: httpx.AsyncClient, path: str, token: str, payload: dict) -> httpx.Response:
    return await client.post(
        path, json=payload, headers={"Authorization": f"Bearer {token}"}
    )


async def sync_all() -> dict[str, Any]:
    token = remote_client.get_token()
    server = remote_client.get_server_url()
    if not token or not server:
        return {"status": "unpaired"}

    conn = _connect()
    try:
        pending_recipes = conn.execute(
            "SELECT op_uuid,payload FROM pending_creates WHERE status!='done' ORDER BY created_at"
        ).fetchall()
        pending_shop = conn.execute(
            "SELECT op_uuid,op,item_id,payload,checked FROM pending_shopping_ops "
            "WHERE status!='done' ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()

    failed = 0
    try:
        client_cm = httpx.AsyncClient(base_url=server, timeout=60)
        client = await client_cm.__aenter__()
    except httpx.HTTPError as exc:
        return {
            "status": "offline",
            "error": str(exc)[:200],
            "pending_creates": len(pending_recipes),
            "pending_shopping": len(pending_shop),
        }

    try:
        for op_uuid, raw in pending_recipes:
            payload = json.loads(raw)
            body = {
                "op_uuid": op_uuid,
                "payload": payload,
                "source": payload.get("source"),
                "source_id": payload.get("source_id"),
            }
            resp = await _post(client, "/api/v1/recipes", token, body)
            if resp.status_code < 400:
                conn = _connect()
                try:
                    conn.execute("DELETE FROM pending_creates WHERE op_uuid=?", (op_uuid,))
                    conn.commit()
                finally:
                    conn.close()
            else:
                failed += 1
                conn = _connect()
                try:
                    conn.execute(
                        "UPDATE pending_creates SET attempts=attempts+1,last_error=? WHERE op_uuid=?",
                        (resp.text[:200], op_uuid),
                    )
                    conn.commit()
                finally:
                    conn.close()

        if pending_shop:
            ops = []
            for op_uuid, op, item_id, raw, checked in pending_shop:
                data = {"op_uuid": op_uuid, "op": op, "item_id": item_id}
                if op == "add":
                    data["payload"] = json.loads(raw) if raw else {}
                elif op == "set_checked":
                    data["checked"] = bool(checked)
                ops.append(data)
            for start in range(0, len(ops), 100):
                resp = await _post(
                    client, "/api/v1/shopping/ops", token, {"ops": ops[start:start + 100]}
                )
                if resp.status_code < 400:
                    results = resp.json().get("results") or []
                    conn = _connect()
                    try:
                        for result in results:
                            if result.get("status") == "ok":
                                conn.execute(
                                    "DELETE FROM pending_shopping_ops WHERE op_uuid=?",
                                    (result.get("op_uuid"),),
                                )
                        conn.commit()
                    finally:
                        conn.close()
                else:
                    failed += 1

        if failed:
            return {
                "status": "partial",
                "failed": failed,
                "pending_creates": len(pending_recipes),
                "pending_shopping": len(pending_shop),
            }

        snap = await client.get(
            "/api/v1/snapshot", headers={"Authorization": f"Bearer {token}"}
        )
        if snap.status_code == 200:
            data = snap.json()
            save_snapshot(data)
            return {"status": "ok", "revision": data.get("snapshot_revision")}
        return {"status": "partial", "http_status": snap.status_code}
    except httpx.HTTPError as exc:
        return {
            "status": "offline",
            "error": str(exc)[:200],
            "pending_creates": len(pending_recipes),
            "pending_shopping": len(pending_shop),
        }
    finally:
        await client_cm.__aexit__(None, None, None)
