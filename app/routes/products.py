"""Дополнительные эндпоинты для продуктов (аналитика)."""
from fastapi import APIRouter
from stores import recipe_store

router = APIRouter(prefix="/api/products", tags=["products"])

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
