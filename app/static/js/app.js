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

  async function checkSharedRoute() {
    const path = window.location.pathname;
    const match = path.match(/\/share\/([a-f0-9]+)/);
    if (!match) return false;
    
    // Скрываем всё, кроме detail-panel
    document.querySelector("header").style.display = "none";
    document.querySelector(".tabs").style.display = "none";
    document.querySelectorAll(".panel").forEach(p => p.style.display = "none");
    
    try {
      const res = await fetch(`${window.location.origin}/api/sharing/${match[1]}`);
      if (!res.ok) throw new Error("Ссылка недействительна или отозвана");
      const data = await res.json();
      if (data && data.recipe) {
        RM.state.isSharedView = true;
        RM.detail.open(data.recipe);
      } else {
        throw new Error("Рецепт не найден");
      }
    } catch(e) {
      document.body.innerHTML = `<div style="padding:20px;color:red;">Ошибка: ${e.message}</div>`;
    }
    return true;
  }

  async function init() {
    if (await checkSharedRoute()) return;
    const authed = await checkAuth();
    if (!authed) return;

    RM.tabs.setupTopTabs();
    RM.tabs.setupSubTabs();

    // Планировщик и покупки
    RM.planPicker.setup();
    RM.planner.setup();
    RM.recipePicker.setup();
    RM.shopping.setup();

    // Поиск по ингредиентам
    if (RM.finder) RM.finder.setup();

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
    if (RM.walkthrough) RM.walkthrough.init();

    if (RM.jobs) RM.jobs.setup();

    RM.recipes.load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window.RM);