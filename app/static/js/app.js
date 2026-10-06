"use strict";
(function (RM) {
  function init() {
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

    // Продукты
    if (RM.products) RM.products.setup();

    // Профили генерации
    if (RM.profiles) {
      RM.profiles.setup();
      RM.profiles.load();
    }

    // Синхронизация
    if (RM.sync) RM.sync.setup();

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