/* Вкладка «Продукты» — CRUD базы ингредиентов.
 *
 * Требуемые id в index.html:
 *   panel-products              — секция вкладки
 *   products-search             — поле поиска
 *   products-category-filter    — фильтр по категории
 *   products-show-deleted       — чекбокс "Показать удалённые"
 *   products-add                — кнопка "Новый продукт"
 *   products-lookup             — кнопка "Найти по штрих-коду"
 *   products-container          — список продуктов
 *   product-editor-overlay      — оверлей редактора
 *
 * Требуемые id внутри редактора:
 *   product-editor-title, product-editor-close,
 *   product-editor-name, product-editor-brand, product-editor-barcode,
 *   product-editor-category, product-editor-unit, product-editor-image,
 *   product-editor-cal, product-editor-prot, product-editor-fat,
 *   product-editor-carb, product-editor-fiber, product-editor-sugar,
 *   product-editor-sodium, product-editor-satfat,
 *   product-editor-aliases-list, product-editor-alias-input,
 *   product-editor-alias-add,
 *   product-editor-scanner, product-editor-video,
 *   product-editor-scan-hint, product-editor-scan-status,
 *   product-editor-scan, product-editor-scan-stop,
 *   product-editor-lookup,
 *   product-editor-save, product-editor-delete,
 *   product-editor-cancel, product-editor-status
 */
"use strict";
(function (RM) {
  const { $, escHtml, setStatus, clearStatus } = RM.utils;
  const { getJSON, postJSON, patchJSON, del } = RM.api;
  const state = RM.state;

  // Локальное состояние вкладки продуктов
  state.products = [];
  state.productsFilter = { q: "", category: "", showDeleted: false };
  state.productGroups = [];
  state.groupSuggestions = [];
  state.productSuggestions = [];

  // Редактор продукта
  let editorState = null; // { product, isNew, aliases: [...] }

  const PANTRY_MARKERS = [
    "сушён", "сушен", "специ", "приправ", "лавров", "мускатн",
    "кориандр", "орегано", "паприк", "розмарин", "тимьян", "кориц",
  ];

  function isPantryName(name) {
    const text = String(name || "").toLowerCase().replace(/ё/g, "е");
    if (!text) return false;
    if (/\bсвеж(ий|ая|ие|их|ее|им)\b/.test(text) || text.includes("болгар") || text.includes("сладк")) {
      return false;
    }
    if (text.split(/[^a-zа-яё0-9]+/i).includes("соль")) return true;
    if (text === "перец") return true;
    if (
      text === "сахар"
      || text.startsWith("сахар ")
      || text.startsWith("сахарный")
      || text.startsWith("сахарная пудра")
      || text.startsWith("сахар-песок")
    ) {
      return true;
    }
    if (PANTRY_MARKERS.some((word) => text.includes(word))) return true;
    return text.includes("перец")
      && ["черн", "молот", "красн", "горош"].some((word) => text.includes(word));
  }

  // Сканер в модалке продукта
  let scanNativeStream = null;
  let scanNativeRaf = null;
  let scanHtml5 = null;
  let scanDetectedLock = false;

  const CATEGORY_HINTS = [
    "Овощи", "Фрукты", "Ягоды", "Зелень", "Грибы",
    "Мясо", "Птица", "Рыба", "Морепродукты", "Яйца",
    "Молочное", "Крупы", "Макароны", "Мука", "Бобовые",
    "Хлеб", "Орехи", "Сухофрукты", "Сладости", "Жиры и масла",
    "Соусы", "Специи", "Напитки", "Готовое",
  ];

  // =====================================================================
  // Setup
  // =====================================================================

  function setup() {
    // Тулбар
    $("products-add").addEventListener("click", () => openEditor(null));
    $("products-lookup").addEventListener("click", onQuickLookup);
    $("products-search").addEventListener("input", (e) => {
      state.productsFilter.q = e.target.value.trim();
      render();
    });
    $("products-category-filter").addEventListener("change", (e) => {
      state.productsFilter.category = e.target.value;
      render();
    });
    $("products-show-deleted").addEventListener("change", (e) => {
      state.productsFilter.showDeleted = e.target.checked;
      load();
    });
    
    loadUnlinkedCount();

    // B4: Несвязанные
    const btnUnlinked = $("products-unlinked");
    if (btnUnlinked) btnUnlinked.addEventListener("click", openUnlinked);
    const closeUnlinked = $("unlinked-close");
    if (closeUnlinked) closeUnlinked.addEventListener("click", () => $("unlinked-overlay").classList.remove("show"));

    // Заявки из внешних покупок
    const btnSuggestions = $("products-suggestions");
    if (btnSuggestions) btnSuggestions.addEventListener("click", openProductSuggestions);
    const closeSuggestions = $("product-suggestions-close");
    if (closeSuggestions) closeSuggestions.addEventListener("click", () => {
      $("product-suggestions-overlay").classList.remove("show");
    });
    const suggestionsOverlay = $("product-suggestions-overlay");
    if (suggestionsOverlay) suggestionsOverlay.addEventListener("click", (e) => {
      if (e.target === suggestionsOverlay) suggestionsOverlay.classList.remove("show");
    });

    // Группы продуктов
    const btnGroups = $("products-groups");
    if (btnGroups) btnGroups.addEventListener("click", openGroups);
    const closeGroups = $("product-groups-close");
    if (closeGroups) closeGroups.addEventListener("click", () => {
      $("product-groups-overlay").classList.remove("show");
    });
    const scanGroups = $("product-groups-scan");
    if (scanGroups) scanGroups.addEventListener("click", scanProductGroups);
    const groupsOverlay = $("product-groups-overlay");
    if (groupsOverlay) groupsOverlay.addEventListener("click", (e) => {
      if (e.target === groupsOverlay) groupsOverlay.classList.remove("show");
    });

    // Модалка редактора
    $("product-editor-close").addEventListener("click", closeEditor);
    $("product-editor-cancel").addEventListener("click", closeEditor);
    $("product-editor-overlay").addEventListener("click", (e) => {
      if (e.target === $("product-editor-overlay")) closeEditor();
    });
    $("product-editor-save").addEventListener("click", onSave);
    $("product-editor-delete").addEventListener("click", onDelete);
    $("product-editor-scan").addEventListener("click", onScanClick);
    $("product-editor-scan-stop").addEventListener("click", stopScanner);
    $("product-editor-lookup").addEventListener("click", onLookupBarcode);
    $("product-editor-alias-add").addEventListener("click", onAliasAdd);
    $("product-editor-alias-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        onAliasAdd();
      }
    });
    $("product-editor-barcode").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        onLookupBarcode();
      }
    });
  }

  // =====================================================================
  // Загрузка и рендер
  // =====================================================================

  function openUnlinked() {
    const overlay = $("unlinked-overlay");
    const list = $("unlinked-list");
    if (!overlay || !list) return;
    
    const data = state.unlinkedData || [];
    if (!data.length) {
      list.innerHTML = "<p style='color:var(--success)'>🎉 Все ингредиенты связаны!</p>";
    } else {
      list.innerHTML = data.map(item => `
        <div style="display:flex; justify-content:space-between; align-items:center; padding: 8px 0; border-bottom: 1px solid var(--border);">
          <span style="font-size:14px">${escHtml(item.name)}</span>
          <span style="color:var(--text-muted); font-size:13px; margin-left:12px;">${item.count} рец.</span>
        </div>
      `).join("");
    }
    overlay.classList.add("show");
  }

  async function loadUnlinkedCount() {
    try {
      const data = await getJSON("api/products/unlinked");
      const el = $("unlinked-count");
      if (el) el.textContent = data.total_unique;
      state.unlinkedData = data.unlinked || [];
    } catch (e) {
      console.warn("Unlinked count error:", e);
    }
  }

  async function load() {
    const container = $("products-container");
    container.innerHTML = '<div class="loading"><span class="spinner"></span> Загрузка…</div>';
    try {
      const params = new URLSearchParams();
      params.set("include_deleted", String(state.productsFilter.showDeleted));
      const [data, groupData, suggestionData] = await Promise.all([
        getJSON(`api/ingredients?${params.toString()}`),
        getJSON("api/product-groups").catch((err) => {
          console.warn("Product groups error:", err);
          return { groups: [], suggestions: [] };
        }),
        getJSON("api/products/suggestions?status=pending").catch((err) => {
          console.warn("Product suggestions error:", err);
          return { items: [] };
        }),
      ]);
      state.products = data.products || [];
      state.productGroups = groupData.groups || [];
      state.groupSuggestions = groupData.suggestions || [];
      state.productSuggestions = suggestionData.items || [];
      updateGroupsCount();
      updateProductSuggestionsCount();
      await fillCategoryFilter();
      render();
    } catch (err) {
      container.innerHTML = `<div class="empty"><div class="icon">⚠️</div><p>${escHtml(err.message)}</p></div>`;
    }
  }

  async function refreshGroups() {
    try {
      const data = await getJSON("api/product-groups");
      state.productGroups = data.groups || [];
      state.groupSuggestions = data.suggestions || [];
      updateGroupsCount();
      renderGroupSuggestions();
      render();
    } catch (err) {
      const status = $("product-groups-status");
      if (status) setStatus(status, "Ошибка: " + err.message, "error");
    }
  }

  function updateGroupsCount() {
    const el = $("product-groups-count");
    if (el) el.textContent = (state.groupSuggestions || []).length;
  }

  function updateProductSuggestionsCount() {
    const el = $("product-suggestions-count");
    if (el) el.textContent = (state.productSuggestions || []).length;
  }

  function openProductSuggestions() {
    const overlay = $("product-suggestions-overlay");
    if (!overlay) return;
    clearStatus($("product-suggestions-status"));
    renderProductSuggestions();
    overlay.classList.add("show");
  }

  function renderProductSuggestions() {
    const list = $("product-suggestions-list");
    if (!list) return;
    const items = state.productSuggestions || [];
    if (!items.length) {
      list.innerHTML = `<div class="empty" style="padding:24px 0;">
        <div class="icon">📥</div>
        <p>Новых товаров из покупок нет.</p>
        <p class="hint" style="margin-top:6px;">Когда внешний сервис пришлёт чек, товары появятся здесь.</p>
      </div>`;
      return;
    }
    list.innerHTML = items.map((s) => `
      <div class="group-suggestion" data-product-suggestion-id="${escHtml(s.id)}">
        <div class="group-suggestion-head">
          <div>
            <div class="group-suggestion-title">
              <strong>${escHtml(s.name || "(без названия)")}</strong>
            </div>
            <div class="group-suggestion-key">
              ${s.brand ? escHtml(s.brand) + " · " : ""}
              ${s.category ? escHtml(s.category) + " · " : ""}
              ${s.barcode ? escHtml(s.barcode) : "без GTIN"}
              ${s.created_at ? " · " + escHtml(String(s.created_at).slice(0, 10)) : ""}
            </div>
          </div>
          <div class="group-suggestion-actions">
            <button class="btn primary small" data-product-suggestion-action="approve" data-product-suggestion-id="${escHtml(s.id)}">
              Добавить в продукты
            </button>
            <button class="btn small" data-product-suggestion-action="reject" data-product-suggestion-id="${escHtml(s.id)}">
              Отклонить
            </button>
          </div>
        </div>
      </div>
    `).join("");

    list.querySelectorAll("[data-product-suggestion-action]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const id = btn.dataset.productSuggestionId;
        const action = btn.dataset.productSuggestionAction;
        btn.disabled = true;
        try {
          await postJSON(`api/products/suggestions/${id}/${action}`, {});
          state.productSuggestions = (state.productSuggestions || [])
            .filter((x) => x.id !== id);
          updateProductSuggestionsCount();
          renderProductSuggestions();
          await load();
        } catch (err) {
          setStatus($("product-suggestions-status"), "Ошибка: " + err.message, "error");
          btn.disabled = false;
        }
      });
    });
  }

  function openGroups() {
    const overlay = $("product-groups-overlay");
    if (!overlay) return;
    clearStatus($("product-groups-status"));
    renderGroupSuggestions();
    overlay.classList.add("show");
  }

  function renderGroupSuggestions() {
    const list = $("product-groups-list");
    if (!list) return;
    const suggestions = state.groupSuggestions || [];
    if (!suggestions.length) {
      list.innerHTML = `<div class="empty" style="padding:24px 0;">
        <div class="icon">🏷️</div>
        <p>Похожих продуктов не найдено.</p>
        <p class="hint" style="margin-top:6px;">Нажмите «Найти группы», чтобы проверить базу.</p>
      </div>`;
      return;
    }
    list.innerHTML = suggestions.map((s) => suggestionRow(s)).join("");
    list.querySelectorAll("[data-suggestion-action]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const id = btn.dataset.suggestionId;
        const action = btn.dataset.suggestionAction;
        btn.disabled = true;
        try {
          if (action === "approve") {
            await postJSON(`api/product-groups/suggestions/${id}/approve`, {});
          } else {
            await postJSON(`api/product-groups/suggestions/${id}/reject`, {});
          }
          state.groupSuggestions = (state.groupSuggestions || []).filter((x) => x.id !== id);
          updateGroupsCount();
          renderGroupSuggestions();
          await load();
        } catch (err) {
          setStatus($("product-groups-status"), "Ошибка: " + err.message, "error");
          btn.disabled = false;
        }
      });
    });
  }

  function suggestionRow(s) {
    const products = s.products || [];
    const members = products.map((p) => `
      <div class="group-suggestion-member">
        <span class="group-suggestion-name">${escHtml(p.name || "(без названия)")}</span>
        <span class="group-suggestion-meta">
          ${p.brand ? escHtml(p.brand) + " · " : ""}
          ${p.barcode ? escHtml(p.barcode) : "без GTIN"}
        </span>
      </div>
    `).join("");
    const isAdd = s.type === "add_to_group";
    return `<div class="group-suggestion" data-suggestion-id="${escHtml(s.id)}">
      <div class="group-suggestion-head">
        <div>
          <div class="group-suggestion-title">
            ${isAdd ? "Добавить вариант в группу" : "Похожи на один продукт"}:
            <strong>${escHtml(s.canonical_name || "—")}</strong>
          </div>
          <div class="group-suggestion-key">${escHtml(s.identity_key || "")}</div>
        </div>
        <div class="group-suggestion-actions">
          <button class="btn primary small" data-suggestion-action="approve" data-suggestion-id="${escHtml(s.id)}">
            ${isAdd ? "Добавить" : "Объединить"}
          </button>
          <button class="btn small" data-suggestion-action="reject" data-suggestion-id="${escHtml(s.id)}">
            Не объединять
          </button>
        </div>
      </div>
      <div class="group-suggestion-members">${members}</div>
    </div>`;
  }

  async function scanProductGroups() {
    const status = $("product-groups-status");
    const btn = $("product-groups-scan");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Ищем…";
    }
    clearStatus(status);
    try {
      const data = await postJSON("api/product-groups/suggest", {});
      await refreshGroups();
      setStatus(
        status,
        data.created
          ? `✓ Новых предложений: ${data.created}.`
          : "Новых совпадений нет.",
        "success"
      );
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "🔎 Найти группы";
      }
    }
  }

  async function dissolveGroup(groupId) {
    if (!groupId) return;
    if (!confirm("Разъединить группу? Все варианты снова станут отдельными продуктами.")) return;
    try {
      await postJSON(`api/product-groups/${groupId}/dissolve`, {});
      await load();
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  async function fillCategoryFilter() {
    const sel = $("products-category-filter");
    const current = sel.value;
    let cats = [];
    try {
      const data = await getJSON("api/ingredients/categories");
      cats = data.categories || [];
    } catch (_) {
      // Фоллбэк: собираем из уже загруженных продуктов
      const set = new Set(state.products.map((p) => p.category).filter(Boolean));
      cats = Array.from(set).sort();
    }
    sel.innerHTML = `<option value="">Все категории</option>` +
      cats.map((c) => `<option value="${escHtml(c)}">${escHtml(c)}</option>`).join("");
    sel.value = cats.includes(current) ? current : "";
  }

  function productMatches(p, f, q) {
    if (f.category && p.category !== f.category) return false;
    if (!q) return true;
    if ((p.name || "").toLowerCase().includes(q)) return true;
    for (const a of p.aliases || []) {
      if (String(a).toLowerCase().includes(q)) return true;
    }
    if (p.brand && String(p.brand).toLowerCase().includes(q)) return true;
    if (p.barcode && String(p.barcode).includes(q)) return true;
    return false;
  }

  function groupMatches(group, f, q) {
    const members = group.members || [];
    if (f.category) {
      const inCategory = members.some((m) => m.category === f.category)
        || group.category === f.category;
      if (!inCategory) return false;
    }
    if (!q) return true;
    const haystack = [
      group.canonical_name,
      group.brand,
      group.identity_key,
      ...members.map((m) => m.name),
      ...members.map((m) => m.brand),
      ...members.map((m) => m.barcode),
      ...members.flatMap((m) => m.aliases || []),
    ].filter(Boolean).join(" ").toLowerCase();
    return haystack.includes(q);
  }

  function unitCategory(unit) {
    if (unit.kind === "group") {
      return unit.group.category || (unit.members[0] || {}).category || "Без категории";
    }
    return unit.product.category || "Без категории";
  }

  function unitLabel(unit) {
    if (unit.kind === "group") {
      return (unit.group.canonical_name || (unit.members[0] || {}).name || "").toLowerCase();
    }
    return (unit.product.name || "").toLowerCase();
  }

  function render() {
    const container = $("products-container");
    const f = state.productsFilter;
    const q = (f.q || "").toLowerCase();

    const groupedIds = new Set();
    for (const group of state.productGroups || []) {
      for (const member of group.members || []) groupedIds.add(member.id);
    }

    const units = [];
    for (const group of state.productGroups || []) {
      const members = (group.members || []).filter((m) => !m.deleted);
      if (!members.length) continue;
      if (!groupMatches(group, f, q)) continue;
      units.push({ kind: "group", group, members });
    }
    for (const p of state.products) {
      if (p.group_id && groupedIds.has(p.id)) continue;
      if (!productMatches(p, f, q)) continue;
      units.push({ kind: "product", product: p });
    }

    if (!units.length) {
      container.innerHTML = `<div class="empty">
        <div class="icon">🧺</div>
        <p>${f.q || f.category ? "Ничего не найдено." : "Справочник пуст."}</p>
      </div>`;
      return;
    }

    units.sort((a, b) => {
      const cat = unitCategory(a).localeCompare(unitCategory(b));
      return cat || unitLabel(a).localeCompare(unitLabel(b));
    });

    // Группируем по категориям
    const byCat = {};
    for (const unit of units) {
      const cat = unitCategory(unit);
      (byCat[cat] || (byCat[cat] = [])).push(unit);
    }
    const sortedCats = Object.keys(byCat).sort();

    let html = "";
    for (const cat of sortedCats) {
      html += `<div class="products-group-title">${escHtml(cat)} <span class="products-group-count">${byCat[cat].length}</span></div>`;
      html += `<div class="products-grid">`;
      for (const unit of byCat[cat]) {
        html += unit.kind === "group"
          ? groupCard(unit.group, unit.members)
          : productCard(unit.product);
      }
      html += `</div>`;
    }

    container.innerHTML = html;

    container.querySelectorAll("[data-group-id]").forEach((el) => {
      el.addEventListener("click", (e) => {
        const variant = e.target.closest("[data-variant-id]");
        if (variant) {
          e.stopPropagation();
          const p = state.products.find((x) => x.id === variant.dataset.variantId);
          if (p) openEditor(p);
          return;
        }
        const dissolve = e.target.closest("[data-action='dissolve-group']");
        if (dissolve) {
          e.stopPropagation();
          dissolveGroup(el.dataset.groupId);
          return;
        }
        el.classList.toggle("expanded");
      });
    });
    container.querySelectorAll("[data-product-id]").forEach((el) => {
      el.addEventListener("click", () => {
        const id = el.dataset.productId;
        const p = state.products.find((x) => x.id === id);
        if (p) openEditor(p);
      });
    });
  }

  function productCard(p) {
    const n = p.nutrition_per_100g || {};
    const kcal = n.calories != null ? Math.round(n.calories) : "—";
    const img = p.image_url
      ? `<img class="product-thumb" src="${escHtml(p.image_url)}" alt="" loading="lazy">`
      : `<div class="product-thumb product-thumb-placeholder">🧺</div>`;
    const brand = p.brand ? `<div class="product-brand">${escHtml(p.brand)}</div>` : "";
    const barcode = p.barcode ? `<span class="product-chip barcode">${escHtml(p.barcode)}</span>` : "";
    const deleted = p.deleted ? `<span class="product-chip deleted">удалён</span>` : "";
    const src = p.source === "openfoodfacts"
      ? `<span class="product-chip source-off">OFF</span>`
      : p.source === "base"
        ? `<span class="product-chip source-base">база</span>`
        : "";
    const pantry = p.pantry ? `<span class="product-chip pantry">запас</span>` : "";
    const kcalCls = kcal === "—" ? "product-kcal empty" : "product-kcal";

    return `<div class="product-card ${p.deleted ? "deleted" : ""}" data-product-id="${escHtml(p.id)}">
      ${img}
      <div class="product-info">
        <div class="product-name">${escHtml(p.name || "(без названия)")}</div>
        ${brand}
        <div class="product-meta">
          <span class="${kcalCls}">${kcal} ккал</span>
          ${barcode}
          ${src}
          ${pantry}
          ${deleted}
        </div>
      </div>
    </div>`;
  }

  function groupCard(group, members) {
    const primary = members.find((m) => m.id === group.primary_product_id) || members[0] || {};
    const img = primary.image_url
      ? `<img class="product-thumb" src="${escHtml(primary.image_url)}" alt="" loading="lazy">`
      : `<div class="product-thumb product-thumb-placeholder">🏷️</div>`;
    const brandValue = group.brand || primary.brand;
    const brand = brandValue ? `<div class="product-brand">${escHtml(brandValue)}</div>` : "";
    const barcodes = Array.from(new Set(
      members.map((m) => m.barcode).filter(Boolean)
    ));
    const barcodeChips = barcodes.slice(0, 3)
      .map((b) => `<span class="product-chip barcode">${escHtml(b)}</span>`)
      .join("");
    const more = barcodes.length > 3
      ? `<span class="product-chip">+${barcodes.length - 3}</span>`
      : "";
    const pantry = members.some((m) => m.pantry)
      ? `<span class="product-chip pantry">запас</span>`
      : "";
    const variants = members.map((m) => `
      <div class="product-variant" data-variant-id="${escHtml(m.id)}">
        <div class="product-variant-main">
          <div class="product-variant-name">${escHtml(m.name || "(без названия)")}</div>
          <div class="product-variant-meta">
            ${m.brand ? escHtml(m.brand) + " · " : ""}
            ${m.barcode ? escHtml(m.barcode) : "без GTIN"}
            ${m.default_unit ? " · " + escHtml(m.default_unit) : ""}
          </div>
        </div>
        <span class="product-variant-edit">✏️</span>
      </div>
    `).join("");

    return `<div class="product-card product-group-card" data-group-id="${escHtml(group.id)}">
      ${img}
      <div class="product-info">
        <div class="product-name">${escHtml(group.canonical_name || primary.name || "(без названия)")}</div>
        ${brand}
        <div class="product-meta">
          <span class="product-chip group-count">${members.length} вар.</span>
          ${barcodeChips}
          ${more}
          ${pantry}
        </div>
        <div class="product-variants">
          <div class="product-variants-title">Варианты GTIN</div>
          ${variants}
          <button class="btn small danger" data-action="dissolve-group">Разъединить группу</button>
        </div>
      </div>
    </div>`;
  }

  // =====================================================================
  // Редактор продукта
  // =====================================================================

  function openEditor(product) {
    const isNew = !product || !product.id;
    const p = product || {};
    const n = p.nutrition_per_100g || {};

    editorState = {
      product: p,
      isNew,
      aliases: Array.isArray(p.aliases) ? [...p.aliases] : [],
    };

    $("product-editor-title").textContent = isNew ? "Новый продукт" : "Редактирование";
    $("product-editor-name").value = p.name || "";
    $("product-editor-barcode").value = p.barcode || "";
    $("product-editor-brand").value = p.brand || "";
    $("product-editor-category").value = p.category || "";
    $("product-editor-unit").value = p.default_unit || "г";
    $("product-editor-pantry").checked = typeof p.pantry === "boolean"
      ? p.pantry
      : isPantryName(p.name);
    $("product-editor-cal").value = n.calories ?? "";
    $("product-editor-prot").value = n.protein ?? "";
    $("product-editor-fat").value = n.fat ?? "";
    $("product-editor-carb").value = n.carbohydrates ?? "";
    $("product-editor-fiber").value = n.fiber ?? "";
    $("product-editor-sugar").value = n.sugar ?? "";
    $("product-editor-sodium").value = n.sodium ?? "";
    $("product-editor-satfat").value = n.saturated_fat ?? "";
    $("product-editor-image").value = p.image_url || "";

    renderAliases();

    // Кнопка удаления — только для существующего и не deleted
    const delBtn = $("product-editor-delete");
    if (isNew || p.deleted) {
      delBtn.style.display = "none";
    } else {
      delBtn.style.display = "inline-flex";
      delBtn.textContent = "🗑️ Удалить";
    }

    clearStatus($("product-editor-status"));
    const saveBtn = $("product-editor-save");
    saveBtn.disabled = false;
    saveBtn.textContent = "💾 Сохранить";
    $("product-editor-scanner").style.display = "none";
    $("product-editor-overlay").classList.add("show");
  }

  function closeEditor() {
    stopScanner();
    $("product-editor-overlay").classList.remove("show");
    const saveBtn = $("product-editor-save");
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = "💾 Сохранить";
    }
    editorState = null;
  }

  function renderAliases() {
    const list = $("product-editor-aliases-list");
    if (!editorState || !editorState.aliases.length) {
      list.innerHTML = `<span class="aliases-empty">Нет алиасов</span>`;
      return;
    }
    list.innerHTML = editorState.aliases
      .map((a, idx) => `<span class="alias-chip">
        ${escHtml(a)}
        <button class="alias-chip-remove" data-alias-idx="${idx}" title="Удалить">×</button>
      </span>`)
      .join("");
    list.querySelectorAll("[data-alias-idx]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.dataset.aliasIdx, 10);
        editorState.aliases.splice(idx, 1);
        renderAliases();
      });
    });
  }

  function onAliasAdd() {
    if (!editorState) return;
    const inp = $("product-editor-alias-input");
    const a = inp.value.trim();
    if (!a) return;
    if (editorState.aliases.includes(a)) {
      inp.value = "";
      return;
    }
    editorState.aliases.push(a);
    inp.value = "";
    renderAliases();
  }

  // =====================================================================
  // Сохранение / удаление
  // =====================================================================

  async function onSave() {
    if (!editorState) return;
    const status = $("product-editor-status");
    const name = $("product-editor-name").value.trim();
    if (!name) {
      setStatus(status, "Укажите название.", "error");
      return;
    }

    const nutrition = {};
    const readNum = (id) => {
      const v = $(id).value.trim();
      if (v === "") return null;
      const num = parseFloat(v.replace(",", "."));
      return isNaN(num) ? null : num;
    };
    const fields = {
      calories: readNum("product-editor-cal"),
      protein: readNum("product-editor-prot"),
      fat: readNum("product-editor-fat"),
      carbohydrates: readNum("product-editor-carb"),
      fiber: readNum("product-editor-fiber"),
      sugar: readNum("product-editor-sugar"),
      sodium: readNum("product-editor-sodium"),
      saturated_fat: readNum("product-editor-satfat"),
    };
    for (const [k, v] of Object.entries(fields)) {
      if (v != null) nutrition[k] = v;
    }

    const payload = {
      name,
      barcode: $("product-editor-barcode").value.trim() || null,
      brand: $("product-editor-brand").value.trim() || null,
      category: $("product-editor-category").value.trim() || null,
      default_unit: $("product-editor-unit").value || "г",
      pantry: !!$("product-editor-pantry")?.checked,
      nutrition_per_100g: nutrition,
      image_url: $("product-editor-image").value.trim() || null,
      aliases: editorState.aliases,
    };

    const btn = $("product-editor-save");
    btn.disabled = true;
    btn.textContent = "Сохранение…";
    clearStatus(status);

    try {
      let result;
      if (editorState.isNew) {
        result = await postJSON("api/ingredients", payload);
      } else {
        result = await patchJSON(
          `api/ingredients/${editorState.product.id}`,
          payload
        );
      }
      setStatus(status, `✓ Продукт «${result.product.name}» сохранён.`, "success");
      setTimeout(() => {
        closeEditor();
        load();
      }, 400);
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
      btn.disabled = false;
      btn.textContent = "💾 Сохранить";
    }
  }

  async function onDelete() {
    if (!editorState || editorState.isNew) return;
    const p = editorState.product;
    if (!confirm(`Удалить продукт «${p.name}»? Ссылки в рецептах сохранятся.`)) return;
    try {
      await del(`api/ingredients/${p.id}`);
      closeEditor();
      load();
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  // =====================================================================
  // Быстрый поиск по штрих-коду из тулбара
  // =====================================================================

  async function onQuickLookup() {
    if (RM.productPicker && typeof RM.productPicker.open === "function") {
      RM.productPicker.open(
        "",
        null,
        async (productId /*, product */) => {
          // После выбора/создания продукта обновим список
          if (productId) await load();
        },
        {
          tab: "barcode",
          title: "Найти по штрих-коду",
          subtitle: "Отсканируйте или введите GTIN вручную",
        }
      );
      return;
    }
    // Fallback: если picker почему-то не загружен — старый путь через редактор
    openEditor(null);
    setTimeout(() => $("product-editor-barcode").focus(), 100);
  }

  // =====================================================================
  // Поиск в OFF по штрих-коду из модалки
  // =====================================================================

  async function onLookupBarcode() {
    const barcode = $("product-editor-barcode").value.trim();
    if (!barcode) return;
    const status = $("product-editor-status");
    const btn = $("product-editor-lookup");
    btn.disabled = true;
    btn.textContent = "…";
    clearStatus(status);

    try {
      const data = await postJSON("api/ingredients/lookup", { barcode });

      if (data.local) {
        setStatus(status, "Этот продукт уже есть в справочнике.", "info");
        return;
      }

      if (data.source === "internal_barcode") {
        setStatus(
          status,
          "Весовой товар магазина. Введите название вручную.",
          "info"
        );
        return;
      }

      if (!data.found || !data.product) {
        setStatus(
          status,
          "Не найдено в Open Food Facts. Заполните данные вручную.",
          "info"
        );
        return;
      }

      applyOffProduct(data.product);
      const sourceLabel = data.cached ? "из кэша" : "из Open Food Facts";
      setStatus(status, `✓ Данные подтянуты ${sourceLabel}.`, "success");
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "🔍";
    }
  }

  function applyOffProduct(p) {
    if (!p) return;
    const setIfEmpty = (id, value) => {
      const el = $(id);
      if (!el.value && value != null && value !== "") el.value = value;
    };
    setIfEmpty("product-editor-name", p.name);
    setIfEmpty("product-editor-brand", p.brand);
    setIfEmpty("product-editor-category", p.category);
    setIfEmpty("product-editor-image", p.image_url);

    const n = p.nutrition_per_100g || {};
    setIfEmpty("product-editor-cal", n.calories);
    setIfEmpty("product-editor-prot", n.protein);
    setIfEmpty("product-editor-fat", n.fat);
    setIfEmpty("product-editor-carb", n.carbohydrates);
    setIfEmpty("product-editor-fiber", n.fiber);
    setIfEmpty("product-editor-sugar", n.sugar);
    setIfEmpty("product-editor-sodium", n.sodium);
    setIfEmpty("product-editor-satfat", n.saturated_fat);
  }

  // =====================================================================
  // Сканер штрих-кода внутри модалки
  // =====================================================================

  async function onScanClick() {
    const status = $("product-editor-status");
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus(status, "Камера недоступна. Нужен HTTPS.", "error");
      return;
    }
    clearStatus(status);
    scanDetectedLock = false;

    if ("BarcodeDetector" in window) {
      await startNativeScanner(status);
    } else if (typeof Html5Qrcode !== "undefined") {
      await startHtml5Scanner(status);
    } else {
      setStatus(status, "Библиотека сканирования не загрузилась.", "error");
    }
  }

  async function startNativeScanner(status) {
    const video = $("product-editor-video");
    const wrapper = $("product-editor-scanner");
    resetScannerUI();
    try {
      scanNativeStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      video.srcObject = scanNativeStream;
      await video.play();
      wrapper.style.display = "block";

      const detector = new BarcodeDetector({
        formats: ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39", "qr_code"],
      });

      const tick = async () => {
        if (!scanNativeStream) return;
        try {
          const codes = await detector.detect(video);
          if (codes.length > 0) {
            const v = (codes[0].rawValue || "").trim();
            if (v && !scanDetectedLock) {
              onCodeDetected(v);
              return;
            }
          }
        } catch (_) {}
        scanNativeRaf = requestAnimationFrame(tick);
      };
      scanNativeRaf = requestAnimationFrame(tick);
    } catch (err) {
      setStatus(status, "Не удалось открыть камеру: " + (err.message || err), "error");
      stopScanner();
    }
  }

  async function startHtml5Scanner(status) {
    const wrapper = $("product-editor-scanner");
    resetScannerUI();
    $("product-editor-video").style.display = "none";
    wrapper.style.display = "block";

    let container = document.getElementById("product-editor-html5qr");
    if (!container) {
      container = document.createElement("div");
      container.id = "product-editor-html5qr";
      container.style.width = "100%";
      container.style.height = "100%";
      wrapper.insertBefore(container, wrapper.firstChild);
    }

    try {
      scanHtml5 = new Html5Qrcode("product-editor-html5qr");
      await scanHtml5.start(
        { facingMode: "environment" },
        {
          fps: 10,
          qrbox: { width: 280, height: 180 },
          formatsToSupport: [
            Html5QrcodeSupportedFormats.EAN_13,
            Html5QrcodeSupportedFormats.EAN_8,
            Html5QrcodeSupportedFormats.UPC_A,
            Html5QrcodeSupportedFormats.UPC_E,
            Html5QrcodeSupportedFormats.CODE_128,
            Html5QrcodeSupportedFormats.CODE_39,
            Html5QrcodeSupportedFormats.QR_CODE,
          ],
        },
        (decodedText) => {
          const v = (decodedText || "").trim();
          if (v && !scanDetectedLock) onCodeDetected(v);
        },
        () => {}
      );
    } catch (err) {
      setStatus(status, "Не удалось открыть камеру: " + (err.message || err), "error");
      stopScanner();
    }
  }

  function onCodeDetected(value) {
    scanDetectedLock = true;
    stopCameraOnly();
    flashScannerDetected(value);
    setTimeout(() => {
      stopScanner();
      $("product-editor-barcode").value = value;
      onLookupBarcode();
    }, 500);
  }

  function flashScannerDetected(value) {
    const frame = document.querySelector("#product-editor-scanner .barcode-scan-frame");
    const st = $("product-editor-scan-status");
    const hint = $("product-editor-scan-hint");
    if (frame) frame.classList.add("detected");
    if (hint) hint.style.display = "none";
    if (st) {
      st.textContent = "✓ Распознано: " + value;
      st.classList.add("show");
    }
  }

  function stopCameraOnly() {
    if (scanNativeRaf) { cancelAnimationFrame(scanNativeRaf); scanNativeRaf = null; }
    if (scanNativeStream) {
      scanNativeStream.getTracks().forEach((t) => t.stop());
      scanNativeStream = null;
    }
    if (scanHtml5) {
      try { scanHtml5.stop().then(() => scanHtml5.clear()); } catch (_) {}
      scanHtml5 = null;
    }
  }

  function stopScanner() {
    stopCameraOnly();
    const wrapper = $("product-editor-scanner");
    const video = $("product-editor-video");
    const container = document.getElementById("product-editor-html5qr");
    if (wrapper) wrapper.style.display = "none";
    if (video) { video.srcObject = null; video.style.display = "block"; }
    if (container) container.innerHTML = "";
    resetScannerUI();
    scanDetectedLock = false;
  }

  function resetScannerUI() {
    const frame = document.querySelector("#product-editor-scanner .barcode-scan-frame");
    const st = $("product-editor-scan-status");
    const hint = $("product-editor-scan-hint");
    if (frame) frame.classList.remove("detected");
    if (st) { st.classList.remove("show"); st.textContent = ""; }
    if (hint) hint.style.display = "";
  }

  // =====================================================================
  // Экспорт
  // =====================================================================

  RM.products = { setup, load, render, openEditor, closeEditor };
})(window.RM);