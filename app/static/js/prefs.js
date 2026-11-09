/* Личные настройки интерфейса (localStorage). */
"use strict";
(function (RM) {
  const SHOW_SIDE_RECIPES_KEY = "rm_show_side_recipes";
  const OFFER_SIDE_COOKING_KEY = "rm_offer_side_cooking";
  const LEGACY_KEY = "rm_show_side_dish";

  function readBool(key, fallback) {
    try {
      const value = localStorage.getItem(key);
      if (value === null) return fallback;
      return value === "1";
    } catch (_) {
      return fallback;
    }
  }

  function writeBool(key, value) {
    try {
      localStorage.setItem(key, value ? "1" : "0");
    } catch (_) { /* localStorage может быть отключён */ }
  }

  // Старая настройка «Показывать гарнир» управляла предложением при готовке.
  // Переносим её значение в новую настройку «Предлагать гарнир».
  try {
    if (
      localStorage.getItem(OFFER_SIDE_COOKING_KEY) === null
      && localStorage.getItem(LEGACY_KEY) !== null
    ) {
      localStorage.setItem(
        OFFER_SIDE_COOKING_KEY,
        localStorage.getItem(LEGACY_KEY),
      );
    }
  } catch (_) { /* ignore */ }

  RM.prefs = {
    getShowSideRecipes: () => readBool(SHOW_SIDE_RECIPES_KEY, true),
    setShowSideRecipes: (value) => writeBool(SHOW_SIDE_RECIPES_KEY, value),
    getOfferSideCooking: () => readBool(OFFER_SIDE_COOKING_KEY, true),
    setOfferSideCooking: (value) => writeBool(OFFER_SIDE_COOKING_KEY, value),
  };
})(window.RM);
