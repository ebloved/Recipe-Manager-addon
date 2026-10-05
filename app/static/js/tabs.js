"use strict";
(function (RM) {
  const { $ } = RM.utils;

  function setupTopTabs() {
    document.querySelectorAll(".tab").forEach((t) => {
      t.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
        document.querySelectorAll(".panel").forEach((x) => x.classList.remove("active"));
        t.classList.add("active");
        $("panel-" + t.dataset.panel).classList.add("active");

        const panel = t.dataset.panel;
        if (panel === "recipes") RM.recipes.load();
        if (panel === "planner") RM.planner.load();
      });
    });
  }

  function setupSubTabs() {
    document.querySelectorAll(".sub-tab").forEach((t) => {
      t.addEventListener("click", () => {
        document.querySelectorAll(".sub-tab").forEach((x) => x.classList.remove("active"));
        document.querySelectorAll(".subpanel").forEach((x) => x.classList.remove("active"));
        t.classList.add("active");
        $("subpanel-" + t.dataset.subpanel).classList.add("active");
      });
    });
  }

  function switchToRecipes() {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((x) => x.classList.remove("active"));
    document.querySelector('.tab[data-panel="recipes"]').classList.add("active");
    $("panel-recipes").classList.add("active");
  }

  RM.tabs = { setupTopTabs, setupSubTabs, switchToRecipes };
})(window.RM);