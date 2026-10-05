"use strict";
(function (RM) {
  const { $, escHtml, formatTime, scaleAmount } = RM.utils;
  const { patchJSON, del } = RM.api;
  const state = RM.state;

  const RDA = {
    calories:      { label: "Калории",         unit: "kcal", value: 2000 },
    fat:           { label: "Жиры",            unit: "г",    value: 65 },
    saturated_fat: { label: "Насыщенные жиры", unit: "г",    value: 20 },
    cholesterol:   { label: "Холестерин",      unit: "мг",   value: 300 },
    sodium:        { label: "Натрий",          unit: "мг",   value: 2300 },
    carbohydrates: { label: "Углеводы",        unit: "г",    value: 300 },
    fiber:         { label: "Клетчатка",       unit: "г",    value: 28 },
    sugar:         { label: "Сахара",          unit: "г",    value: 50 },
    protein:       { label: "Белок",           unit: "г",    value: 50 },
  };

  function setup() {
    $("detail-overlay").addEventListener("click", (e) => {
      if (e.target === $("detail-overlay")) close();
    });
  }

  function open(recipe) {
    state.currentRecipe = recipe;
    state.servingMult = 1;
    state.completedSteps = new Set();
    render();
    $("detail-overlay").classList.add("show");
  }
  function close() {
    $("detail-overlay").classList.remove("show");
    state.currentRecipe = null;
  }

  function render() {
    const r = state.currentRecipe;
    if (!r) return;
    const panel = $("detail-panel");

    const ingredients = (r.ingredients || []).map((ing) =>
      typeof ing === "string" ? { name: ing, amount: null, unit: null, notes: null } : ing
    );

    const metaChips = [];
    if (r.servings_text || r.servings)
      metaChips.push(`<span class="meta-chip-large">👥 ${escHtml(r.servings_text || r.servings)}</span>`);
    if (r.prep_time) metaChips.push(`<span class="meta-chip-large">⏱ ${formatTime(r.prep_time)}</span>`);
    if (r.cook_time) metaChips.push(`<span class="meta-chip-large">🔥 ${formatTime(r.cook_time)}</span>`);
    const totalTime = r.total_time || r.time;
    if (totalTime && totalTime !== (r.prep_time||0)+(r.cook_time||0))
      metaChips.push(`<span class="meta-chip-large">⏲ ${formatTime(totalTime)}</span>`);

    const chipsRows = [];
    if ((r.courses || []).length) {
      chipsRows.push(`<div class="chips-row">
        <span class="chips-label">Курс:</span>
        ${r.courses.map((c) => `<button class="chip course" data-filter="${escHtml(c)}">${escHtml(c)}</button>`).join("")}
      </div>`);
    }
    if ((r.categories || []).length) {
      chipsRows.push(`<div class="chips-row">
        <span class="chips-label">Категория:</span>
        ${r.categories.map((c) => `<button class="chip category" data-filter="${escHtml(c)}">${escHtml(c)}</button>`).join("")}
      </div>`);
    }
    if ((r.collections || []).length) {
      chipsRows.push(`<div class="chips-row">
        <span class="chips-label">Коллекция:</span>
        ${r.collections.map((c) => `<button class="chip collection" data-filter="${escHtml(c)}">${escHtml(c)}</button>`).join("")}
      </div>`);
    }

    const photoBlock = r.image_url
      ? `<button class="photo-toggle" id="photo-toggle">📷 Показать фото</button>
         <div class="photo-box" id="photo-box"><img src="${escHtml(r.image_url)}" alt="${escHtml(r.name)}"></div>`
      : "";

    const hasNutrition = r.nutrition && Object.values(r.nutrition).some((v) => v != null && v !== "");
    const nutritionBlock = hasNutrition ? renderNutrition(r) : "";
    const rdaBlock = hasNutrition ? renderRDA(r) : "";

    const stepsHtml = (r.instructions || []).length
      ? `<ol class="steps-list">
          ${(r.instructions || []).map((s, i) => `
            <li class="step-item" data-step-idx="${i}">
              <div class="step-num" data-toggle-step="${i}">${i + 1}</div>
              <div class="step-text">${renderStepText(s)}</div>
            </li>
          `).join("")}
        </ol>`
      : `<p style="color:var(--text-secondary);font-size:14px;">Шаги не указаны.</p>`;

    const notesHtml = r.notes
      ? `<div class="section-card">
          <div class="section-title">📝 Заметки</div>
          <div class="notes-box">⚠️ ${escHtml(r.notes)}</div>
        </div>`
      : "";

    const ingredientsHtml = ingredients.length
      ? `<ul class="ingredients-list">
          ${ingredients.map((ing) => renderIngredientRow(ing)).join("")}
        </ul>`
      : `<p style="color:var(--text-secondary);font-size:14px;">Ингредиенты не указаны.</p>`;

    panel.innerHTML = `
      <button class="detail-close" id="detail-close">×</button>

      <div class="detail-head">
        <h2 class="detail-title">${escHtml(r.name || "")}</h2>
        ${r.description ? `<div class="detail-description">${escHtml(r.description)}</div>` : ""}

        <div class="detail-toolbar">
          <button class="toolbar-btn ${r.is_favourite ? "fav-active" : ""}" id="tbtn-fav">
            <span class="ico">${r.is_favourite ? "❤️" : "🤍"}</span>
            <span>Избранное</span>
          </button>
          <button class="toolbar-btn" id="tbtn-plan">
            <span class="ico">📅</span>
            <span>В план</span>
          </button>
          <button class="toolbar-btn" id="tbtn-shop">
            <span class="ico">🛒</span>
            <span>В покупки</span>
          </button>
          <button class="toolbar-btn" id="tbtn-edit">
            <span class="ico">✏️</span>
            <span>Правка</span>
          </button>
          <button class="toolbar-btn danger" id="tbtn-delete">
            <span class="ico">🗑️</span>
            <span>Удалить</span>
          </button>
        </div>

        ${photoBlock}
        ${metaChips.length ? `<div class="meta-chips">${metaChips.join("")}</div>` : ""}
        ${chipsRows.length ? `<div class="chips-area">${chipsRows.join("")}</div>` : ""}
      </div>

      <div class="detail-grid">
        <div class="detail-col">
          <div class="section-card">
            <div class="scaler-row">
              <div class="scaler">
                <button class="scaler-btn" id="scale-minus">−</button>
                <span class="scaler-val" id="scale-val">×1</span>
                <button class="scaler-btn" id="scale-plus">+</button>
              </div>
              <span style="font-size:11px;color:var(--text-muted)">порции</span>
            </div>
          </div>
          <div class="section-card">
            <div class="section-title">🥕 Ингредиенты</div>
            ${ingredientsHtml}
          </div>
          ${hasNutrition ? `<div class="section-card">${nutritionBlock}${rdaBlock}</div>` : ""}
        </div>
        <div class="detail-col">
          <div class="section-card">
            <div class="section-title">📋 Шаги приготовления</div>
            ${stepsHtml}
          </div>
          ${notesHtml}
        </div>
      </div>
    `;

    // --- Events ---
    $("detail-close").addEventListener("click", close);
    $("tbtn-delete").addEventListener("click", () => onDelete(r));
    $("tbtn-fav").addEventListener("click", () => onToggleFav(r));
    $("tbtn-plan").addEventListener("click", () => RM.planPicker.open(r));
    $("tbtn-shop").addEventListener("click", () => {
      RM.shopping.openRecipeShop(r, state.servingMult);
      });
    $("tbtn-edit").addEventListener("click", () => {
      RM.editor.open(r, (updated) => {
        state.currentRecipe = { ...r, ...updated };
        const idx = state.recipes.findIndex((x) => x.id === r.id);
        if (idx >= 0) state.recipes[idx] = state.currentRecipe;
        render();
        RM.recipes.render(state.recipes);
      });
    });

    const photoToggle = $("photo-toggle");
    if (photoToggle) {
      photoToggle.addEventListener("click", () => {
        const box = $("photo-box");
        box.classList.toggle("show");
        photoToggle.textContent = box.classList.contains("show") ? "📷 Скрыть фото" : "📷 Показать фото";
      });
    }

    $("scale-minus").addEventListener("click", () => {
      if (state.servingMult <= 0.25) return;
      state.servingMult = Math.max(0.25, state.servingMult - 0.25);
      updateServingDisplay();
    });
    $("scale-plus").addEventListener("click", () => {
      state.servingMult += 0.25;
      updateServingDisplay();
    });

    panel.querySelectorAll("[data-toggle-step]").forEach((el) => {
      el.addEventListener("click", () => {
        const idx = parseInt(el.dataset.toggleStep, 10);
        if (state.completedSteps.has(idx)) state.completedSteps.delete(idx);
        else state.completedSteps.add(idx);
        updateStepDisplay();
      });
    });

    panel.querySelectorAll("[data-filter]").forEach((el) => {
      el.addEventListener("click", () => {
        const val = el.dataset.filter;
        close();
        RM.tabs.switchToRecipes();
        $("search").value = val;
        RM.recipes.filterAndRender(val);
      });
    });
  }

  function renderIngredientRow(ing) {
    if (ing.is_heading || (ing.name || "").startsWith("#")) {
      const text = (ing.name || "").replace(/^#\s*/, "");
      return `<li class="ing-heading">${escHtml(text)}</li>`;
    }
    const amount = scaleAmount(ing.amount, state.servingMult);
    const unit = ing.unit || "";
    const amountStr = [amount, unit].filter(Boolean).join(" ");
    return `<li class="ing-item">
      <span class="ing-amount">${escHtml(amountStr || "—")}</span>
      <span class="ing-name">${escHtml(ing.name || "")}${
        ing.notes ? ` <span class="ing-notes">(${escHtml(ing.notes)})</span>` : ""
      }</span>
    </li>`;
  }

  function renderStepText(text) {
    return escHtml(text)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>");
  }

  function updateServingDisplay() {
    const el = $("scale-val");
    if (el) el.textContent = "×" + state.servingMult;
    const r = state.currentRecipe;
    if (!r) return;
    const list = document.querySelector(".ingredients-list");
    if (!list) return;
    const ingredients = (r.ingredients || []).map((ing) =>
      typeof ing === "string" ? { name: ing } : ing
    );
    list.innerHTML = ingredients.map(renderIngredientRow).join("");
  }

  function updateStepDisplay() {
    document.querySelectorAll(".step-item").forEach((el) => {
      const idx = parseInt(el.dataset.stepIdx, 10);
      const num = el.querySelector(".step-num");
      if (state.completedSteps.has(idx)) {
        el.classList.add("done");
        num.classList.add("done");
        num.textContent = "✓";
      } else {
        el.classList.remove("done");
        num.classList.remove("done");
        num.textContent = idx + 1;
      }
    });
  }

  // --- Nutrition ring ---
  function renderNutrition(r) {
    const n = r.nutrition || {};
    const carbs = parseFloat(n.carbohydrates) || 0;
    const fat = parseFloat(n.fat) || 0;
    const protein = parseFloat(n.protein) || 0;
    const calories = parseFloat(n.calories) || 0;

    const calCarbs = carbs * 4;
    const calFat = fat * 9;
    const calProtein = protein * 4;
    const totalCal = calCarbs + calFat + calProtein;

    const r0 = 42;
    const C = 2 * Math.PI * r0;
    const gap = 6;
    const lenCarbs = totalCal > 0 ? Math.max(0, (calCarbs / totalCal) * C - gap) : 0;
    const lenFat   = totalCal > 0 ? Math.max(0, (calFat   / totalCal) * C - gap) : 0;
    const lenProt  = totalCal > 0 ? Math.max(0, (calProtein/ totalCal) * C - gap) : 0;

    const startCarbs = -90;
    const startFat = startCarbs + (totalCal > 0 ? (calCarbs / totalCal) * 360 : 0);
    const startProt = startFat + (totalCal > 0 ? (calFat / totalCal) * 360 : 0);

    const displayCal = calories > 0 ? Math.round(calories) : (totalCal > 0 ? Math.round(totalCal) : "—");

    return `
      <div class="section-title">🥗 Пищевая ценность</div>
      <div class="nutr-block">
        <div class="nutr-ring-wrap">
          <svg width="90" height="90" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="${r0}" fill="none" stroke="var(--border)" stroke-width="7"/>
            <circle cx="50" cy="50" r="${r0}" fill="none"
              stroke="var(--carbs)" stroke-width="7" stroke-linecap="round"
              stroke-dasharray="${lenCarbs} ${C}"
              transform="rotate(${startCarbs} 50 50)"
              opacity="${lenCarbs > 0 ? 1 : 0}"/>
            <circle cx="50" cy="50" r="${r0}" fill="none"
              stroke="var(--fat)" stroke-width="7" stroke-linecap="round"
              stroke-dasharray="${lenFat} ${C}"
              transform="rotate(${startFat} 50 50)"
              opacity="${lenFat > 0 ? 1 : 0}"/>
            <circle cx="50" cy="50" r="${r0}" fill="none"
              stroke="var(--protein)" stroke-width="7" stroke-linecap="round"
              stroke-dasharray="${lenProt} ${C}"
              transform="rotate(${startProt} 50 50)"
              opacity="${lenProt > 0 ? 1 : 0}"/>
            <text x="50" y="48" text-anchor="middle" class="nutr-ring-text-main">${displayCal}</text>
            <text x="50" y="62" text-anchor="middle" class="nutr-ring-text-sub">kcal</text>
          </svg>
        </div>
        <div class="nutr-macros">
          ${macroCol("Углеводы", carbs, calCarbs, totalCal, "var(--carbs)")}
          ${macroCol("Жиры", fat, calFat, totalCal, "var(--fat)")}
          ${macroCol("Белок", protein, calProtein, totalCal, "var(--protein)")}
        </div>
      </div>
      ${r.servings_text ? `<div class="nutr-serving-note">на ${escHtml(r.servings_text)}</div>` : ""}
    `;
  }

  function macroCol(label, grams, cal, totalCal, color) {
    const pct = totalCal > 0 ? Math.round((cal / totalCal) * 100) : 0;
    const val = grams > 0 ? `${grams} г` : "—";
    return `<div class="nutr-macro">
      <span class="nutr-macro-val" style="color:${color}">${val}</span>
      <span class="nutr-macro-label">${label}</span>
      ${pct > 0 ? `<span class="nutr-macro-pct" style="color:${color}">${pct}% cal</span>` : ""}
    </div>`;
  }

  function renderRDA(r) {
    const n = r.nutrition || {};
    const order = ["calories","fat","saturated_fat","cholesterol","sodium","carbohydrates","fiber","sugar","protein"];
    const rows = [];
    for (const key of order) {
      const v = parseFloat(n[key]);
      if (!v || isNaN(v)) continue;
      const rda = RDA[key];
      if (!rda) continue;
      const pct = Math.min(Math.round((v / rda.value) * 100), 999);
      rows.push(`<div class="rda-row">
        <span class="rda-label">${rda.label}</span>
        <span class="rda-val">${v} ${rda.unit}</span>
        <span class="rda-pct">${pct}%</span>
        <div class="rda-bar-wrap"><div class="rda-bar ${pct > 100 ? "over" : ""}" style="width:${Math.min(pct,100)}%"></div></div>
      </div>`);
    }
    if (!rows.length) return "";
    return `<div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--border);">
      <div class="section-title" style="margin-bottom:8px;">📊 Дневная норма</div>
      <div class="rda-list">${rows.join("")}</div>
    </div>`;
  }

  async function onDelete(r) {
    if (!confirm(`Удалить рецепт «${r.name}»?`)) return;
    try {
      await del(`api/recipes/${r.id}`);
      state.recipes = state.recipes.filter((x) => x.id !== r.id);
      close();
      RM.recipes.render(state.recipes);
    } catch (err) {
      alert("Ошибка удаления: " + err.message);
    }
  }

  async function onToggleFav(r) {
    try {
      const data = await patchJSON(`api/recipes/${r.id}`, { is_favourite: !r.is_favourite });
      state.currentRecipe = data.recipe;
      const idx = state.recipes.findIndex((x) => x.id === r.id);
      if (idx >= 0) state.recipes[idx] = data.recipe;
      render();
      RM.recipes.render(state.recipes);
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  RM.detail = { setup, open, close, render };
})(window.RM);