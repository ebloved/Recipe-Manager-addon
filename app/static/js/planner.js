"use strict";
(function (RM) {
  const {
    $, escHtml, toISO, getMonday, addDays, weekTitle, isToday, WEEKDAYS_SHORT,
  } = RM.utils;
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

  // --- Подсчёт итогов по дням -----------------------------------------
  function computeDayTotals(monday) {
    const days = {};
    for (let i = 0; i < 7; i++) {
      const iso = toISO(addDays(monday, i));
      days[iso] = { calories: 0, protein: 0, fat: 0, carbohydrates: 0, count: 0 };
    }

    for (const e of state.plannerEntries) {
      const day = days[e.date];
      if (!day) continue;

      const n = e.recipe_nutrition || {};
      const rServ = parseFloat(e.recipe_servings) || 1;
      const eServ = parseFloat(e.servings) || rServ;
      const factor = rServ > 0 ? eServ / rServ : 1;

      const cal = (parseFloat(n.calories) || 0) * factor;
      const prot = (parseFloat(n.protein) || 0) * factor;
      const fat = (parseFloat(n.fat) || 0) * factor;
      const carbs = (parseFloat(n.carbohydrates) || 0) * factor;

      day.calories += cal;
      day.protein += prot;
      day.fat += fat;
      day.carbohydrates += carbs;

      if (cal > 0 || prot > 0 || fat > 0 || carbs > 0) day.count++;
    }

    return days;
  }

  function renderTotalsRow(monday, totals) {
    let hasAny = false;
    for (const k in totals) {
      if (totals[k].count > 0) { hasAny = true; break; }
    }
    if (!hasAny) return "";

    const rda = RM.RDA;

    let html = `<div class="planner-meal-label planner-totals-label">🥗<br>Итого</div>`;

    for (let i = 0; i < 7; i++) {
      const d = addDays(monday, i);
      const iso = toISO(d);
      const t = totals[iso];

      if (!t || t.count === 0) {
        html += `<div class="planner-totals-cell empty">—</div>`;
        continue;
      }

      const calPct = rda.calories ? Math.round((t.calories / rda.calories) * 100) : 0;
      const pPct = rda.protein ? Math.round((t.protein / rda.protein) * 100) : 0;
      const fPct = rda.fat ? Math.round((t.fat / rda.fat) * 100) : 0;
      const cPct = rda.carbohydrates ? Math.round((t.carbohydrates / rda.carbohydrates) * 100) : 0;

      const calClass = calPct > 120 ? "over" : calPct > 100 ? "high" : "";

      html += `<div class="planner-totals-cell ${isToday(iso) ? "today" : ""}">
        <div class="ptc-kcal ${calClass}">${Math.round(t.calories)} <span>ккал</span></div>
        <div class="ptc-sub">${calPct}% нормы · ${t.count} ${t.count === 1 ? "блюдо" : "блюд"}</div>
        <div class="ptc-macros">
          <span class="ptc-macro protein" title="Белки: ${Math.round(t.protein)} г">Б ${pPct}%</span>
          <span class="ptc-macro fat" title="Жиры: ${Math.round(t.fat)} г">Ж ${fPct}%</span>
          <span class="ptc-macro carbs" title="Углеводы: ${Math.round(t.carbohydrates)} г">У ${cPct}%</span>
        </div>
      </div>`;
    }

    return html;
  }

  // --- Отрисовка сетки -------------------------------------------------
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

    // Итоговая строка (калории + БЖУ % за день)
    const totals = computeDayTotals(monday);
    html += renderTotalsRow(monday, totals);

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

    // Клик по пустой ячейке
    container.querySelectorAll(".planner-cell.empty").forEach((cell) => {
      cell.addEventListener("click", () => {
        alert("Чтобы добавить рецепт, откройте его карточку или нажмите 📅");
      });
    });
  }

  RM.planner = { setup, load, render };
})(window.RM);