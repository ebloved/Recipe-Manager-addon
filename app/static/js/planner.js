"use strict";
(function (RM) {
  const { $, escHtml, toISO, getMonday, addDays, weekTitle, isToday, WEEKDAYS_SHORT } = RM.utils;
  const { getJSON, del } = RM.api;
  const state = RM.state;

  function setup() {
    if (!state.plannerWeekStart) state.plannerWeekStart = getMonday(new Date());

    $("planner-prev").addEventListener("click", () => {
      state.plannerWeekStart = addDays(state.plannerWeekStart, -7);
      load();
    });
    $("planner-next").addEventListener("click", () => {
      state.plannerWeekStart = addDays(state.plannerWeekStart, 7);
      load();
    });
    $("planner-today").addEventListener("click", () => {
      state.plannerWeekStart = getMonday(new Date());
      load();
    });
  }

  async function load() {
    const monday = state.plannerWeekStart;
    const sunday = addDays(monday, 6);
    $("planner-title").textContent = weekTitle(monday);

    try {
      const data = await getJSON(`api/meal-plan?start=${toISO(monday)}&end=${toISO(sunday)}`);
      state.plannerEntries = data.entries || [];
    } catch (e) {
      state.plannerEntries = [];
    }

    render();
  }

  function render() {
    const monday = state.plannerWeekStart;
    const entries = state.plannerEntries;
    const container = $("planner-grid");
    const MEALS = RM.MEALS;
    const MEAL_LABELS = RM.MEAL_LABELS;

    let html = '<div class="planner-cell-header" style="background:transparent"></div>';
    for (let i = 0; i < 7; i++) {
      const d = addDays(monday, i);
      const iso = toISO(d);
      const cls = isToday(iso) ? "today" : "";
      html += `<div class="planner-cell-header ${cls}">
        <span class="day-name">${WEEKDAYS_SHORT[i]}</span>
        <span class="day-num">${d.getDate()}</span>
      </div>`;
    }

    for (const meal of MEALS) {
      html += `<div class="planner-meal-label">${MEAL_LABELS[meal]}</div>`;
      for (let i = 0; i < 7; i++) {
        const d = addDays(monday, i);
        const iso = toISO(d);
        const cellEntries = entries.filter((e) => e.date === iso && e.meal_type === meal);
        const cellCls = "planner-cell" + (cellEntries.length ? "" : " empty");

        html += `<div class="${cellCls}" data-date="${iso}" data-meal="${meal}">`;
        for (const e of cellEntries) {
          html += `<div class="plan-entry" data-entry-id="${escHtml(e.id)}" data-recipe-id="${escHtml(e.recipe_id)}">
            <span class="pe-name">${escHtml(e.recipe_name || "(без названия)")}</span>
            <button class="pe-remove" data-remove-id="${escHtml(e.id)}" title="Убрать">×</button>
          </div>`;
        }
        html += `</div>`;
      }
    }

    container.innerHTML = html;

    // Клик по записи — открыть рецепт
    container.querySelectorAll(".plan-entry").forEach((el) => {
      el.addEventListener("click", (ev) => {
        if (ev.target.classList.contains("pe-remove")) return;
        const recipeId = el.dataset.recipeId;
        const recipe = state.recipes.find((r) => r.id === recipeId);
        if (recipe) {
          RM.detail.open(recipe);
        } else {
          // Подгружаем рецепт и открываем
          RM.api.getJSON(`api/recipes/${recipeId}`)
            .then((d) => RM.detail.open(d.recipe))
            .catch(() => {});
        }
      });
    });

    // Удаление записи
    container.querySelectorAll(".pe-remove").forEach((btn) => {
      btn.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const entryId = btn.dataset.removeId;
        try {
          await del(`api/meal-plan/${entryId}`);
          state.plannerEntries = state.plannerEntries.filter((x) => x.id !== entryId);
          render();
        } catch (err) {
          alert("Ошибка: " + err.message);
        }
      });
    });

    // Клик по пустой ячейке — открыть picker с произвольным рецептом (не реализовано)
    container.querySelectorAll(".planner-cell.empty").forEach((cell) => {
      cell.addEventListener("click", () => {
        // Можно открыть поиск рецепта — пока заглушка
        alert("Чтобы добавить рецепт, откройте его карточку или нажмите 📅");
      });
    });
  }

  RM.planner = { setup, load, render };
})(window.RM);