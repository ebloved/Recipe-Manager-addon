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
    active_emails = {u["email"] for u in users_store.users.values()}
    pending_emails = [e for e in users_store.allowed_emails if e not in active_emails]
    
    return {
        "users": list(users_store.users.values()),
        "pending_emails": pending_emails,
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

@router.delete("/users/{email:path}")
async def delete_user(request: Request, email: str):
    check_admin(request)
    email = email.lower()
    
    # Удаляем из белого списка
    if email in users_store.allowed_emails:
        users_store.allowed_emails.remove(email)
        
    # Удаляем пользователя, если он есть
    for uid, u in list(users_store.users.items()):
        if u["email"] == email:
            del users_store.users[uid]
            
    await users_store.save()
    return {"status": "ok"}
