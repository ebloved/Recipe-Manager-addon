"use strict";
(function (RM) {
  const { $, escHtml, formatTime, getMonday, addDays, toISO } = RM.utils;
  const { getJSON, postJSON } = RM.api;
  const state = RM.state;

  const WEEKDAYS_FULL = ["воскресенье","понедельник","вторник","среда","четверг","пятница","суббота"];
  const MONTHS_GEN = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"];

  let currentDate = null;
  let currentMeal = null;

  function setup() {
    $("recipe-picker-close").addEventListener("click", close);
    $("recipe-picker-overlay").addEventListener("click", (e) => {
      if (e.target === $("recipe-picker-overlay")) close();
    });
    $("recipe-picker-search").addEventListener("input", renderList);
  }

  async function open(date, meal) {
    currentDate = date;
    currentMeal = meal;

    const label = (RM.MEAL_LABELS[meal] || meal).toLowerCase();
    $("recipe-picker-title").textContent = `Добавить в ${label}`;
    $("recipe-picker-subtitle").textContent = formatDateFull(date);
    $("recipe-picker-search").value = "";
    $("recipe-picker-servings").value = "1";

    $("recipe-picker-overlay").classList.add("show");
    setTimeout(() => $("recipe-picker-search").focus(), 60);

    if (!state.recipes.length) {
      try {
        const data = await getJSON("api/recipes");
        state.recipes = data.recipes || [];
      } catch (e) {
        state.recipes = [];
      }
    }
    renderList();
  }

  function close() {
    $("recipe-picker-overlay").classList.remove("show");
    currentDate = null;
    currentMeal = null;
  }

  function formatDateFull(iso) {
    const d = new Date(iso + "T00:00:00Z");
    return `${WEEKDAYS_FULL[d.getUTCDay()]}, ${d.getUTCDate()} ${MONTHS_GEN[d.getUTCMonth()]}`;
  }

  function renderList() {
    const list = $("recipe-picker-list");
    const q = ($("recipe-picker-search").value || "").trim().toLowerCase();

    let recipes = state.recipes.slice();
    if (q) {
      recipes = recipes.filter((r) => {
        if ((r.name || "").toLowerCase().includes(q)) return true;
        if ((r.description || "").toLowerCase().includes(q)) return true;
        for (const arr of [r.tags, r.courses, r.categories]) {
          if (Array.isArray(arr) && arr.some((x) => String(x).toLowerCase().includes(q))) return true;
        }
        return false;
      });
    }

    if (!recipes.length) {
      list.innerHTML = `<div class="picker-empty">${q ? "Ничего не найдено" : "Рецептов пока нет"}</div>`;
      return;
    }

    list.innerHTML = recipes.map((r) => {
      const t = r.total_time || r.time || ((r.prep_time || 0) + (r.cook_time || 0)) || null;
      const img = r.image_url
        ? `<img class="picker-thumb" src="${escHtml(r.image_url)}" alt="">`
        : `<div class="picker-thumb picker-placeholder">🍽</div>`;
      const meta = [];
      if (t) meta.push("⏱ " + formatTime(t));
      if (r.servings) meta.push("👥 " + r.servings);
      const tags = (r.tags || []).slice(0, 3)
        .map((x) => `<span class="picker-tag">${escHtml(x)}</span>`).join("");

      return `<div class="picker-item" data-recipe-id="${escHtml(r.id)}">
        ${img}
        <div class="picker-info">
          <span class="picker-name">${escHtml(r.name || "(без названия)")}</span>
          ${meta.length ? `<span class="picker-meta">${meta.join(" · ")}</span>` : ""}
          ${tags ? `<div class="picker-tags">${tags}</div>` : ""}
        </div>
      </div>`;
    }).join("");

    list.querySelectorAll(".picker-item").forEach((el) => {
      el.addEventListener("click", () => pick(el.dataset.recipeId));
    });
  }

  async function pick(recipeId) {
    const sVal = parseInt($("recipe-picker-servings").value, 10);
    const servings = (sVal && sVal > 0) ? sVal : 1;
    if (!currentDate || !currentMeal) return;
    try {
      await postJSON("api/meal-plan", {
        recipe_id: recipeId,
        date: currentDate,
        meal_type: currentMeal,
        servings: servings,
      });
      close();
      if ($("panel-planner").classList.contains("active")) {
        RM.planner.load();
      }
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  RM.recipePicker = { setup, open, close };
})(window.RM);