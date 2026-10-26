from fastapi import APIRouter, Request, HTTPException, Body
from config import AUTH_MODE
from services.auth import users_store

router = APIRouter(prefix="/api/admin", tags=["admin"])

def check_admin(request: Request):
    if AUTH_MODE == "oauth":
        session_id = request.cookies.get("rm_session")
        user = users_store.users.get(session_id)
        if not user or user.get("role") != "admin":
            raise HTTPException(403, "Admin only")

@router.get("/users")
async def get_users(request: Request):
    check_admin(request)
    return {
        "users": list(users_store.users.values()),
        "allowed_emails": users_store.allowed_emails
    }

@router.post("/users")
async def add_user(request: Request, payload: dict = Body(...)):
    check_admin(request)
    email = payload.get("email", "").strip()
    if not email:
        raise HTTPException(400, "Email is required")
    await users_store.add_allowed_email(email)
    return {"status": "ok"}

@router.delete("/users/{user_id}")
async def delete_user(request: Request, user_id: str):
    check_admin(request)
    await users_store.remove_user(user_id)
    return {"status": "ok"}
