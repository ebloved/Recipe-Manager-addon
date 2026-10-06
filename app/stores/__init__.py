"""Хранилища (recipes, meal_plan, shopping, ingredients)."""
from .recipes import recipe_store, RecipeStore
from .meal_plan import meal_plan_store, MealPlanStore
from .shopping import shopping_store, ShoppingStore
from .ingredients import ingredients_store, IngredientStore

__all__ = [
    "recipe_store", "RecipeStore",
    "meal_plan_store", "MealPlanStore",
    "shopping_store", "ShoppingStore",
    "ingredients_store", "IngredientStore",
]