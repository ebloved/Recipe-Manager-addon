import io
import sqlite3
import uuid
import zipfile
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from config import DATA_DIR, DB_FILE, MEDIA_DIR
from .admin import check_admin
from fastapi import Request

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.get("/backup.zip")
async def download_backup(request: Request):
    check_admin(request)
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for f in DATA_DIR.iterdir():
            if f.is_file() and f.suffix == ".json" and f.name not in ("jobs.json", "rate_limits.json"):
                zip_file.write(f, f.name)

        # Изображения рецептов: content-addressed каталоги.
        if MEDIA_DIR.exists():
            for path in MEDIA_DIR.rglob("*"):
                if path.is_file() and not path.name.startswith("."):
                    zip_file.write(path, str(path.relative_to(MEDIA_DIR.parent)))

        # SQLite — консистентная копия, а не копирование живого файла.
        if DB_FILE.exists():
            tmp = DATA_DIR / f".backup_tmp_{uuid.uuid4().hex}.sqlite3"
            try:
                src = sqlite3.connect(str(DB_FILE))
                dst = sqlite3.connect(str(tmp))
                try:
                    src.backup(dst)
                finally:
                    src.close()
                    dst.close()
                zip_file.write(tmp, "rm.sqlite3")
            finally:
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass

    zip_buffer.seek(0)
    try:
        from services import audit

        actor = audit.actor_from_request(request)
        await audit.log_event(
            action="admin.backup_download",
            label="Скачивание ZIP-бэкапа",
            actor_kind=actor["kind"],
            actor_id=actor["id"],
            actor_name=actor["name"],
            actor_email=actor["email"],
            actor_role=actor["role"],
            status="ok",
            details={"bytes": len(zip_buffer.getvalue())},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[audit] backup log failed: {exc}")
    return StreamingResponse(
        iter([zip_buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=recipe_manager_backup.zip"}
    )
