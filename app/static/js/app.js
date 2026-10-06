"use strict";
(function (RM) {
  function init() {
    // --- UI: вкладки ---
    if (RM.tabs) RM.tabs.setupTopTabs();
    if (RM.tabs) RM.tabs.setupSubTabs();

    // --- Основные разделы ---
    if (RM.youtube) RM.youtube.setup();
    if (RM.imports) RM.imports.setup();
    if (RM.recipes) RM.recipes.setup();
    if (RM.detail) RM.detail.setup();

    // --- Планировщик ---
    if (RM.planner) RM.planner.setup();
    if (RM.planPicker) RM.planPicker.setup();
    if (RM.recipePicker) RM.recipePicker.setup();

    // --- Покупки ---
    if (RM.shopping) RM.shopping.setup();

    // --- Синхронизация ---
    if (RM.sync) RM.sync.setup();

    // --- База продуктов ---
    // ВАЖНО: productPicker должен быть setup() до editor и detail,
    // чтобы обработчики 🔗 знали, куда открывать модалку.
    if (RM.productPicker) RM.productPicker.setup();
    if (RM.products) RM.products.setup();

    // --- Очередь подтверждений матчинга ---
    if (RM.matcherBatch) RM.matcherBatch.setup();

    // --- Живая синхронизация (polling) ---
    if (RM.liveSync) RM.liveSync.setup();

    // --- Первичная загрузка данных ---
    // Открываем вкладку «Рецепты» по умолчанию
    if (RM.recipes) RM.recipes.load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window.RM);