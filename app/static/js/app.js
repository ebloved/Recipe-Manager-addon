"use strict";
(function (RM) {
  async function checkAuth() {
    try {
      const me = await RM.api.getJSON("api/me");
      if (me.authenticated === false) {
        document.getElementById("auth-screen").style.display = "flex";
        document.querySelector("header").style.display = "none";
        document.querySelector("main").style.display = "none";
        return false;
      }
      return true;
    } catch (e) {
      return true; // Если API недоступно, пропускаем (например, в HA)
    }
  }

  async function init() {
    const authed = await checkAuth();
    if (!authed) return;

    RM.tabs.setupTopTabs();
    RM.tabs.setupSubTabs();

    // Планировщик и покупки
    RM.planPicker.setup();
    RM.planner.setup();
    RM.recipePicker.setup();
    RM.shopping.setup();

    // Рецепты
    RM.recipes.setup();
    RM.detail.setup();
    RM.youtube.setup();
    RM.imports.setup();

    // Генератор
    if (RM.generator) RM.generator.setup();

    // Продукты
    if (RM.products) RM.products.setup();

    // Пикер продукта для ингредиентов (используется в detail.js и editor.js)
    if (RM.productPicker) RM.productPicker.setup();

    // Профили генерации
    if (RM.profiles) {
      RM.profiles.setup();
      RM.profiles.load();
    }

    // Кабинет (включает в себя синхронизацию)
    if (RM.cabinet) RM.cabinet.setup();

    // Live-sync (периодический polling)
    if (RM.liveSync) RM.liveSync.setup();

    // Первичная загрузка
    RM.recipes.load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window.RM);