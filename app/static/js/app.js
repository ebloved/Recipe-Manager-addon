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
      RM.state.user = me;
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
    if (RM.stores) RM.stores.setup();
    if (RM.cooking) RM.cooking.setup();
    if (RM.help) RM.help.setup();

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
    if (RM.remote) RM.remote.setup();

    // Live-sync (периодический polling)
    if (RM.liveSync) RM.liveSync.setup();

    // Первичная загрузка
    if (RM.walkthrough) RM.walkthrough.init();

    if (RM.jobs) RM.jobs.setup();

    RM.recipes.load();
  }

  function setupActivityPing() {
    let lastPing = 0;
    const ping = () => {
      const now = Date.now();
      if (now - lastPing < 60000) return;
      lastPing = now;
      fetch(RM.api.api("api/me/activity"), { method: "POST" }).catch(() => {});
    };
    ["pointerdown", "keydown", "touchstart", "scroll"].forEach((ev) => {
      window.addEventListener(ev, ping, { passive: true });
    });
    ping();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      setupActivityPing();
      init();
    });
  } else {
    setupActivityPing();
    init();
  }
})(window.RM);