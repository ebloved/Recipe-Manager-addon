"""Собирает все роутеры в один api_router."""
from fastapi import APIRouter

from . import imports, youtube, meal_plan, recipes, misc

api_router = APIRouter()
api_router.include_router(imports.router)
api_router.include_router(youtube.router)
api_router.include_router(meal_plan.router)
api_router.include_router(recipes.router)
api_router.include_router(misc.router)

__all__ = ["api_router"]