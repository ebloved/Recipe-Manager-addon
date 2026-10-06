"use strict";
(function (RM) {
  const { $ } = RM.utils;

  // -----------------------------------------------------------------
  // Top-level tabs (Рецепты / Планировщик / Покупки / Продукты /
  // Синхронизация / YouTube / Импорт)
  // -----------------------------------------------------------------
  function setupTopTabs() {
    document.querySelectorAll(".tab").forEach((t) => {
      t.addEventListener("click", () => {
        activateTab(t.dataset.panel);
      });
    });
  }

  // -----------------------------------------------------------------
  // Sub-tabs внутри вкладки «Импорт» (Scrape / Markdown / Manual)
  // -----------------------------------------------------------------
  function setupSubTabs() {
    document.querySelectorAll(".sub-tab").forEach((t) => {
      // Не трогаем sub-tab, у которых есть data-pp-tab (это табы
      // внутри product-picker) — они управляются своим модулем.
      if (t.dataset.ppTab) return;

      t.addEventListener("click", () => {
        document.querySelectorAll(".sub-tab").forEach((x) => {
          if (x.dataset.ppTab) return;
          x.classList.remove("active");
        });
        document.querySelectorAll(".subpanel").forEach((x) => x.classList.remove("active"));
        t.classList.add("active");
        $("subpanel-" + t.dataset.subpanel).classList.add("active");
      });
    });
  }

  // -----------------------------------------------------------------
  // Activate top-level tab
  // -----------------------------------------------------------------
  function activateTab(name) {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((x) => x.classList.remove("active"));

    const tab = document.querySelector(`.tab[data-panel="${name}"]`);
    const panel = $("panel-" + name);

    if (tab) tab.classList.add("active");
    if (panel) panel.classList.add("active");

    // Ленивая подгрузка данных для вкладки
    switch (name) {
      case "recipes":
        if (RM.recipes) RM.recipes.load();
        break;
      case "planner":
        if (RM.planner) RM.planner.load();
        break;
      case "shopping":
        if (RM.shopping) RM.shopping.load();
        break;
      case "products":
        if (RM.products) RM.products.load();
        break;
      case "sync":
        if (RM.sync) RM.sync.load();
        break;
      // youtube, import — статические формы, ничего не грузим
    }
  }

  function switchToRecipes() {
    activateTab("recipes");
  }

  RM.tabs = {
    setupTopTabs,
    setupSubTabs,
    activateTab,
    switchToRecipes,
    switchTo: activateTab,
  };
})(window.RM);