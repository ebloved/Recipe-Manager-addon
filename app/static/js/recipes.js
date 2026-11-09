"use strict";
(function (RM) {
  const { $, escHtml, formatTime } = RM.utils;
  const { getJSON, postJSON } = RM.api;
  const state = RM.state;

  let searchTimer = null;
  state.recipesSort = "name_asc";
  const nameCollator = new Intl.Collator("ru", {
    sensitivity: "base",
    numeric: true,
  });
  state.recipeKind = "all";
  state.deletedRecipes = [];
  state.trashLoaded = false;
  
  function getActiveProfile() {
    return (RM.profiles && RM.profiles.getActive) ? RM.profiles.getActive() : null;
  }
  
  function recipeFilterText(recipe) {
    const parts = [recipe && recipe.name, recipe && recipe.description];
    for (const key of ["tags", "courses", "categories", "collections", "category"]) {
      const value = recipe ? recipe[key] : null;
      const items = Array.isArray(value) ? value : [value];
      for (const item of items) if (item) parts.push(String(item));
    }
    for (const ing of (recipe && recipe.ingredients) || []) {
      if (typeof ing === "string") parts.push(ing);
      else if (ing && ing.name) parts.push(ing.name);
    }
    return parts.join(" ").toLowerCase().replace(/ё/g, "е");
  }

  function fitsProfile(recipe, profile) {
    if (!profile) return true;
    const c = profile.constraints || {};
    const num = (v) => (v === null || v === undefined || v === "") ? null : Number(v);
    if (
      RM.matchAllergens
      && c.avoid_groups
      && c.avoid_groups.length
      && RM.matchAllergens(recipe, c.avoid_groups).length
    ) {
      return false;
    }
    const filterText = recipeFilterText(recipe);
    for (const item of c.avoid_ingredients || []) {
      const needle = String(item || "").trim().toLowerCase().replace(/ё/g, "е");
      if (needle && filterText.includes(needle)) return false;
    }
    for (const item of c.avoid_methods || []) {
      const needle = String(item || "").trim().toLowerCase().replace(/ё/g, "е");
      if (needle && filterText.includes(needle)) return false;
    }
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
    const groups = buildGroups(state.recipes);
    const total = groups.length;
    const fitting = groups.filter((g) => fitsProfile(g.display, active)).length;
    btn.textContent = `🎯 Только под профиль (${fitting}/${total})`;
    btn.title = active.name || "Активный профиль";
    if (state.profileFilterActive) btn.classList.add("profile-filter-active");
    else btn.classList.remove("profile-filter-active");
  }

  function kindOf(r) {
    const values = [
      ...(r.tags || []),
      ...(r.courses || []),
      ...(r.categories || []),
      r.category || "",
    ].map((x) => String(x).toLowerCase());
    if (values.some((x) => x.includes("салат"))) return "salad";
    if (values.some((x) => x.includes("гарнир") && !x.includes("нужен гарнир"))) return "side";
    if (values.some((x) => x.includes("десерт") || x.includes("выпечка") || x.includes("завтрак"))) {
      return "other";
    }
    return "main";
  }

  function showSideRecipes() {
    return !RM.prefs || RM.prefs.getShowSideRecipes();
  }

  function applySideVisibility() {
    const show = showSideRecipes();
    const sideTab = document.querySelector('.recipe-kind-tab[data-kind="side"]');
    if (sideTab) sideTab.style.display = show ? "" : "none";
    if (!show && state.recipeKind === "side") {
      state.recipeKind = "all";
      document.querySelectorAll(".recipe-kind-tab").forEach((x) => {
        x.classList.toggle("active", x.dataset.kind === "all");
      });
    }
    return show;
  }

  function setupKindTabs() {
    document.querySelectorAll(".recipe-kind-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        const kind = btn.dataset.kind;
        if (kind === "cooking") {
          RM.tabs.activateTab("cooking");
          return;
        }
        state.recipeKind = kind || "all";
        document.querySelectorAll(".recipe-kind-tab").forEach((x) => {
          x.classList.toggle("active", x === btn);
        });
        filterAndRender();
      });
    });
  }

  function setup() {
      setupKindTabs();
      $("search").addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => filterAndRender(), 200);
      });
      const filterBtn = $("profile-filter-btn");
      if (filterBtn) filterBtn.addEventListener("click", toggleProfileFilter);
      const ownerSel = $("filter-owner");
      if (ownerSel) ownerSel.addEventListener("change", () => {
        if (ownerSel.value === "trash") loadTrash();
        else if (!state.recipes.length) load();
        else filterAndRender();
      });
      const sortSel = $("sort-select");
      if (sortSel) {
        state.recipesSort = sortSel.value || "name_asc";
        sortSel.addEventListener("change", (e) => {
          state.recipesSort = e.target.value;
          filterAndRender();
        });
      }
      const hiddenCb = $("show-hidden-cb");
      if (hiddenCb) hiddenCb.addEventListener("change", () => load(true));
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

  async function load(force = false) {
      const container = $("recipes-container");
      if (force) state.recipes = [];
      if (state.recipes.length) {
        filterAndRender();
        return;
      }
      container.innerHTML = '<div class="loading"><span class="spinner"></span> Загрузка…</div>';
      try {
        const showHidden = $("show-hidden-cb")?.checked;
      const url = showHidden ? "api/recipes?show_hidden=true" : "api/recipes";
      const data = await getJSON(url);
        state.recipes = data.recipes || [];
        filterAndRender();
      } catch (err) {
        container.innerHTML = `<div class="empty"><div class="icon">⚠️</div><p>Не удалось загрузить: ${escHtml(err.message)}</p></div>`;
      }
    }

      function sortRecipes(arr) {
      const mode = state.recipesSort || "name_asc";
      if (!mode) return arr;
      
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
          if (ca !== cb) return nameCollator.compare(ca, cb);
          return nameCollator.compare(a.name || "", b.name || "");
        }
        
        if (mode === "name_asc") {
          return nameCollator.compare(a.name || "", b.name || "");
        }
        
        return 0;
      });
    }

function currentUserId() {
  return RM.state && RM.state.user ? RM.state.user.id : null;
}

  // Один базовый рецепт + его личная версия = одна карточка.
  function buildGroups(recipes) {
    const list = Array.isArray(recipes) ? recipes : [];
    const uid = currentUserId();
    const clones = new Map();
    const adaptedChildren = new Set();
    for (const r of list) {
      if (!r) continue;
      for (const childId of Object.values(r.adapted_versions || {})) {
        if (childId) adaptedChildren.add(String(childId));
      }
      if (!r.personal_of) continue;
      if (!uid || r.owner_id === uid) clones.set(String(r.personal_of), r);
    }
    const bases = list.filter(
      (r) => r && !r.personal_of && !adaptedChildren.has(String(r.id))
    );
    const baseIds = new Set(bases.map((r) => String(r.id)));
    const groups = bases.map((base) => {
      const personal = clones.get(String(base.id)) || null;
      const selected = !!(personal && personal.personal_selected !== false);
      return { base, personal, selected, display: selected ? personal : base };
    });
    for (const [baseId, personal] of clones) {
      if (!baseIds.has(baseId)) {
        groups.push({ base: personal, personal: null, selected: true, display: personal });
      }
    }
    return groups;
  }

  function recipeMatches(r, lower) {
    if (!r) return false;
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
  }

  function sortGroups(groups) {
    const ordered = sortRecipes(groups.map((g) => g.display));
    const order = new Map(ordered.map((r, i) => [String(r.id), i]));
    return groups.slice().sort(
      (a, b) => (order.get(String(a.display.id)) ?? 0) - (order.get(String(b.display.id)) ?? 0)
    );
  }

  async function selectPersonalVersion(group, selected) {
    if (!group || !group.personal) return;
    try {
      await postJSON(`api/recipes/${encodeURIComponent(group.base.id)}/personal-select`, {
        selected: !!selected,
      });
      const clone = state.recipes.find((r) => r.id === group.personal.id);
      if (clone) clone.personal_selected = !!selected;
      filterAndRender();
    } catch (e) {
      alert("Ошибка переключения версии: " + e.message);
    }
  }

function filterAndRender(q) {
      const showSides = applySideVisibility();
      const query = (q !== undefined ? q : ($("search").value || "")).trim();
      const active = getActiveProfile();
      const applyProfile = state.profileFilterActive && active;
      const ownerFilter = $("filter-owner")?.value || "all";

      if (ownerFilter === "trash") {
        if (!state.trashLoaded) {
          loadTrash();
        } else {
          renderTrash(query);
        }
        return;
      }

      let groups = buildGroups(state.recipes);
      if (!showSides) {
        groups = groups.filter(
          (g) => kindOf(g.base) !== "side" && kindOf(g.display) !== "side"
        );
      }
      if (ownerFilter === "my" && RM.state.user) {
        groups = groups.filter(
          (g) => g.base.owner_id === RM.state.user.id || !!g.personal
        );
      }
      if (applyProfile) {
        groups = groups.filter((g) => fitsProfile(g.display, active));
      }
      if (state.recipeKind && state.recipeKind !== "all") {
        groups = groups.filter((g) => kindOf(g.display) === state.recipeKind);
      }
      if (query) {
        const lower = query.toLowerCase();
        groups = groups.filter(
          (g) => recipeMatches(g.base, lower) || (g.personal && recipeMatches(g.personal, lower))
        );
      }
      groups = sortGroups(groups);
      renderGroups(groups);
    }

  async function loadTrash() {
    const container = $("recipes-container");
    container.innerHTML = '<div class="loading"><span class="spinner"></span> Загрузка корзины…</div>';
    try {
      const data = await getJSON("api/recipes/trash");
      state.deletedRecipes = data.recipes || [];
      state.trashLoaded = true;
      renderTrash(($("search").value || "").trim());
    } catch (err) {
      container.innerHTML = `<div class="empty"><div class="icon">⚠️</div><p>Не удалось загрузить корзину: ${escHtml(err.message)}</p></div>`;
    }
  }

  function renderTrash(query) {
    const container = $("recipes-container");
    let items = state.deletedRecipes || [];
    if (query) {
      const q = query.toLowerCase();
      items = items.filter((r) =>
        String(r.name || "").toLowerCase().includes(q)
        || String(r.description || "").toLowerCase().includes(q)
      );
    }
    if (!items.length) {
      container.innerHTML = '<div class="empty"><div class="icon">🗑</div><p>Корзина пуста.</p></div>';
      return;
    }
    container.innerHTML = `<div class="recipe-grid">${items.map((r) => {
      const thumb = r.image_thumb_url || r.image_url;
      const date = r.deleted_at ? new Date(r.deleted_at).toLocaleString("ru-RU") : "—";
      return `<div class="recipe-card deleted">
        ${thumb ? `<div class="recipe-thumb"><img src="${escHtml(RM.utils.mediaUrl(thumb))}" alt="" loading="lazy" decoding="async"></div>` : `<div class="recipe-thumb picker-placeholder">🗑</div>`}
        <div class="recipe-body">
          <div class="deleted-badge">Удалён ${escHtml(date)}</div>
          <h3 class="recipe-name">${escHtml(r.name || "(без названия)")}</h3>
          <div class="trash-actions">
            <button class="btn primary" data-restore="${escHtml(r.id)}">↩ Восстановить</button>
            <button class="btn danger" data-purge="${escHtml(r.id)}">Удалить навсегда</button>
          </div>
        </div>
      </div>`;
    }).join("")}</div>`;

    container.querySelectorAll("[data-restore]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await RM.api.postJSON(`api/recipes/${btn.dataset.restore}/restore`, {});
          state.trashLoaded = false;
          state.recipes = [];
          await loadTrash();
        } catch (e) {
          alert("Ошибка восстановления: " + e.message);
          btn.disabled = false;
        }
      });
    });
    container.querySelectorAll("[data-purge]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Удалить рецепт навсегда? Восстановить его будет нельзя.")) return;
        btn.disabled = true;
        try {
          await RM.api.del(`api/recipes/${btn.dataset.purge}/permanent`);
          state.deletedRecipes = state.deletedRecipes.filter((r) => r.id !== btn.dataset.purge);
          renderTrash(($("search").value || "").trim());
        } catch (e) {
          alert("Ошибка удаления: " + e.message);
          btn.disabled = false;
        }
      });
    });
  }

  function renderGroups(groups) {
    const container = $("recipes-container");
    if (!groups.length) {
      container.innerHTML = '<div class="empty"><div class="icon">📖</div><p>Рецептов пока нет.</p></div>';
      return;
    }
    const grid = document.createElement("div");
    grid.className = "recipe-grid";
    for (const group of groups) {
      grid.appendChild(cardFor(group.display, group));
    }
    container.innerHTML = "";
    container.appendChild(grid);
  }

  function render(recipes) {
    const showSides = !RM.prefs || RM.prefs.getShowSideRecipes();
    const list = showSides
      ? recipes
      : (recipes || []).filter((r) => kindOf(r) !== "side");
    renderGroups(buildGroups(list));
  }

  function cardFor(r, group) {
    const card = document.createElement("div");
    const thumbUrl = r.image_thumb_url || r.image_url;
    card.className = "recipe-card" + (thumbUrl ? "" : " no-thumb");
    card.addEventListener("click", () => RM.detail.open(r));

    if (thumbUrl) {
      const thumb = document.createElement("div");
      thumb.className = "recipe-thumb";
      const img = document.createElement("img");
      img.src = RM.utils.mediaUrl(thumbUrl);
      img.alt = r.name || "";
      img.loading = "lazy";
      img.decoding = "async";
      img.width = 480;
      img.height = 360;
      thumb.appendChild(img);
      card.appendChild(thumb);
    }

    const cookBtn = document.createElement("button");
    cookBtn.className = "card-cook-btn";
    cookBtn.title = "На кухню";
    cookBtn.textContent = "🍳";
    cookBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      RM.cooking.start(r);
    });
    card.appendChild(cookBtn);

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

    if (r.adapted_versions && r.adapted_versions.airfryer) {
      const af = chip("♨️ аэрогриль", false);
      af.title = "Есть отдельная версия этого рецепта для аэрогриля";
      meta.appendChild(af);
    }
    
    // Нормализация по стандарту recipe_template.md
    if (r.normalization_status) {
      const issues = r.normalization_issues || [];
      const warnings = issues.filter((i) => i.severity === "error" || i.severity === "warning").length;
      const badge = chip(warnings ? `⚠️ ${warnings}` : "✅ норма", false);
      badge.title = issues.length
        ? issues.map((i) => `[${i.severity}] ${i.code}: ${i.message}`).join("\n")
        : "Рецепт соответствует стандарту";
      badge.classList.add(warnings ? "norm-issues" : "norm-ok");
      meta.appendChild(badge);
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

    if (group && group.personal) {
      const sw = document.createElement("div");
      sw.className = "recipe-version-switch";
      sw.innerHTML = `
        <button type="button" data-version="shared" class="${group.selected ? "" : "active"}">Общая</button>
        <button type="button" data-version="mine" class="${group.selected ? "active" : ""}">Моя</button>
      `;
      sw.addEventListener("click", (e) => e.stopPropagation());
      const sharedBtn = sw.querySelector('[data-version="shared"]');
      const mineBtn = sw.querySelector('[data-version="mine"]');
      if (sharedBtn) sharedBtn.onclick = (e) => {
        e.stopPropagation();
        if (!group.selected) return;
        selectPersonalVersion(group, false);
      };
      if (mineBtn) mineBtn.onclick = (e) => {
        e.stopPropagation();
        if (group.selected) return;
        selectPersonalVersion(group, true);
      };
      body.appendChild(sw);
    }

    card.appendChild(body);
    return card;
  }

  function chip(text, isTag) {
    const el = document.createElement("span");
    el.className = "meta-chip" + (isTag ? " tag" : "");
    el.textContent = text;
    return el;
  }

  RM.recipes = {
    setup, load, filterAndRender, render, fitsProfile, updateFilterButton,
    kindOf, versionGroups: buildGroups,
  };
})(window.RM);