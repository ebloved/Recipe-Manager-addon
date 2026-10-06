/* Редактор рецепта — модальное окно поверх основного UI.
 *
 * Изменения относительно предыдущей версии:
 *   - Под textarea «Ингредиенты» добавлена секция «🔗 Связки с продуктами»,
 *     где для каждого ингредиента можно связать/отвязать продукт через
 *     product-picker.
 *   - Связки хранятся в локальном state редактора (по имени ингредиента,
 *     нормализованному в lowercase + ё→е) и применяются к ингредиентам
 *     при сохранении.
 *   - Кнопки экспорта и Markdown-редактирования сохранены без изменений.
 */
"use strict";
(function (RM) {
  const { $, escHtml } = RM.utils;
  const { getJSON, postJSON, patchJSON, del } = RM.api;

  const BASE = window.location.pathname.replace(/\/+$/, "") + "/";
  const api = (p) => BASE + p.replace(/^\/+/, "");

  // -----------------------------------------------------------------
  // Состояние текущего открытого редактора
  // -----------------------------------------------------------------
  const s = {
    ingredientLinks: {},   // normalized name → product_id
    productCache: {},      // product_id → { name, brand, image_url, ... }
    linksTimer: null,      // debounce для renderLinks
  };

  // -----------------------------------------------------------------
  // Базовые хелперы
  // -----------------------------------------------------------------
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
    merged.instructions = (merged.instructions || []).map((x) => String(x));
    merged.nutrition = { ...(merged.nutrition || {}) };
    return merged;
  }

  function numOrNull(v) {
    if (v === "" || v == null) return null;
    const n = parseInt(v, 10);
    return isNaN(n) ? null : n;
  }
  function splitList(v) {
    return (v || "").split(",").map((x) => x.trim()).filter(Boolean);
  }
  function joinList(v) {
    return Array.isArray(v) ? v.join(", ") : "";
  }
  function normalizeName(name) {
    return String(name || "").trim().toLowerCase().replace(/ё/g, "е");
  }

  // -----------------------------------------------------------------
  // Парсинг строки ингредиента (тот же формат, что и на бэкенде)
  // -----------------------------------------------------------------
  function parseIngredientLine(line) {
    const trimmed = (line || "").trim();
    if (!trimmed) return null;

    // Подзаголовок
    if (trimmed.startsWith("#")) {
      return { name: trimmed, is_heading: true };
    }

    // "500 г муки" или "2 шт яйца" или "соль"
    const m = trimmed.match(/^([\d.,/]+)\s+([а-яa-z]+\.?)\s+(.+)$/i);
    if (m) {
      return { amount: m[1], unit: m[2], name: m[3].trim() };
    }
    return { name: trimmed };
  }

  // -----------------------------------------------------------------
  // Рендер модалки
  // -----------------------------------------------------------------
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
      if (ing.is_heading || (ing.name || "").startsWith("#")) {
        return ing.name || "";
      }
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
          <div class="editor-header-actions">
            ${!isNew ? `
              <button class="editor-btn" id="ed-export-md" title="Скачать .md">📥 .md</button>
              <button class="editor-btn" id="ed-edit-md" title="Редактировать как Markdown">📝 Markdown</button>
            ` : ""}
            <button class="editor-close" id="ed-close">×</button>
          </div>
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

          <div class="editor-links" id="ed-ingredient-links"></div>

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

        <div class="editor-md-view" id="ed-md-view" style="display:none">
          <div class="editor-md-hint">
            Отредактируйте Markdown и нажмите «Применить». Поля формы будут перезаписаны.
            Формат: YAML front matter + тело с разделами <code>## Ингредиенты</code> и <code>## Шаги</code>.
          </div>
          <textarea id="ed-md-text" class="editor-md-textarea" spellcheck="false"></textarea>
          <div class="editor-md-actions">
            <button class="btn" id="ed-md-cancel">Отмена</button>
            <button class="btn primary" id="ed-md-apply">Применить</button>
          </div>
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

  // -----------------------------------------------------------------
  // Секция «Связки с продуктами»
  // -----------------------------------------------------------------
  function scheduleRenderLinks() {
    if (s.linksTimer) clearTimeout(s.linksTimer);
    s.linksTimer = setTimeout(renderLinks, 200);
  }

  function renderLinks() {
    const ta = $("ed-ingredients");
    const container = $("ed-ingredient-links");
    if (!ta || !container) return;

    // Парсим текущее содержимое textarea
    const lines = ta.value.split("\n").map((l) => l.trim()).filter(Boolean);
    const items = [];
    for (const line of lines) {
      const parsed = parseIngredientLine(line);
      if (!parsed || parsed.is_heading) continue;
      if (!parsed.name) continue;
      items.push(parsed.name);
    }

    if (!items.length) {
      container.innerHTML = "";
      container.style.display = "none";
      return;
    }

    // Убираем устаревшие связки (ингредиенты, которые больше не в textarea)
    const currentNorms = new Set(items.map(normalizeName));
    for (const k of Object.keys(s.ingredientLinks)) {
      if (!currentNorms.has(k)) delete s.ingredientLinks[k];
    }

    const linkedCount = items.filter((n) => s.ingredientLinks[normalizeName(n)]).length;

    container.style.display = "block";
    container.innerHTML = `
      <div class="ed-links-header">
        <span class="ed-links-title">🔗 Связки с продуктами</span>
        <span class="ed-links-count">${linkedCount} из ${items.length}</span>
      </div>
      <div class="ed-links-list">
        ${items.map((name) => renderLinkRow(name)).join("")}
      </div>
    `;

    container.querySelectorAll("[data-ed-link]").forEach((el) => {
      el.addEventListener("click", (e) => {
        if (e.target.closest("[data-ed-unlink]")) return;
        onLinkClick(el.dataset.edLink);
      });
    });
    container.querySelectorAll("[data-ed-unlink]").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        onUnlink(el.dataset.edUnlink);
      });
    });
  }

  function renderLinkRow(name) {
    const norm = normalizeName(name);
    const pid = s.ingredientLinks[norm];

    if (pid) {
      const p = s.productCache[pid];
      const label = p
        ? (p.name || "") + (p.brand ? ` · ${p.brand}` : "")
        : "(продукт не найден)";
      const thumb = p && p.image_url
        ? `<img class="ed-link-thumb" src="${escHtml(p.image_url)}" alt="" loading="lazy">`
        : `<span class="ed-link-thumb ed-link-thumb-placeholder">📦</span>`;

      return `<div class="ed-link-row linked" data-ed-link="${escHtml(name)}" title="Изменить связку">
        ${thumb}
        <div class="ed-link-info">
          <span class="ed-link-ing">${escHtml(name)}</span>
          <span class="ed-link-product">${escHtml(label)}</span>
        </div>
        <button class="ed-link-remove" data-ed-unlink="${escHtml(name)}" title="Отвязать">×</button>
      </div>`;
    }

    return `<div class="ed-link-row" data-ed-link="${escHtml(name)}" title="Связать с продуктом">
      <span class="ed-link-thumb ed-link-thumb-placeholder">🔗</span>
      <div class="ed-link-info">
        <span class="ed-link-ing">${escHtml(name)}</span>
        <span class="ed-link-hint">не связан — нажмите, чтобы связать</span>
      </div>
    </div>`;
  }

  function onLinkClick(name) {
    const norm = normalizeName(name);
    const currentPid = s.ingredientLinks[norm] || null;

    RM.productPicker.open(name, currentPid, async (productId, product) => {
      if (productId) {
        s.ingredientLinks[norm] = productId;
        if (product) s.productCache[productId] = product;
      } else {
        delete s.ingredientLinks[norm];
      }
      renderLinks();
    });
  }

  function onUnlink(name) {
    const norm = normalizeName(name);
    if (!s.ingredientLinks[norm]) return;
    if (!confirm(`Отвязать «${name}» от продукта?`)) return;
    delete s.ingredientLinks[norm];
    renderLinks();
  }

  // -----------------------------------------------------------------
  // Сбор данных формы
  // -----------------------------------------------------------------
  function collectForm() {
    const lines = $("ed-ingredients").value.split("\n");
    const ingredients = [];
    for (const line of lines) {
      const parsed = parseIngredientLine(line);
      if (!parsed) continue;

      // Применяем связку из локального state
      if (!parsed.is_heading && parsed.name) {
        const pid = s.ingredientLinks[normalizeName(parsed.name)];
        if (pid) parsed.product_id = pid;
      }

      ingredients.push(parsed);
    }

    const instructions = $("ed-instructions").value
      .split("\n").map((x) => x.trim()).filter(Boolean);

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

  // -----------------------------------------------------------------
  // Open
  // -----------------------------------------------------------------
  async function open(recipe, onSaved, defaults) {
    const isNew = !recipe || !recipe.id;
    const data = normalize(recipe, defaults);
    const overlay = $("editor-overlay");

    // Сброс локального состояния
    s.ingredientLinks = {};
    s.productCache = {};

    // Засеиваем связки из рецепта
    if (recipe && Array.isArray(recipe.ingredients)) {
      for (const ing of recipe.ingredients) {
        if (ing && typeof ing === "object" && ing.product_id && ing.name) {
          s.ingredientLinks[normalizeName(ing.name)] = ing.product_id;
        }
      }
    }

    overlay.innerHTML = renderEditor(data, isNew);
    overlay.classList.add("show");

    const close = () => {
      overlay.classList.remove("show");
      overlay.innerHTML = "";
      s.ingredientLinks = {};
      s.productCache = {};
    };

    $("ed-close").addEventListener("click", close);
    $("ed-cancel").addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

    const status = $("ed-status");

    // --- Первичный рендер связок (до загрузки продуктов) ---
    renderLinks();

    // --- Асинхронная загрузка данных продуктов по связкам ---
    const ids = new Set(Object.values(s.ingredientLinks));
    if (ids.size) {
      Promise.all([...ids].map((id) =>
        getJSON(`api/ingredients/${id}`)
          .then((d) => [id, d.product])
          .catch(() => [id, null])
      )).then((results) => {
        for (const [id, p] of results) {
          if (p) s.productCache[id] = p;
        }
        renderLinks();
      });
    }

    // --- Перерисовка связок при изменении textarea ---
    $("ed-ingredients").addEventListener("input", scheduleRenderLinks);

    // --- Сохранить ---
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
        const saved = isNew
          ? await postJSON("api/recipes", payload)
          : await patchJSON(`api/recipes/${recipe.id}`, payload);
        setStatus(status, `✓ Рецепт «${saved.recipe.name}» сохранён.`, "success");
        setTimeout(() => {
          close();
          if (onSaved) onSaved(saved.recipe);
        }, 400);
      } catch (err) {
        setStatus(status, "Ошибка: " + err.message, "error");
        btn.disabled = false;
        btn.textContent = "💾 Сохранить";
      }
    });

    // --- Удалить ---
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

    // --- Экспорт в .md ---
    const exportBtn = $("ed-export-md");
    if (exportBtn) {
      exportBtn.addEventListener("click", () => {
        if (!recipe || !recipe.id) return;
        const url = api(`api/recipes/${recipe.id}/export.md`);
        window.open(url, "_blank");
      });
    }

    // --- Редактирование в Markdown ---
    const mdToggle = $("ed-edit-md");
    if (mdToggle) {
      mdToggle.addEventListener("click", () => {
        const payload = collectForm();
        const md = _recipeToMd(payload, recipe);
        $("ed-md-text").value = md;
        const body = document.querySelector(".editor-body");
        const footer = document.querySelector(".editor-footer");
        if (body) body.style.display = "none";
        if (footer) footer.style.display = "none";
        $("ed-md-view").style.display = "flex";
      });
    }

    const mdCancel = $("ed-md-cancel");
    if (mdCancel) {
      mdCancel.addEventListener("click", () => {
        $("ed-md-view").style.display = "none";
        const body = document.querySelector(".editor-body");
        const footer = document.querySelector(".editor-footer");
        if (body) body.style.display = "flex";
        if (footer) footer.style.display = "flex";
      });
    }

    const mdApply = $("ed-md-apply");
    if (mdApply) {
      mdApply.addEventListener("click", async () => {
        const md = $("ed-md-text").value;
        if (!md.trim()) return;
        const btn = $("ed-md-apply");
        btn.disabled = true;
        btn.textContent = "Применение…";
        try {
          const resp = await fetch(api(`api/recipes/${recipe.id}/import-md`), {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ markdown_content: md }),
          });
          const json = await resp.json();
          if (!resp.ok) throw new Error(json.detail || JSON.stringify(json));
          close();
          if (onSaved) onSaved(json.recipe);
        } catch (err) {
          alert("Ошибка: " + err.message);
          btn.disabled = false;
          btn.textContent = "Применить";
        }
      });
    }
  }

  // -----------------------------------------------------------------
  // Локальная сериализация в Markdown (для превью)
  // -----------------------------------------------------------------
  function _recipeToMd(r, original) {
    const out = ["---"];
    const push = (k, v) => {
      if (v == null || v === "" || (Array.isArray(v) && !v.length)) return;
      if (Array.isArray(v)) {
        out.push(`${k}: [${v.map((x) => JSON.stringify(x)).join(", ")}]`);
      } else if (typeof v === "string" && /[:#,]/.test(v)) {
        out.push(`${k}: ${JSON.stringify(v)}`);
      } else {
        out.push(`${k}: ${v}`);
      }
    };
    push("id", original && original.id ? original.id : r.id);
    push("title", r.name);
    push("description", r.description);
    push("tags", r.tags);
    push("courses", r.courses);
    push("categories", r.categories);
    push("collections", r.collections);
    push("servings", r.servings);
    push("prep_time", r.prep_time);
    push("cook_time", r.cook_time);
    push("source_url", r.source_url);
    push("image_url", r.image_url);
    if (r.nutrition && Object.keys(r.nutrition).length) {
      out.push("nutrition:");
      for (const [k, v] of Object.entries(r.nutrition)) {
        if (v) out.push(`  ${k}: ${v}`);
      }
    }
    out.push("---", "");
    out.push(`# ${r.name || "Без названия"}`, "");
    if (r.description) out.push(r.description, "");
    if (r.ingredients && r.ingredients.length) {
      out.push("## Ингредиенты", "");
      for (const ing of r.ingredients) {
        if (typeof ing === "string") { out.push(`- ${ing}`); continue; }
        if (ing.is_heading || (ing.name || "").startsWith("#")) {
          out.push(`### ${(ing.name || "").replace(/^#\s*/, "")}`);
        } else {
          const parts = [];
          if (ing.amount) parts.push(ing.amount);
          if (ing.unit) parts.push(ing.unit);
          const head = parts.join(" ");
          out.push(`- ${head ? head + " " : ""}${ing.name || ""}${ing.notes ? ` (${ing.notes})` : ""}`);
        }
      }
      out.push("");
    }
    if (r.instructions && r.instructions.length) {
      out.push("## Шаги", "");
      r.instructions.forEach((x, i) => out.push(`${i + 1}. ${x}`));
      out.push("");
    }
    if (r.notes) out.push("## Заметки", "", r.notes);
    return out.join("\n");
  }

  RM.editor = { open };
})(window.RM);