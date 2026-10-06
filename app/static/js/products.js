/* Вкладка «Продукты» — CRUD базы ингредиентов.
 *
 * Требуемые id в index.html:
 *   panel-products              — секция вкладки
 *   products-search             — поле поиска
 *   products-refresh            — кнопка "Обновить"
 *   products-create             — кнопка "Добавить продукт"
 *   products-export             — кнопка "Скачать JSON"
 *   products-include-deleted    — чекбокс "Показать удалённые"
 *   products-stats              — блок статистики
 *   products-container          — список продуктов
 *   products-bulk-bar           — панель массовых действий (скрыта по умолчанию)
 *   products-editor-overlay     — оверлей редактора
 *
 * Требуемые id внутри редактора:
 *   pe-title, pe-close, pe-status
 *   pe-name, pe-brand, pe-barcode, pe-category, pe-image, pe-aliases, pe-serving
 *   pe-calories, pe-protein, pe-fat, pe-carbs, pe-fiber, pe-sugar, pe-sodium, pe-cholesterol
 *   pe-save, pe-delete
 */
"use strict";
(function (RM) {
  const { $, escHtml, setStatus, clearStatus } = RM.utils;
  const { getJSON, postJSON, patchJSON, del } = RM.api;
  const state = RM.state;

  // -----------------------------------------------------------------
  // Локальное состояние
  // -----------------------------------------------------------------
  state.products = state.products || {
    items: [],
    stats: null,
    filter: {
      q: "",
      include_deleted: false,
    },
    selected: new Set(),
    loading: false,
    editing: null,     // текущий редактируемый продукт (или null для нового)
  };

  let searchTimer = null;

  // -----------------------------------------------------------------
  // Setup
  // -----------------------------------------------------------------
  function setup() {
    $("products-search").addEventListener("input", (e) => {
      clearTimeout(searchTimer);
      const q = e.target.value;
      searchTimer = setTimeout(() => {
        state.products.filter.q = q.trim();
        load();
      }, 250);
    });

    $("products-refresh").addEventListener("click", load);

    $("products-create").addEventListener("click", () => openEditor(null));

    $("products-export").addEventListener("click", onExport);

    $("products-include-deleted").addEventListener("change", (e) => {
      state.products.filter.include_deleted = e.target.checked;
      load();
    });

    $("products-editor-overlay").addEventListener("click", (e) => {
      if (e.target === $("products-editor-overlay")) closeEditor();
    });

    // Bulk-операции — делегирование
    $("products-bulk-bar").addEventListener("click", (e) => {
      const action = e.target.closest("[data-bulk]")?.dataset.bulk;
      if (!action) return;
      if (action === "clear") {
        state.products.selected.clear();
        render();
      } else if (action === "delete") {
        onBulkDelete(false);
      } else if (action === "delete-hard") {
        if (confirm("Жёстко удалить выбранные? Отменить будет нельзя.")) {
          onBulkDelete(true);
        }
      } else if (action === "restore") {
        onBulkRestore();
      }
    });
  }

  // -----------------------------------------------------------------
  // Load
  // -----------------------------------------------------------------
  async function load() {
    const container = $("products-container");
    if (!container) return;

    state.products.loading = true;
    container.innerHTML = '<div class="loading"><span class="spinner"></span> Загрузка…</div>';

    const { q, include_deleted } = state.products.filter;
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (include_deleted) params.set("include_deleted", "true");
    params.set("limit", "500");

    try {
      const [listData, statsData] = await Promise.all([
        getJSON(`api/products?${params.toString()}`),
        getJSON("api/products/stats").catch(() => null),
      ]);
      state.products.items = listData.products || [];
      state.products.stats = statsData;
      state.products.loading = false;
      renderStats();
      render();
    } catch (err) {
      state.products.loading = false;
      container.innerHTML = `<div class="empty"><div class="icon">⚠️</div><p>${escHtml(err.message)}</p></div>`;
    }
  }

  // -----------------------------------------------------------------
  // Stats
  // -----------------------------------------------------------------
  function renderStats() {
    const box = $("products-stats");
    if (!box) return;
    const s = state.products.stats;
    if (!s) {
      box.innerHTML = "";
      return;
    }

    box.innerHTML = `
      <div class="prod-stat">
        <span class="prod-stat-num">${s.active}</span>
        <span class="prod-stat-label">активных</span>
      </div>
      <div class="prod-stat">
        <span class="prod-stat-num">${s.with_barcode}</span>
        <span class="prod-stat-label">со штрих-кодом</span>
      </div>
      <div class="prod-stat">
        <span class="prod-stat-num">${s.with_nutrition}</span>
        <span class="prod-stat-label">с КБЖУ</span>
      </div>
      <div class="prod-stat">
        <span class="prod-stat-num">${s.with_vector}</span>
        <span class="prod-stat-label">с вектором</span>
      </div>
      <div class="prod-stat muted">
        <span class="prod-stat-num">${s.deleted}</span>
        <span class="prod-stat-label">удалено</span>
      </div>
    `;
  }

  // -----------------------------------------------------------------
  // Render list
  // -----------------------------------------------------------------
  function render() {
    const container = $("products-container");
    if (!container) return;

    const items = state.products.items;

    if (!items.length) {
      container.innerHTML = `
        <div class="empty">
          <div class="icon">📦</div>
          <p>${state.products.filter.q ? "Ничего не найдено" : "Продуктов пока нет"}</p>
          <p style="font-size:13px;color:var(--text-muted)">
            Нажмите «Добавить продукт» или добавьте ингредиент из рецепта через 🔗
          </p>
        </div>`;
      renderBulkBar();
      return;
    }

    const html = items.map(rowHtml).join("");
    container.innerHTML = `<div class="products-list">${html}</div>`;
    bindRowEvents();
    renderBulkBar();
  }

  function rowHtml(p) {
    const pid = escHtml(p.product_id);
    const checked = state.products.selected.has(p.product_id) ? "checked" : "";
    const deletedCls = p.deleted ? "product-row-deleted" : "";

    const img = p.image_url
      ? `<img class="prod-thumb" src="${escHtml(p.image_url)}" alt="">`
      : `<div class="prod-thumb prod-thumb-placeholder">📦</div>`;

    const barcode = p.barcode
      ? `<span class="prod-tag">🏷 ${escHtml(p.barcode)}</span>`
      : `<span class="prod-tag muted">без barcode</span>`;

    const nutr = p.nutrition_per_100g
      ? `<span class="prod-tag">КБЖУ</span>`
      : `<span class="prod-tag muted">нет КБЖУ</span>`;

    const vectors = (p.vectors && Object.keys(p.vectors).length) > 0
      ? `<span class="prod-tag">vector</span>` : "";

    const aliasesCount = (p.aliases || []).length;
    const aliases = aliasesCount
      ? `<span class="prod-tag">${aliasesCount} alias${aliasesCount === 1 ? "" : "es"}</span>`
      : "";

    const brand = p.brand ? `<span class="prod-brand">${escHtml(p.brand)}</span>` : "";
    const category = p.category ? `<span class="prod-cat">${escHtml(p.category)}</span>` : "";

    const actions = p.deleted
      ? `<button class="btn small" data-restore="${pid}" title="Восстановить">↺ Восстановить</button>`
      : `<button class="btn small" data-edit="${pid}" title="Редактировать">✏️</button>
         <button class="btn small danger" data-delete="${pid}" title="Удалить">🗑</button>`;

    return `
      <div class="product-row ${deletedCls}" data-id="${pid}">
        <label class="prod-check">
          <input type="checkbox" data-select="${pid}" ${checked}>
        </label>
        ${img}
        <div class="prod-info">
          <div class="prod-name">${escHtml(p.name || "(без названия)")}</div>
          <div class="prod-meta">
            ${brand}
            ${category}
          </div>
          <div class="prod-tags">
            ${barcode}
            ${nutr}
            ${vectors}
            ${aliases}
          </div>
        </div>
        <div class="prod-actions">${actions}</div>
      </div>`;
  }

  function bindRowEvents() {
    document.querySelectorAll("[data-select]").forEach((cb) => {
      cb.addEventListener("change", () => {
        const id = cb.dataset.select;
        if (cb.checked) state.products.selected.add(id);
        else state.products.selected.delete(id);
        renderBulkBar();
      });
    });

    document.querySelectorAll("[data-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const p = state.products.items.find((x) => x.product_id === btn.dataset.edit);
        if (p) openEditor(p);
      });
    });

    document.querySelectorAll("[data-delete]").forEach((btn) => {
      btn.addEventListener("click", () => onDelete(btn.dataset.delete));
    });

    document.querySelectorAll("[data-restore]").forEach((btn) => {
      btn.addEventListener("click", () => onRestore(btn.dataset.restore));
    });
  }

  // -----------------------------------------------------------------
  // Bulk bar
  // -----------------------------------------------------------------
  function renderBulkBar() {
    const bar = $("products-bulk-bar");
    if (!bar) return;
    const n = state.products.selected.size;
    if (!n) {
      bar.classList.remove("show");
      bar.innerHTML = "";
      return;
    }

    const hasDeleted = state.products.items.some(
      (p) => state.products.selected.has(p.product_id) && p.deleted
    );
    const hasActive = state.products.items.some(
      (p) => state.products.selected.has(p.product_id) && !p.deleted
    );

    bar.classList.add("show");
    bar.innerHTML = `
      <span class="bulk-count">Выбрано: <b>${n}</b></span>
      <div class="bulk-actions">
        ${hasActive ? `
          <button class="btn small" data-bulk="delete">Мягко удалить</button>
          <button class="btn small danger" data-bulk="delete-hard">Удалить навсегда</button>
        ` : ""}
        ${hasDeleted ? `
          <button class="btn small" data-bulk="restore">Восстановить</button>
        ` : ""}
        <button class="btn small" data-bulk="clear">Снять выделение</button>
      </div>
    `;
  }

  async function onBulkDelete(hard) {
    const ids = [...state.products.selected];
    if (!ids.length) return;
    try {
      const data = await postJSON("api/products/bulk-delete", {
        product_ids: ids,
        hard: hard,
      });
      state.products.selected.clear();
      await load();
      console.log(`Bulk delete: ${data.deleted} удалено, ${data.missing} не найдено`);
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  async function onBulkRestore() {
    const ids = [...state.products.selected];
    if (!ids.length) return;
    try {
      const data = await postJSON("api/products/bulk-restore", { product_ids: ids });
      state.products.selected.clear();
      await load();
      console.log(`Bulk restore: ${data.restored} восстановлено, ${data.missing} не найдено`);
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  // -----------------------------------------------------------------
  // Single item actions
  // -----------------------------------------------------------------
  async function onDelete(id) {
    const p = state.products.items.find((x) => x.product_id === id);
    if (!p) return;
    const name = p.name || "продукт";
    if (!confirm(`Удалить «${name}»?\n\nПродукт будет помечен как удалённый. Связки в рецептах сохранятся — их можно восстановить.`)) return;
    try {
      await del(`api/products/${id}`);
      await load();
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  async function onRestore(id) {
    try {
      await postJSON(`api/products/${id}/restore`, {});
      await load();
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  // -----------------------------------------------------------------
  // Export
  // -----------------------------------------------------------------
  async function onExport() {
    try {
      const data = await getJSON("api/products/export");
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const ts = new Date().toISOString().slice(0, 10);
      a.href = url;
      a.download = `ingredients-${ts}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      alert("Ошибка экспорта: " + err.message);
    }
  }

  // -----------------------------------------------------------------
  // Editor (modal)
  // -----------------------------------------------------------------
  function openEditor(product) {
    state.products.editing = product || { _isNew: true };
    renderEditor();
    $("products-editor-overlay").classList.add("show");
  }

  function closeEditor() {
    state.products.editing = null;
    $("products-editor-overlay").classList.remove("show");
  }

  function renderEditor() {
    const overlay = $("products-editor-overlay");
    const p = state.products.editing;
    if (!p) return;
    const isNew = !!p._isNew;

    const n = p.nutrition_per_100g || {};

    overlay.innerHTML = `
      <div class="editor-panel products-editor-panel">
        <div class="editor-header">
          <h3>${isNew ? "Новый продукт" : "Редактирование продукта"}</h3>
          <button class="editor-close" id="pe-close">×</button>
        </div>
        <div class="editor-body">
          <div class="field">
            <label>Название *</label>
            <input type="text" id="pe-name" value="${escHtml(p.name || "")}"
                   placeholder="Например, Греческий йогурт 2%">
          </div>
          <div class="row">
            <div class="field">
              <label>Бренд</label>
              <input type="text" id="pe-brand" value="${escHtml(p.brand || "")}">
            </div>
            <div class="field">
              <label>Категория</label>
              <input type="text" id="pe-category" value="${escHtml(p.category || "")}">
            </div>
          </div>
          <div class="row">
            <div class="field">
              <label>Штрих-код (GTIN)</label>
              <input type="text" id="pe-barcode" value="${escHtml(p.barcode || "")}"
                     inputmode="numeric" placeholder="4607123456789">
            </div>
            <div class="field">
              <label>Вес 1 шт / порции (г)</label>
              <input type="number" id="pe-serving" min="0" step="0.1"
                     value="${p.serving_size_g ?? ""}">
            </div>
          </div>
          <div class="field">
            <label>Ссылка на фото</label>
            <input type="url" id="pe-image" value="${escHtml(p.image_url || "")}"
                   placeholder="https://…">
          </div>

          <div class="editor-section-title">🥗 Пищевая ценность на 100 г</div>
          <div class="editor-three">
            ${numField("pe-calories", "Калории (kcal)", n.calories)}
            ${numField("pe-protein", "Белки (г)", n.protein)}
            ${numField("pe-fat", "Жиры (г)", n.fat)}
          </div>
          <div class="editor-three">
            ${numField("pe-carbs", "Углеводы (г)", n.carbohydrates)}
            ${numField("pe-fiber", "Клетчатка (г)", n.fiber)}
            ${numField("pe-sugar", "Сахара (г)", n.sugar)}
          </div>
          <div class="editor-three">
            ${numField("pe-sodium", "Натрий (мг)", n.sodium)}
            ${numField("pe-cholesterol", "Холестерин (мг)", n.cholesterol)}
            <div></div>
          </div>

          <div class="editor-section-title">🏷 Синонимы</div>
          <div class="field">
            <label>Альтернативные названия (через запятую)</label>
            <textarea id="pe-aliases" rows="2"
                      placeholder="йогурт греческий 2%, греч. йогурт">${escHtml((p.aliases || []).join(", "))}</textarea>
            <div class="editor-hint">
              Используются при автоматическом связывании ингредиентов в рецептах.
            </div>
          </div>

          <div class="status" id="pe-status"></div>
        </div>
        <div class="editor-footer">
          <div>
            ${!isNew ? `<button class="btn danger" id="pe-delete">🗑 Удалить</button>` : ""}
          </div>
          <div class="editor-footer-right">
            <button class="btn" id="pe-cancel">Отмена</button>
            <button class="btn primary" id="pe-save">💾 Сохранить</button>
          </div>
        </div>
      </div>
    `;

    $("pe-close").addEventListener("click", closeEditor);
    $("pe-cancel").addEventListener("click", closeEditor);

    const delBtn = $("pe-delete");
    if (delBtn) {
      delBtn.addEventListener("click", async () => {
        if (!confirm(`Удалить продукт «${p.name}»?`)) return;
        try {
          await del(`api/products/${p.product_id}`);
          closeEditor();
          await load();
        } catch (err) {
          setStatus($("pe-status"), "Ошибка: " + err.message, "error");
        }
      });
    }

    $("pe-save").addEventListener("click", async () => {
      const payload = collectEditor();
      if (!payload.name) {
        setStatus($("pe-status"), "Укажите название.", "error");
        return;
      }
      const btn = $("pe-save");
      btn.disabled = true;
      btn.textContent = "Сохранение…";
      try {
        if (isNew) {
          await postJSON("api/products", payload);
        } else {
          await patchJSON(`api/products/${p.product_id}`, payload);
        }
        closeEditor();
        await load();
      } catch (err) {
        setStatus($("pe-status"), "Ошибка: " + err.message, "error");
        btn.disabled = false;
        btn.textContent = "💾 Сохранить";
      }
    });
  }

  function numField(id, label, value) {
    const v = (value === 0 || value) ? value : "";
    return `<div class="field">
      <label>${escHtml(label)}</label>
      <input type="number" id="${id}" min="0" step="0.1" value="${v === "" ? "" : escHtml(String(v))}">
    </div>`;
  }

  function collectEditor() {
    const nutrition = {};
    const fields = [
      ["pe-calories", "calories"],
      ["pe-protein", "protein"],
      ["pe-fat", "fat"],
      ["pe-carbs", "carbohydrates"],
      ["pe-fiber", "fiber"],
      ["pe-sugar", "sugar"],
      ["pe-sodium", "sodium"],
      ["pe-cholesterol", "cholesterol"],
    ];
    for (const [id, key] of fields) {
      const raw = $(id).value.trim();
      if (raw !== "") nutrition[key] = raw;
    }

    const aliasesRaw = $("pe-aliases").value || "";
    const aliases = aliasesRaw
      .split(",")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

    const serving = $("pe-serving").value.trim();

    return {
      name: $("pe-name").value.trim(),
      brand: $("pe-brand").value.trim() || null,
      category: $("pe-category").value.trim() || null,
      barcode: $("pe-barcode").value.trim() || null,
      image_url: $("pe-image").value.trim() || null,
      serving_size_g: serving !== "" ? parseFloat(serving) : null,
      aliases: aliases,
      nutrition_per_100g: Object.keys(nutrition).length ? nutrition : null,
    };
  }

  // -----------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------
  RM.products = {
    setup,
    load,
    render,
    openEditor,
    closeEditor,
  };
})(window.RM);