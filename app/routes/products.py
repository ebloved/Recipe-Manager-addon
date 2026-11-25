"""Дополнительные эндпоинты для продуктов (аналитика и заявки)."""
from fastapi import APIRouter, HTTPException, Request

from services.auth import get_current_user
from services.product_sync import (
    NonFoodProductError,
    approve_suggestion,
    list_suggestions,
    reject_suggestion,
)
from stores import recipe_store

router = APIRouter(prefix="/api/products", tags=["products"])


def _admin(request: Request) -> dict:
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    return user


@router.get("/unlinked")
async def get_unlinked_ingredients():
    """Собирает список уникальных ингредиентов из всех рецептов, у которых нет product_id."""
    unlinked = {}
    for r in recipe_store.get_all():
        for ing in r.get("ingredients", []):
            name = ing.get("name") if isinstance(ing, dict) else str(ing)
            if not name: continue
            
            pid = ing.get("product_id") if isinstance(ing, dict) else None
            if not pid:
                norm = name.strip().lower()
                unlinked[norm] = unlinked.get(norm, 0) + 1
                
    result = [{"name": k, "count": v} for k, v in unlinked.items()]
    result.sort(key=lambda x: (-x["count"], x["name"]))
    
    return {"unlinked": result, "total_unique": len(result)}


# --- Заявки на новые продукты (из внешних покупок) ------------------------


@router.get("/suggestions")
async def product_suggestions(request: Request, status: str = "pending"):
    _admin(request)
    return {"items": await list_suggestions(status or None)}


@router.post("/suggestions/{suggestion_id}/approve")
async def approve_product_suggestion(suggestion_id: str, request: Request):
    user = _admin(request)
    try:
        product = await approve_suggestion(suggestion_id, admin_id=user["id"])
    except NonFoodProductError as exc:
        raise HTTPException(
            409, f"Non-food product ignored: {exc.reason}"
        ) from exc
    if product is None:
        raise HTTPException(404, "Suggestion not found or already reviewed")
    return {"status": "approved", "product": product}


@router.post("/suggestions/{suggestion_id}/reject")
async def reject_product_suggestion(suggestion_id: str, request: Request):
    user = _admin(request)
    ok = await reject_suggestion(suggestion_id, admin_id=user["id"])
    if not ok:
        raise HTTPException(404, "Suggestion not found or already reviewed")
    return {"status": "rejected"}
