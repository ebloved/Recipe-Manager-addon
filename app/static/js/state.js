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
})(window.RM);