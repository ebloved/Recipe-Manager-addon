"use strict";
(function (RM) {
  const { $, escHtml, formatTime } = RM.utils;
  const { getJSON } = RM.api;
  const state = RM.state;

  let searchTimer = null;

  function setup() {
    $("search").addEventListener("input", (e) => {
      clearTimeout(searchTimer);
      const q = e.target.value.trim();
      searchTimer = setTimeout(() => filterAndRender(q), 200);
    });
  }

  async function load() {
    const container = $("recipes-container");
    if (state.recipes.length) {
      render(state.recipes);
      return;
    }
    container.innerHTML = '<div class="loading"><span class="spinner"></span> Загрузка…</div>';
    try {
      const data = await getJSON("api/recipes");
      state.recipes = data.recipes || [];
      render(state.recipes);
    } catch (err) {
      container.innerHTML = `<div class="empty"><div class="icon">⚠️</div><p>Не удалось загрузить: ${escHtml(err.message)}</p></div>`;
    }
  }

  function filterAndRender(q) {
    if (!q) { render(state.recipes); return; }
    const lower = q.toLowerCase();
    const filtered = state.recipes.filter((r) => {
      if ((r.name || "").toLowerCase().includes(lower)) return true;
      if ((r.description || "").toLowerCase().includes(lower)) return true;
      for (const arr of [r.tags, r.courses, r.categories, r.collections]) {
        if (Array.isArray(arr) && arr.some((t) => String(t).toLowerCase().includes(lower))) return true;
      }
      for (const ing of r.ingredients || []) {
        const name = typeof ing === "string" ? ing : ing.name;
        if (name && String(name).toLowerCase().includes(lower)) return true;
      }
      return false;
    });
    render(filtered);
  }

  function render(recipes) {
    const container = $("recipes-container");
    if (!recipes.length) {
      container.innerHTML = '<div class="empty"><div class="icon">📖</div><p>Рецептов пока нет.</p></div>';
      return;
    }
    const grid = document.createElement("div");
    grid.className = "recipe-grid";
    for (const r of recipes) {
      grid.appendChild(cardFor(r));
    }
    container.innerHTML = "";
    container.appendChild(grid);
  }

  function cardFor(r) {
    const card = document.createElement("div");
    card.className = "recipe-card";
    card.addEventListener("click", () => RM.detail.open(r));

    const thumb = document.createElement("div");
    thumb.className = "recipe-thumb";
    if (r.image_url) {
      const img = document.createElement("img");
      img.src = r.image_url;
      img.alt = r.name || "";
      img.loading = "lazy";
      thumb.appendChild(img);
    } else {
      thumb.textContent = "🍽";
    }

    const planBtn = document.createElement("button");
    planBtn.className = "card-plan-btn";
    planBtn.title = "Добавить в план";
    planBtn.textContent = "📅";
    planBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      RM.planPicker.open(r);
    });
    thumb.appendChild(planBtn);
    card.appendChild(thumb);

    const body = document.createElement("div");
    body.className = "recipe-body";

    const name = document.createElement("h3");
    name.className = "recipe-name";
    name.textContent = r.name || "(без названия)";
    body.appendChild(name);

    const meta = document.createElement("div");
    meta.className = "recipe-meta";
    const t = r.total_time || r.time || ((r.prep_time || 0) + (r.cook_time || 0)) || null;
    if (t) meta.appendChild(chip("⏱ " + formatTime(t), false));
    if (r.servings) meta.appendChild(chip("👥 " + r.servings, false));
    for (const tag of (r.tags || []).slice(0, 3)) meta.appendChild(chip(tag, true));
    body.appendChild(meta);
    card.appendChild(body);
    return card;
  }

  function chip(text, isTag) {
    const el = document.createElement("span");
    el.className = "meta-chip" + (isTag ? " tag" : "");
    el.textContent = text;
    return el;
  }

  RM.recipes = { setup, load, filterAndRender, render };
})(window.RM);