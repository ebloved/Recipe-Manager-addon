"use strict";
(function (RM) {
  const { $, escHtml, toISO, getMonday, addDays, weekTitle, isToday, WEEKDAYS_SHORT } = RM.utils;
  const { getJSON, postJSON } = RM.api;
  const state = RM.state;

  function setup() {
    $("plan-picker-close").addEventListener("click", close);
    $("plan-picker").addEventListener("click", (e) => {
      if (e.target === $("plan-picker")) close();
    });
    $("plan-picker-prev").addEventListener("click", () => {
      state.pickerWeekStart = addDays(state.pickerWeekStart, -7);
      loadAndRenderPicker();
    });
    $("plan-picker-next").addEventListener("click", () => {
      state.pickerWeekStart = addDays(state.pickerWeekStart, 7);
      loadAndRenderPicker();
    });
    $("plan-picker-servings").addEventListener("change", (e) => {
      const v = parseInt(e.target.value, 10);
      state.pickerServings = (v && v > 0) ? v : 1;
      e.target.value = state.pickerServings;
    });
  }

  async function open(recipe) {
    state.pickerRecipe = recipe;
    state.pickerServings = 1;
    state.pickerWeekStart = getMonday(new Date());
    $("plan-picker-title").textContent = `Добавить «${recipe.name}» в план`;
    $("plan-picker-servings").value = state.pickerServings;
    $("plan-picker").classList.add("show");
    await loadAndRenderPicker();
  }

  function close() {
    $("plan-picker").classList.remove("show");
    state.pickerRecipe = null;
  }

  async function loadAndRenderPicker() {
    const monday = state.pickerWeekStart;
    const sunday = addDays(monday, 6);
    $("plan-picker-week-title").textContent = weekTitle(monday);

    let entries = [];
    try {
      const data = await getJSON(`api/meal-plan?start=${toISO(monday)}&end=${toISO(sunday)}`);
      entries = data.entries || [];
    } catch (e) { /* ignore */ }

    renderGrid($("plan-picker-grid"), monday, entries);
  }

  function renderGrid(container, monday, entries) {
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
        const hasEntries = entries.some((e) => e.date === iso && e.meal_type === meal);
        const cls = "planner-cell" + (hasEntries ? " already-has" : " empty");
        html += `<div class="${cls}" data-date="${iso}" data-meal="${meal}"></div>`;
      }
    }

    container.innerHTML = html;

    container.querySelectorAll(".planner-cell").forEach((cell) => {
      cell.addEventListener("click", () => onPick(cell.dataset.date, cell.dataset.meal));
    });
  }

  async function onPick(date, meal) {
    if (!state.pickerRecipe) return;
    try {
      await postJSON("api/meal-plan", {
        recipe_id: state.pickerRecipe.id,
        date,
        meal_type: meal,
        servings: state.pickerServings,
      });
      close();
      // Обновляем планировщик, если открыт
      if ($("panel-planner").classList.contains("active")) {
        RM.planner.load();
      }
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  RM.planPicker = { setup, open, close };
})(window.RM);