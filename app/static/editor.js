/* Recipe editor module.
 * Открывается как модальное окно поверх основного UI.
 * Использование:
 *   window.openRecipeEditor(recipe, onSaved, defaults)
 *     recipe    — существующий рецепт (PATCH) или null (POST)
 *     onSaved   — callback после успешного сохранения
 *     defaults  — объект с полями, если нужно предзаполнить при создании
 */
"use strict";

(function () {
  const BASE = window.location.pathname.replace(/\/+$/, "") + "/";
  const api = (p) => BASE + p.replace(/^\/+/, "");

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
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

  function ensureStyles() {
    if (document.getElementById("rme-styles")) return;
    const style = document.createElement("style");
    style.id = "rme-styles";
    style.textContent = `
      .rme-overlay {
        position: fixed; inset: 0; z-index: 200;
        background: rgba(0,0,0,0.55);
        display: flex; align-items: flex-start; justify-content: center;
        overflow-y: auto; padding: 20px;
      }
      .rme-panel {
        background: var(--surface, #fff); color: var(--text, #1f2328);
        border-radius: 14px; max-width: 720px; width: 100%;
        margin: auto; padding: 22px 24px;
        position: relative; font-family: inherit;
      }
      .rme-header {
        display: flex; align-items: center; justify-content: space-between;
        margin-bottom: 16px; padding-bottom: 12px;
        border-bottom: 1px solid var(--border, #e4e6eb);
      }
      .rme-header h3 { margin: 0; font-size: 18px; font-weight: 700; }
      .rme-close {
        background: none; border: none; font-size: 26px; line-height: 1;
        color: var(--text-secondary, #5c6370); cursor: pointer;
        padding: 0 10px; border-radius: 8px;
      }
      .rme-close:hover { background: var(--elevated, #f2f3f7); color: var(--text, #1f2328); }
      .rme-body { display: flex; flex-direction: column; gap: 12px; }
      .rme-field label {
        display: block; font-size: 11px; font-weight: 600;
        color: var(--text-secondary, #5c6370);
        text-transform: uppercase; letter-spacing: 0.05em;
        margin-bottom: 4px;
      }
      .rme-field input, .rme-field textarea {
        width: 100%; background: var(--elevated, #f2f3f7);
        border: 1px solid var(--border, #e4e6eb); border-radius: 8px;
        color: var(--text, #1f2328); padding: 8px 10px;
        font-size: 14px; font-family: inherit; transition: border-color 0.15s;
      }
      .rme-field textarea { resize: vertical; min-height: 60px; }
      .rme-field input:focus, .rme-field textarea:focus {
        outline: none; border-color: var(--accent, #ff6b35);
      }
      .rme-row { display: flex; gap: 10px; flex-wrap: wrap; }
      .rme-row > * { flex: 1; min-width: 120px; }
      .rme-three { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
      .rme-section-title {
        font-size: 11px; font-weight: 700; color: var(--text-muted, #8b93a1);
        text-transform: uppercase; letter-spacing: 0.08em;
        padding-top: 10px; margin-top: 6px;
        border-top: 1px solid var(--border, #e4e6eb);
      }
      .rme-footer {
        display: flex; gap: 8px; justify-content: space-between;
        align-items: center; margin-top: 18px;
        padding-top: 14px; border-top: 1px solid var(--border, #e4e6eb);
      }
      .rme-footer-right { display: flex; gap: 8px; }
      .rme-btn {
        background: var(--elevated, #f2f3f7); border: 1px solid var(--border, #e4e6eb);
        border-radius: 8px; color: var(--text, #1f2328);
        padding: 9px 16px; font-size: 14px; font-weight: 500;
        cursor: pointer; font-family: inherit; transition: all 0.15s;
        display: inline-flex; align-items: center; gap: 6px;
      }
      .rme-btn:hover:not(:disabled) { background: var(--border, #e4e6eb); }
      .rme-btn:disabled { opacity: 0.5; cursor: not-allowed; }
      .rme-btn.primary {
        background: var(--accent, #ff6b35); border-color: var(--accent, #ff6b35);
        color: #fff;
      }
      .rme-btn.primary:hover:not(:disabled) { opacity: 0.88; background: var(--accent, #ff6b35); }
      .rme-btn.danger { color: var(--danger, #d64545); border-color: var(--danger, #d64545); }
      .rme-btn.danger:hover:not(:disabled) { background: var(--danger, #d64545); color: #fff; }
      .rme-status {
        font-size: 13px; padding: 8px 12px; border-radius: 8px;
        display: none; margin-top: 10px;
      }
      .rme-status.show { display: block; }
      .rme-status.error { background: rgba(214,69,69,0.12); color: var(--danger, #d64545); }
      .rme-status.success { background: rgba(46,160,67,0.12); color: var(--success, #2ea043); }
      .rme-hint {
        font-size: 12px; color: var(--text-secondary, #5c6370);
        margin-top: 4px; line-height: 1.4;
      }
    `;
    document.head.appendChild(style);
  }

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

  function normalizeRecipe(r, defaults) {
    const base = emptyRecipe();
    const merged = { ...base, ...(r || {}), ...(defaults || {}) };
    // ingredients могут быть строками
    merged.ingredients = (merged.ingredients || []).map((ing) =>
      typeof ing === "string" ? { name: ing } : { ...ing }
    );
    merged.instructions = (merged.instructions || []).map((s) => String(s));
    // nutrition
    merged.nutrition = { ...(merged.nutrition || {}) };
    return merged;
  }

  function renderEditor(recipe, isNew) {
    const r = recipe;
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
      <div class="rme-overlay" id="rme-overlay">
        <div class="rme-panel">
          <div class="rme-header">
            <h3>${isNew ? "Новый рецепт" : "Редактирование"}</h3>
            <button class="rme-close" id="rme-close">×</button>
          </div>

          <div class="rme-body">
            <div class="rme-field">
              <label>Название *</label>
              <input type="text" id="rme-name" value="${esc(r.name)}" placeholder="Например, Борщ">
            </div>
            <div class="rme-field">
              <label>Описание</label>
              <textarea id="rme-description" rows="2">${esc(r.description)}</textarea>
            </div>

            <div class="rme-row">
              <div class="rme-field">
                <label>Ссылка на источник</label>
                <input type="url" id="rme-source" value="${esc(r.source_url)}">
              </div>
              <div class="rme-field">
                <label>Фото (URL)</label>
                <input type="url" id="rme-image" value="${esc(r.image_url)}">
              </div>
            </div>

            <div class="rme-three">
              <div class="rme-field">
                <label>Prep (мин)</label>
                <input type="number" id="rme-prep" value="${r.prep_time ?? ""}" min="0">
              </div>
              <div class="rme-field">
                <label>Cook (мин)</label>
                <input type="number" id="rme-cook" value="${r.cook_time ?? ""}" min="0">
              </div>
              <div class="rme-field">
                <label>Порции</label>
                <input type="number" id="rme-servings" value="${r.servings ?? ""}" min="1">
              </div>
            </div>

            <div class="rme-field">
              <label>Теги (через запятую)</label>
              <input type="text" id="rme-tags" value="${esc(joinList(r.tags))}" placeholder="суп, украинская, зима">
            </div>

            <div class="rme-row">
              <div class="rme-field">
                <label>Курсы</label>
                <input type="text" id="rme-courses" value="${esc(joinList(r.courses))}" placeholder="суп, основное">
              </div>
              <div class="rme-field">
                <label>Категории</label>
                <input type="text" id="rme-categories" value="${esc(joinList(r.categories))}" placeholder="украинская кухня">
              </div>
            </div>

            <div class="rme-field">
              <label>Коллекции</label>
              <input type="text" id="rme-collections" value="${esc(joinList(r.collections))}" placeholder="на зиму, праздник">
            </div>

            <div class="rme-section-title">🥕 Ингредиенты</div>
            <div class="rme-field">
              <textarea id="rme-ingredients" rows="8"
                placeholder="500 г говядины
2 шт свёклы
300 г капусты">${esc(ingredientsText)}</textarea>
              <div class="rme-hint">Один ингредиент на строку. Начните строку с <code>#</code>, чтобы добавить подзаголовок (например, <code># Для бульона</code>).</div>
            </div>

            <div class="rme-section-title">📋 Шаги</div>
            <div class="rme-field">
              <textarea id="rme-instructions" rows="8"
                placeholder="Залейте мясо водой и доведите до кипения.
Добавьте овощи и варите 30 минут.">${esc(instructionsText)}</textarea>
              <div class="rme-hint">Один шаг на строку.</div>
            </div>

            <div class="rme-field">
              <label>Заметки</label>
              <textarea id="rme-notes" rows="2">${esc(r.notes)}</textarea>
            </div>

            <div class="rme-section-title">🥗 Пищевая ценность (на порцию)</div>
            <div class="rme-three">
              ${nutritionFields.slice(0, 3).map(([key, label]) =>
                `<div class="rme-field">
                  <label>${esc(label)}</label>
                  <input type="number" step="0.1" min="0" data-nutr="${key}" value="${esc(n[key] ?? "")}">
                </div>`
              ).join("")}
            </div>
            <div class="rme-three">
              ${nutritionFields.slice(3, 6).map(([key, label]) =>
                `<div class="rme-field">
                  <label>${esc(label)}</label>
                  <input type="number" step="0.1" min="0" data-nutr="${key}" value="${esc(n[key] ?? "")}">
                </div>`
              ).join("")}
            </div>
            <div class="rme-three">
              ${nutritionFields.slice(6, 9).map(([key, label]) =>
                `<div class="rme-field">
                  <label>${esc(label)}</label>
                  <input type="number" step="0.1" min="0" data-nutr="${key}" value="${esc(n[key] ?? "")}">
                </div>`
              ).join("")}
            </div>

            <div class="rme-status" id="rme-status"></div>
          </div>

          <div class="rme-footer">
            <div>
              ${!isNew ? `<button class="rme-btn danger" id="rme-delete">🗑️ Удалить</button>` : ""}
            </div>
            <div class="rme-footer-right">
              <button class="rme-btn" id="rme-cancel">Отмена</button>
              <button class="rme-btn primary" id="rme-save">💾 Сохранить</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function collectForm() {
    const ingredients = [];
    for (const line of $("rme-ingredients").value.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      if (trimmed.startsWith("#")) {
        ingredients.push({ name: trimmed, is_heading: true });
        continue;
      }
      // Простая эвристика: разобрать "500 г говядины" → amount=500, unit=г, name=говядины
      const m = trimmed.match(/^([\d.,/]+)\s+([а-яa-z]+\.?)\s+(.+)$/i);
      if (m) {
        ingredients.push({ amount: m[1], unit: m[2], name: m[3] });
      } else {
        ingredients.push({ name: trimmed });
      }
    }

    const instructions = $("rme-instructions").value.split("\n")
      .map((s) => s.trim()).filter(Boolean);

    const nutrition = {};
    document.querySelectorAll("[data-nutr]").forEach((el) => {
      const v = el.value.trim();
      if (v !== "") nutrition[el.dataset.nutr] = v;
    });

    return {
      name: $("rme-name").value.trim(),
      description: $("rme-description").value.trim() || null,
      source_url: $("rme-source").value.trim() || null,
      image_url: $("rme-image").value.trim() || null,
      servings: numOrNull($("rme-servings").value),
      prep_time: numOrNull($("rme-prep").value),
      cook_time: numOrNull($("rme-cook").value),
      tags: splitList($("rme-tags").value),
      courses: splitList($("rme-courses").value),
      categories: splitList($("rme-categories").value),
      collections: splitList($("rme-collections").value),
      ingredients,
      instructions,
      notes: $("rme-notes").value.trim() || null,
      nutrition: Object.keys(nutrition).length ? nutrition : null,
    };
  }

  function setStatus(el, text, kind) {
    el.textContent = text;
    el.className = "rme-status show " + kind;
  }
  function clearStatus(el) { el.className = "rme-status"; el.textContent = ""; }

  window.openRecipeEditor = function (recipe, onSaved, defaults) {
    ensureStyles();

    const isNew = !recipe || !recipe.id;
    const data = normalizeRecipe(recipe, defaults);

    const wrap = document.createElement("div");
    wrap.innerHTML = renderEditor(data, isNew);
    const overlay = wrap.firstElementChild;
    document.body.appendChild(overlay);

    const close = () => overlay.remove();

    $("rme-close").addEventListener("click", close);
    $("rme-cancel").addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

    const status = $("rme-status");

    $("rme-save").addEventListener("click", async () => {
      const payload = collectForm();
      if (!payload.name) {
        setStatus(status, "Укажите название рецепта.", "error");
        return;
      }
      const btn = $("rme-save");
      btn.disabled = true; btn.textContent = "Сохранение…";
      clearStatus(status);

      try {
        let resp;
        if (isNew) {
          resp = await fetch(api("api/recipes"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
        } else {
          resp = await fetch(api(`api/recipes/${recipe.id}`), {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
        }
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || JSON.stringify(data));
        setStatus(status, `✓ Рецепт «${data.recipe.name}» сохранён.`, "success");
        setTimeout(() => {
          close();
          if (onSaved) onSaved(data.recipe);
        }, 400);
      } catch (err) {
        setStatus(status, "Ошибка: " + err.message, "error");
        btn.disabled = false; btn.textContent = "💾 Сохранить";
      }
    });

    const delBtn = $("rme-delete");
    if (delBtn) {
      delBtn.addEventListener("click", async () => {
        if (!confirm(`Удалить рецепт «${recipe.name}»?`)) return;
        try {
          const resp = await fetch(api(`api/recipes/${recipe.id}`), { method: "DELETE" });
          if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            throw new Error(data.detail || "delete failed");
          }
          close();
          if (onSaved) onSaved(null);
        } catch (err) {
          setStatus(status, "Ошибка удаления: " + err.message, "error");
        }
      });
    }
  };
})();