"""Публичные ссылки и форк рецептов."""
import uuid
from fastapi import APIRouter, HTTPException
from stores import recipe_store

router = APIRouter(prefix="/api/sharing", tags=["sharing"])

@router.post("/{recipe_id}/share")
async def create_share_link(recipe_id: str):
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    
    token = recipe.get("share_token") or uuid.uuid4().hex[:12]
    await recipe_store.update(recipe_id, {
        "share_token": token,
        "visibility": "unlisted"
    })
    return {"token": token}

@router.delete("/{recipe_id}/share")
async def revoke_share_link(recipe_id: str):
    recipe = recipe_store.get(recipe_id)
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    
    await recipe_store.update(recipe_id, {
        "share_token": None,
        "visibility": "private"
    })
    return {"status": "revoked"}

@router.get("/{token}")
async def get_shared_recipe(token: str):
    recipe = recipe_store.get_by_share_token(token)
    if not recipe:
        raise HTTPException(404, "Shared recipe not found or link revoked")
    return {"recipe": recipe}

@router.post("/{token}/fork")
async def fork_shared_recipe(token: str):
    original = recipe_store.get_by_share_token(token)
    if not original:
        raise HTTPException(404, "Shared recipe not found")
    
    new_recipe = {**original}
    new_recipe["id"] = uuid.uuid4().hex
    new_recipe["name"] = f"{original.get('name')} (копия)"
    new_recipe.pop("share_token", None)
    new_recipe["visibility"] = "private"
    
    created = await recipe_store.add(new_recipe)
    return {"recipe": created}
