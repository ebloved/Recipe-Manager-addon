import io
import zipfile
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from config import DATA_DIR
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
                
    zip_buffer.seek(0)
    return StreamingResponse(
        iter([zip_buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=recipe_manager_backup.zip"}
    )
