"""Собирает все роутеры в один api_router."""
from fastapi import APIRouter

from . import (
    backup,
    sharing,
    admin,
    embeddings,
    auth,
    imports,
    youtube,
    generator,
    meal_plan,
    shopping,
    sync,
    ingredients,
    profiles,
    matcher,
    products,
    recipes,
    misc,
    me,
    settings,
    stores,
    cooking,
    device_flow,
    sync_v1,
    remote,
    media,
    voice,
)

api_router = APIRouter()
api_router.include_router(imports.router)
api_router.include_router(youtube.router)
api_router.include_router(meal_plan.router)
api_router.include_router(shopping.router)
api_router.include_router(sync.router)
api_router.include_router(ingredients.router)
api_router.include_router(profiles.router)
api_router.include_router(generator.router)
api_router.include_router(matcher.router)
api_router.include_router(products.router)
api_router.include_router(sharing.router)
api_router.include_router(recipes.router)
api_router.include_router(misc.router)
api_router.include_router(me.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(backup.router)
api_router.include_router(embeddings.router)
api_router.include_router(settings.router)
api_router.include_router(stores.router)
api_router.include_router(cooking.router)
api_router.include_router(device_flow.router)
api_router.include_router(sync_v1.router)
api_router.include_router(remote.router)
api_router.include_router(media.router)
api_router.include_router(voice.router)

__all__ = ["api_router"]