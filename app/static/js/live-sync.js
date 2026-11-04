"use strict";
(function (RM) {
  const { getJSON } = RM.api;
  const state = RM.state;

  const POLL_INTERVAL_MS = 10000;   // 10 секунд
  let timer = null;
  let lastRecipesHash = "";
  let lastPlanHash = "";
  let busy = false;

  function hash(obj) {
    try {
      return JSON.stringify(obj).length + ":" + JSON.stringify(obj).slice(0, 200);
    } catch (e) {
      return String(Date.now());
    }
  }

  function setup() {
    if (timer) clearInterval(timer);
    timer = setInterval(tick, POLL_INTERVAL_MS);
    // Первый tick через 2 секунды после загрузки — чтобы данные уже были
    setTimeout(tick, 2000);
  }

  async function tick() {
    if (busy) return;
    if (document.hidden) return;   // вкладка не в фокусе — не тратим ресурсы
    busy = true;
    try {
      await pollRecipes();
      await pollPlan();
    } catch (e) {
      // тихо игнорируем — следующая попытка через 10 секунд
    } finally {
      busy = false;
    }
  }

  async function pollRecipes() {
    try {
      const data = await getJSON("api/recipes");
      const incoming = data.recipes || [];
      const h = hash(incoming.map((r) => r.id + ":" + (r.updated_at || "")).join("|"));
      if (h === lastRecipesHash) return;
      lastRecipesHash = h;

      // Сохраняем состояние UI: если открыт детальный просмотр — обновим его
      const currentId = state.currentRecipe ? state.currentRecipe.id : null;

      state.recipes = incoming;

      // Перерисовываем список рецептов, если вкладка активна
      if (document.getElementById("panel-recipes").classList.contains("active")) {
        RM.recipes.render(state.recipes);
      }

      // Обновляем detail-view, если он открыт
      if (currentId && document.getElementById("detail-overlay").classList.contains("show")) {
        const fresh = incoming.find((x) => x.id === currentId);
        if (fresh) {
          state.currentRecipe = fresh;
          RM.detail.render();
        } else {
          // рецепт удалён на другом устройстве — закрываем
          RM.detail.close();
        }
      }
    } catch (e) {
      // ignore
    }
  }

  async function pollPlan() {
    if (!state.plannerWeekStart) return;
    try {
      const { toISO, addDays } = RM.utils;
      const monday = state.plannerWeekStart;
      const sunday = addDays(monday, 6);
      const url = `api/meal-plan?start=${toISO(monday)}&end=${toISO(sunday)}`;
      const data = await getJSON(url);
      const incoming = data.entries || [];
      const h = hash(incoming.map((e) => e.id).join("|"));
      if (h === lastPlanHash) return;
      lastPlanHash = h;

      state.plannerEntries = incoming;
      if (document.getElementById("panel-planner").classList.contains("active")) {
        RM.planner.render();
      }
    } catch (e) {
      // ignore
    }
  }

  RM.liveSync = { setup, tick };
})(window.RM);