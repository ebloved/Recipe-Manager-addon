/* Редактор рецепта — модальное окно поверх основного UI. */
"use strict";
(function (RM) {
  const { $, escHtml } = RM.utils;
  const { postJSON, patchJSON, del } = RM.api;

  function emptyRecipe() {
    return {
      name: "", description: "", source_url: "", image_url: "",
      servings: null, servings_text: "",
      prep_time: null, cook_time: null, total_time: null,
      tags: [], courses: [], categories: [], collections: [],
      cuisine: "", category: "",
      ingredients: [], instructions: [], notes: "",
      nutrition: {},
    };
  }

  function normalize(r, defaults) {
    const base = emptyRecipe();
    const merged = { ...base, ...(r || {}), ...(defaults || {}) };
    merged.ingredients = (merged.ingredients || []).map((ing) =>
      typeof ing === "string" ? { name: ing } : { ...ing }
    );
    merged.instructions = (merged.instructions || []).map((s) => String(s));
    merged.nutrition = { ...(merged.nutrition || {}) };
    return merged;
  }

  function numOrNull(v) {
    if (v === "" || v == null) return null;
    const n = parseInt(v, 10);
    return isNaN(n) ? null : n;
  }
  function splitList(v) {
    return (v || "").split(",").map((s) => s.trim()).filter(Boolean);
  }
  function joinList(v) {
    return Array.isArray(v) ? v.join(", ") : "";
  }

  function renderEditor(r, isNew) {
    const n = r.nutrition || {};
    const nutritionFields = [
      ["calories", "Калории (kcal)"],
      ["protein", "Белок (г)"],
      ["fat", "Жиры (г)"],
      ["carbohydrates", "Углеводы (г)"],
      ["saturated_fat", "Насыщ. жиры (г)"],
      ["fiber", "Клетчатка (г)"],
      ["sugar", "Сахара (г)"],
      ["sodium", "Натрий (мг)"],
      ["cholesterol", "Холестерин (мг)"],
    ];

    const ingredientsText = r.ingredients.map((ing) => {
      const parts = [];
      if (ing.amount) parts.push(ing.amount);
      if (ing.unit) parts.push(ing.unit);
      const head = parts.join(" ");
      const name = ing.name || "";
      const notes = ing.notes ? ` (${ing.notes})` : "";
      return (head ? head + " " : "") + name + notes;
    }).join("\n");

    const instructionsText = r.instructions.join("\n");

    return `
      <div class="editor-panel">
        <div class="editor-header">
          <h3>${isNew ? "Новый рецепт" : "Редактирование"}</h3>
          <button class="editor-close" id="ed-close">×</button>
        </div>
        <div class="editor-body">
          <div class="field">
            <label>Название *</label>
            <input type="text" id="ed-name" value="${escHtml(r.name)}">
          </div>
          <div class="field">
            <label>Описание</label>
            <textarea id="ed-description" rows="2">${escHtml(r.description)}</textarea>
          </div>
          <div class="row">
            <div class="field">
              <label>Ссылка на источник</label>
              <input type="url" id="ed-source" value="${escHtml(r.source_url)}">
            </div>
            <div class="field">
              <label>Фото (URL)</label>
              <input type="url" id="ed-image" value="${escHtml(r.image_url)}">
            </div>
          </div>
          <div class="editor-three">
            <div class="field">
              <label>Prep (мин)</label>
              <input type="number" id="ed-prep" value="${r.prep_time ?? ""}" min="0">
            </div>
            <div class="field">
              <label>Cook (мин)</label>
              <input type="number" id="ed-cook" value="${r.cook_time ?? ""}" min="0">
            </div>
            <div class="field">
              <label>Порции</label>
              <input type="number" id="ed-servings" value="${r.servings ?? ""}" min="1">
            </div>
          </div>
          <div class="field">
            <label>Теги (через запятую)</label>
            <input type="text" id="ed-tags" value="${escHtml(joinList(r.tags))}">
          </div>
          <div class="row">
            <div class="field">
              <label>Курсы</label>
              <input type="text" id="ed-courses" value="${escHtml(joinList(r.courses))}">
            </div>
            <div class="field">
              <label>Категории</label>
              <input type="text" id="ed-categories" value="${escHtml(joinList(r.categories))}">
            </div>
          </div>
          <div class="field">
            <label>Коллекции</label>
            <input type="text" id="ed-collections" value="${escHtml(joinList(r.collections))}">
          </div>

          <div class="editor-section-title">🥕 Ингредиенты</div>
          <div class="field">
            <textarea id="ed-ingredients" rows="8" placeholder="500 г говядины&#10;2 шт свёклы&#10;300 г капусты">${escHtml(ingredientsText)}</textarea>
            <div class="editor-hint">Один ингредиент на строку. Начните с <code>#</code> для подзаголовка.</div>
          </div>

          <div class="editor-section-title">📋 Шаги</div>
          <div class="field">
            <textarea id="ed-instructions" rows="8">${escHtml(instructionsText)}</textarea>
            <div class="editor-hint">Один шаг на строку.</div>
          </div>

          <div class="field">
            <label>Заметки</label>
            <textarea id="ed-notes" rows="2">${escHtml(r.notes)}</textarea>
          </div>

          <div class="editor-section-title">🥗 Пищевая ценность (на порцию)</div>
          <div class="editor-three">
            ${nutritionFields.slice(0, 3).map(([k, l]) =>
              `<div class="field"><label>${escHtml(l)}</label><input type="number" step="0.1" min="0" data-nutr="${k}" value="${escHtml(n[k] ?? "")}"></div>`
            ).join("")}
          </div>
          <div class="editor-three">
            ${nutritionFields.slice(3, 6).map(([k, l]) =>
              `<div class="field"><label>${escHtml(l)}</label><input type="number" step="0.1" min="0" data-nutr="${k}" value="${escHtml(n[k] ?? "")}"></div>`
            ).join("")}
          </div>
          <div class="editor-three">
            ${nutritionFields.slice(6, 9).map(([k, l]) =>
              `<div class="field"><label>${escHtml(l)}</label><input type="number" step="0.1" min="0" data-nutr="${k}" value="${escHtml(n[k] ?? "")}"></div>`
            ).join("")}
          </div>

          <div class="status" id="ed-status"></div>
        </div>
        <div class="editor-footer">
          <div>${!isNew ? `<button class="btn danger" id="ed-delete">🗑️ Удалить</button>` : ""}</div>
          <div class="editor-footer-right">
            <button class="btn" id="ed-cancel">Отмена</button>
            <button class="btn primary" id="ed-save">💾 Сохранить</button>
          </div>
        </div>
      </div>
    `;
  }

  function collectForm() {
    const ingredients = [];
    for (const line of $("ed-ingredients").value.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      if (trimmed.startsWith("#")) {
        ingredients.push({ name: trimmed, is_heading: true });
        continue;
      }
      const m = trimmed.match(/^([\d.,/]+)\s+([а-яa-z]+\.?)\s+(.+)$/i);
      if (m) ingredients.push({ amount: m[1], unit: m[2], name: m[3] });
      else ingredients.push({ name: trimmed });
    }

    const instructions = $("ed-instructions").value.split("\n").map((s) => s.trim()).filter(Boolean);

    const nutrition = {};
    document.querySelectorAll("[data-nutr]").forEach((el) => {
      const v = el.value.trim();
      if (v !== "") nutrition[el.dataset.nutr] = v;
    });

    return {
      name: $("ed-name").value.trim(),
      description: $("ed-description").value.trim() || null,
      source_url: $("ed-source").value.trim() || null,
      image_url: $("ed-image").value.trim() || null,
      servings: numOrNull($("ed-servings").value),
      prep_time: numOrNull($("ed-prep").value),
      cook_time: numOrNull($("ed-cook").value),
      tags: splitList($("ed-tags").value),
      courses: splitList($("ed-courses").value),
      categories: splitList($("ed-categories").value),
      collections: splitList($("ed-collections").value),
      ingredients,
      instructions,
      notes: $("ed-notes").value.trim() || null,
      nutrition: Object.keys(nutrition).length ? nutrition : null,
    };
  }

  function setStatus(el, text, kind) {
    el.textContent = text;
    el.className = "status show " + kind;
  }

  function open(recipe, onSaved, defaults) {
    const isNew = !recipe || !recipe.id;
    const data = normalize(recipe, defaults);
    const overlay = $("editor-overlay");
    overlay.innerHTML = renderEditor(data, isNew);
    overlay.classList.add("show");

    const close = () => {
      overlay.classList.remove("show");
      overlay.innerHTML = "";
    };

    $("ed-close").addEventListener("click", close);
    $("ed-cancel").addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

    const status = $("ed-status");

    $("ed-save").addEventListener("click", async () => {
      const payload = collectForm();
      if (!payload.name) {
        setStatus(status, "Укажите название рецепта.", "error");
        return;
      }
      const btn = $("ed-save");
      btn.disabled = true;
      btn.textContent = "Сохранение…";
      try {
        const data = isNew
          ? await postJSON("api/recipes", payload)
          : await patchJSON(`api/recipes/${recipe.id}`, payload);
        setStatus(status, `✓ Рецепт «${data.recipe.name}» сохранён.`, "success");
        setTimeout(() => {
          close();
          if (onSaved) onSaved(data.recipe);
        }, 400);
      } catch (err) {
        setStatus(status, "Ошибка: " + err.message, "error");
        btn.disabled = false;
        btn.textContent = "💾 Сохранить";
      }
    });

    const delBtn = $("ed-delete");
    if (delBtn) {
      delBtn.addEventListener("click", async () => {
        if (!confirm(`Удалить рецепт «${recipe.name}»?`)) return;
        try {
          await del(`api/recipes/${recipe.id}`);
          close();
          if (onSaved) onSaved(null);
        } catch (err) {
          setStatus(status, "Ошибка удаления: " + err.message, "error");
        }
      });
    }
  }

  RM.editor = { open };
})(window.RM);