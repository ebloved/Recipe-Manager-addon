"use strict";
(function (RM) {
  const { $, escHtml, formatTime } = RM.utils;
  const { postJSON, getJSON } = RM.api;

  function setup() {
    $("finder-search-btn").addEventListener("click", search);
    $("finder-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") search();
    });
  }

  async function search() {
    const query = $("finder-input").value.trim();
    const container = $("finder-results");
    const btn = $("finder-search-btn");

    if (!query) {
      container.innerHTML = `<div class="empty">Введите продукты через запятую (например: курица, лук, морковь)</div>`;
      return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Поиск…';
    container.innerHTML = '<div class="loading"><span class="spinner"></span> Подбираем рецепты…</div>';

    try {
      const data = await postJSON("api/recipes/find-by-ingredients", { ingredients: query });
      renderResults(data.recipes || []);
    } catch (e) {
      container.innerHTML = `<div class="empty" style="color:var(--danger)">Ошибка: ${escHtml(e.message)}</div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = "Найти рецепты";
    }
  }

  function renderResults(recipes) {
    const container = $("finder-results");
    if (!recipes.length) {
      container.innerHTML = '<div class="empty"><div class="icon">🤷‍♂️</div><p>Ничего не нашлось. Попробуйте добавить больше продуктов.</p></div>';
      return;
    }

    const grid = document.createElement("div");
    grid.className = "recipe-grid";
    
    for (const r of recipes) {
      grid.appendChild(renderCard(r));
    }
    container.innerHTML = "";
    container.appendChild(grid);
  }

  function renderCard(r) {
    const card = document.createElement("div");
    card.className = "recipe-card no-thumb";
    card.style.cursor = "pointer";
    card.addEventListener("click", () => RM.detail.open(r));

    const body = document.createElement("div");
    body.className = "recipe-body";

    const name = document.createElement("h3");
    name.className = "recipe-name";
    name.textContent = r.name || "(без названия)";
    body.appendChild(name);

    // Мета-информация
    const meta = document.createElement("div");
    meta.className = "recipe-meta";
    const t = r.total_time || r.time || ((r.prep_time || 0) + (r.cook_time || 0)) || null;
    if (t) meta.appendChild(chip("⏱ " + formatTime(t), false));
    
    // Прогресс совпадения
    const scorePct = Math.round(r._match_score * 100);
    const scoreChip = chip(`Совпадение: ${scorePct}%`, false);
    scoreChip.style.background = scorePct > 60 ? "rgba(46,160,67,0.15)" : "rgba(245,166,35,0.15)";
    scoreChip.style.color = scorePct > 60 ? "var(--success)" : "#f5a623";
    meta.appendChild(scoreChip);
    body.appendChild(meta);

    // Найденные и недостающие ингредиенты
    const ingBox = document.createElement("div");
    ingBox.className = "finder-ingredients";
    
    if (r._matched.length) {
      const m = document.createElement("div");
      m.className = "finder-match-row";
      m.innerHTML = `<span class="finder-label">Есть:</span> ` + 
        r._matched.slice(0, 5).map(x => `<span class="finder-chip match">${escHtml(x)}</span>`).join("") +
        (r._matched.length > 5 ? ` <span class="finder-chip">+${r._matched.length - 5}</span>` : "");
      ingBox.appendChild(m);
    }
    
    if (r._missing.length) {
      const m = document.createElement("div");
      m.className = "finder-match-row";
      m.innerHTML = `<span class="finder-label">Купить:</span> ` + 
        r._missing.slice(0, 5).map(x => `<span class="finder-chip missing">${escHtml(x)}</span>`).join("") +
        (r._missing.length > 5 ? ` <span class="finder-chip">+${r._missing.length - 5}</span>` : "");
      ingBox.appendChild(m);
    }

    body.appendChild(ingBox);
    card.appendChild(body);
    return card;
  }

  function chip(text, isTag) {
    const el = document.createElement("span");
    el.className = "meta-chip" + (isTag ? " tag" : "");
    el.textContent = text;
    return el;
  }

  RM.finder = { setup };
})(window.RM);
