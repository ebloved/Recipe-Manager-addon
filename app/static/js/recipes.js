"use strict";
(function (RM) {
  const { $, escHtml, formatTime } = RM.utils;
  const { getJSON } = RM.api;
  const state = RM.state;

  let searchTimer = null;
  state.recipesSort = "default";
  
  function getActiveProfile() {
    return (RM.profiles && RM.profiles.getActive) ? RM.profiles.getActive() : null;
  }
  
  function fitsProfile(recipe, profile) {
    if (!profile) return true;
    const c = profile.constraints || {};
    const num = (v) => (v === null || v === undefined || v === "") ? null : Number(v);
    if (c.max_calories_per_serving != null) {
      const cal = num((recipe.nutrition || {}).calories);
      if (cal == null || cal > Number(c.max_calories_per_serving)) return false;
    }
    if (c.max_total_time_min != null) {
      let t = num(recipe.total_time);
      if (t == null) t = num(recipe.time);
      if (t == null) {
        const pc = (recipe.prep_time || 0) + (recipe.cook_time || 0);
        t = pc > 0 ? pc : null;
      }
      if (t == null || t > Number(c.max_total_time_min)) return false;
    }
    if (c.max_active_time_min != null) {
      // v1.9.0: только active_time, без fallback на prep_time.
      // Если не оценён — рецепт не подходит (оцени через «🎯 Оценить active_time»).
      const active = num(recipe.active_time);
      if (active == null || active > Number(c.max_active_time_min)) return false;
    }
    if (c.min_protein_per_serving_g != null) {
      const p = num((recipe.nutrition || {}).protein);
      if (p == null || p < Number(c.min_protein_per_serving_g)) return false;
    }
    if (c.max_sugar_per_serving_g != null) {
      const sg = num((recipe.nutrition || {}).sugar);
      if (sg == null || sg > Number(c.max_sugar_per_serving_g)) return false;
    }
    return true;
  }
  
  function toggleProfileFilter() {
    state.profileFilterActive = !state.profileFilterActive;
    filterAndRender();
  }
  
  function updateFilterButton() {
    const btn = $("profile-filter-btn");
    if (!btn) return;
    const active = getActiveProfile();
    if (!active) {
      btn.style.display = "none";
      state.profileFilterActive = false;
      return;
    }
    btn.style.display = "";
    const total = state.recipes.length;
    const fitting = state.recipes.filter((r) => fitsProfile(r, active)).length;
    btn.textContent = `🎯 Только под профиль (${fitting}/${total})`;
    btn.title = active.name || "Активный профиль";
    if (state.profileFilterActive) btn.classList.add("profile-filter-active");
    else btn.classList.remove("profile-filter-active");
  }

  function setup() {
      $("search").addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => filterAndRender(), 200);
      });
      const filterBtn = $("profile-filter-btn");
      if (filterBtn) filterBtn.addEventListener("click", toggleProfileFilter);
      const estBtn = $("estimate-all-btn");
      if (estBtn) estBtn.addEventListener("click", estimateAllActiveTime);
    }

    async function estimateAllActiveTime() {
      const btn = $("estimate-all-btn");
      if (!btn) return;
      if (!confirm("Оценить active_time для всех рецептов? Это может занять несколько минут (LLM вызов на каждый рецепт).")) return;
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = "⏳ Запуск…";
      try {
        const data = await RM.api.postJSON("api/recipes/estimate-active-time?force=false", {});
        const jobId = data.job_id;
        if (!jobId) { alert("Нет job_id в ответе"); return; }
        const t0 = Date.now();
        while (true) {
          await new Promise((r) => setTimeout(r, 2000));
          const elapsed = Math.round((Date.now() - t0) / 1000);
          btn.textContent = `⏳ ${elapsed}s…`;
          let j;
          try { j = await RM.api.getJSON(`api/generator/jobs/${jobId}`); }
          catch (e) { if (/404/.test(e.message || "")) { alert("Задача потеряна"); return; } continue; }
          if (j.status === "done") {
            alert(`Готово за ${elapsed}s. Обновлено: ${j.created || 0}`);
            await load();
            return;
          }
          if (j.status === "error") { alert("Ошибка: " + (j.error || "—")); return; }
          if (elapsed > 900) { alert("Таймаут 15 минут"); return; }
        }
      } catch (err) {
        alert("Ошибка: " + err.message);
      } finally {
        btn.disabled = false;
        btn.textContent = orig;
      }
    }

  async function load() {
      const container = $("recipes-container");
      if (state.recipes.length) {
        filterAndRender();
        return;
      }
      container.innerHTML = '<div class="loading"><span class="spinner"></span> Загрузка…</div>';
      try {
        const data = await getJSON("api/recipes");
        state.recipes = data.recipes || [];
        filterAndRender();
      } catch (err) {
        container.innerHTML = `<div class="empty"><div class="icon">⚠️</div><p>Не удалось загрузить: ${escHtml(err.message)}</p></div>`;
      }
    }

      function sortRecipes(arr) {
      const mode = state.recipesSort || "default";
      if (mode === "default" || !mode) return arr;
      
      const getAct = (r) => r.active_time != null ? r.active_time : 99999;
      const getTot = (r) => r.total_time || r.time || ((r.prep_time || 0) + (r.cook_time || 0)) || 99999;
      
      return [...arr].sort((a, b) => {
        if (mode === "active_asc") return getAct(a) - getAct(b);
        if (mode === "total_asc") return getTot(a) - getTot(b);
        
        if (mode === "combined") {
          const diffAct = getAct(a) - getAct(b);
          if (diffAct !== 0) return diffAct;
          return getTot(a) - getTot(b);
        }
        
        if (mode === "course_asc") {
          const ca = (a.courses && a.courses[0]) || "я";
          const cb = (b.courses && b.courses[0]) || "я";
          if (ca !== cb) return ca.localeCompare(cb);
          return (a.name || "").localeCompare(b.name || "");
        }
        
        if (mode === "name_asc") return (a.name || "").localeCompare(b.name || "");
        
        return 0;
      });
    }

function filterAndRender(q) {
      const query = (q !== undefined ? q : ($("search").value || "")).trim();
      const active = getActiveProfile();
      const applyProfile = state.profileFilterActive && active;

      let filtered = state.recipes;
      if (applyProfile) filtered = filtered.filter((r) => fitsProfile(r, active));
      if (query) {
        const lower = query.toLowerCase();
        filtered = filtered.filter((r) => {
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
      }
      filtered = sortRecipes(filtered);
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
    const sortSel = $("sort-select");
    if (sortSel) {
      sortSel.addEventListener("change", (e) => {
        state.recipesSort = e.target.value;
        filterAndRender();
      });
    }

  }

  function cardFor(r) {
    const card = document.createElement("div");
    card.className = "recipe-card" + (r.image_url ? "" : " no-thumb");
    card.addEventListener("click", () => RM.detail.open(r));

    if (r.image_url) {
      const thumb = document.createElement("div");
      thumb.className = "recipe-thumb";
      const img = document.createElement("img");
      img.src = r.image_url;
      img.alt = r.name || "";
      img.loading = "lazy";
      thumb.appendChild(img);
      card.appendChild(thumb);
    }

    const planBtn = document.createElement("button");
    planBtn.className = "card-plan-btn";
    planBtn.title = "Добавить в план";
    planBtn.textContent = "📅";
    planBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      RM.planPicker.open(r);
    });
    card.appendChild(planBtn);

    const body = document.createElement("div");
    body.className = "recipe-body";

    const name = document.createElement("h3");
    name.className = "recipe-name";
    name.textContent = r.name || "(без названия)";
    body.appendChild(name);

    const meta = document.createElement("div");
    meta.className = "recipe-meta";
    const _activeProfile = getActiveProfile();
    if (_activeProfile && fitsProfile(r, _activeProfile)) {
      const fitChip = chip("🎯", false);
      fitChip.classList.add("fit");
      fitChip.title = "Подходит под профиль: " + (_activeProfile.name || "");
      meta.appendChild(fitChip);
    }
    const t = r.total_time || r.time || ((r.prep_time || 0) + (r.cook_time || 0)) || null;
    if (t) meta.appendChild(chip("⏱ " + formatTime(t), false));
    if (r.servings) meta.appendChild(chip("👥 " + r.servings, false));
    if (r.active_time != null) {
      const at = chip("🎯 " + r.active_time + " мин акт." + (r.active_time_estimated ? "*" : ""), false);
      at.title = "Активное время (сколько вы заняты готовкой)" + (r.active_time_estimated ? ". Оценка ИИ" : "");
      meta.appendChild(at);
    }
    
    // B3: Индикатор связок продуктов
    const ings = r.ingredients || [];
    if (ings.length > 0) {
      let linked = 0;
      for (const ing of ings) {
        if (typeof ing !== "string" && ing.product_id) linked++;
      }
      const badge = chip(`🔗 ${linked}/${ings.length}`, false);
      badge.title = "Связано с базой продуктов";
      if (linked === ings.length) badge.classList.add("linked-all");
      else if (linked > 0) badge.classList.add("linked-partial");
      else badge.classList.add("linked-none");
      meta.appendChild(badge);
    }
    
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

  RM.recipes = { setup, load, filterAndRender, render, fitsProfile, updateFilterButton };
})(window.RM);