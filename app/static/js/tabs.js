"use strict";
(function (RM) {
  const { $ } = RM.utils;

  function setupTopTabs() {
    document.querySelectorAll(".tab").forEach((t) => {
      t.addEventListener("click", () => {
        activateTab(t.dataset.panel);
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

  function activateTab(name) {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((x) => x.classList.remove("active"));
    const tab = document.querySelector(`.tab[data-panel="${name}"]`);
    const panel = $("panel-" + name);
    if (tab) tab.classList.add("active");
    if (panel) panel.classList.add("active");

    if (name === "recipes") RM.recipes.load();
    if (name === "planner") RM.planner.load();
    if (name === "shopping") RM.shopping.load();
  }

  function switchToRecipes() { activateTab("recipes"); }

  RM.tabs = { setupTopTabs, setupSubTabs, activateTab, switchToRecipes, switchTo: activateTab };
})(window.RM);