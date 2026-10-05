"use strict";
(function (RM) {
  RM.state = {
    recipes: [],
    currentJobId: null,
    currentRecipe: null,
    servingMult: 1,
    completedSteps: new Set(),
    plannerWeekStart: null,
    plannerEntries: [],
    pickerWeekStart: null,
    pickerRecipe: null,
    pickerServings: 2,
  };

  RM.MEALS = ["breakfast", "lunch", "snack", "dinner"];
  RM.MEAL_LABELS = {
    breakfast: "Завтрак",
    lunch: "Обед",
    snack: "Полдник",
    dinner: "Ужин",
  };

  // Дневные нормы для расчёта процентов (используются в detail.js и planner.js).
  // Источник: средние значения для взрослого человека на 2000 ккал/день.
  RM.RDA = {
    calories: 2000,
    protein: 50,
    fat: 65,
    carbohydrates: 300,
  };
})(window.RM);