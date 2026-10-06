/* Модалка выбора / создания продукта.
 *
 * Используется из detail-view и редактора рецепта, когда пользователь
 * нажимает 🔗 рядом с ингредиентом.
 *
 * Сценарии:
 *   1. У ингредиента уже есть product_id → показать текущий, дать отвязать
 *      или заменить на другой.
 *   2. У ингредиента нет связки → предложить:
 *      - поиск по базе продуктов (по имени/алиасу),
 *      - поиск по штрих-коду (OpenFoodFacts + локальная база),
 *      - создание нового продукта вручную.
 *
 * Требуемые id в index.html:
 *   product-picker-overlay
 *   pp-close, pp-title, pp-subtitle, pp-status
 *   pp-tabs (контейнер), pp-tab-search, pp-tab-barcode, pp-tab-create
 *   pp-pane-search, pp-pane-barcode, pp-pane-create
 *   pp-search-input, pp-search-results
 *   pp-barcode-input, pp-barcode-search, pp-barcode-result
 *   pp-new-name, pp-new-brand, pp-new-barcode, pp-new-category,
 *   pp-new-aliases, pp-new-create
 *   pp-current, pp-current-info, pp-current-unlink
 *
 * Публичный API:
 *   RM.productPicker.open(name, currentProductId, onSelect)
 *     name             — имя ингредиента (для поиска и создания алиаса)
 *     currentProductId — текущий product_id (или null)
 *     onSelect         — callback(productId | null, product | null)
 *                        null, null = отвязать
 */
"use strict";
(function (RM) {
  const { $, escHtml, setStatus, clearStatus } = RM.utils;
  const { getJSON, postJSON } = RM.api;

  // -----------------------------------------------------------------
  // Локальное состояние
  // -----------------------------------------------------------------
  const s = {
    ingredientName: "",
    currentProductId: null,
    onSelect: null,
    tab: "search",       // search | barcode | create
    searchResults: [],
    searchLoading: false,
    barcodeResult: null,
    barcodeLoading: false,
    creating: false,
    currentProduct: null, // объект продукта, если already linked
  };

  let searchTimer = null;

  // -----------------------------------------------------------------
  // Setup
  // -----------------------------------------------------------------
  function setup() {
    $("pp-close").addEventListener("click", close);
    $("product-picker-overlay").addEventListener("click", (e) => {
      if (e.target === $("product-picker-overlay")) close();
    });

    // Табы
    document.querySelectorAll("[data-pp-tab]").forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.ppTab));
    });

    // Поиск
    $("pp-search-input").addEventListener("input", (e) => {
      clearTimeout(searchTimer);
      const q = e.target.value.trim();
      searchTimer = setTimeout(() => searchProducts(q), 250);
    });

    // Barcode
    $("pp-barcode-search").addEventListener("click", onBarcodeSearch);
    $("pp-barcode-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") onBarcodeSearch();
    });

    // Создание
    $("pp-new-create").addEventListener("click", onCreateFromForm);

    // Отвязка
    $("pp-current-unlink").addEventListener("click", () => {
      if (!confirm(`Отвязать «${s.ingredientName}» от продукта?`)) return;
      const cb = s.onSelect;
      close();
      if (cb) cb(null, null);
    });
  }

  // -----------------------------------------------------------------
  // Open / close
  // -----------------------------------------------------------------
  async function open(name, currentProductId, onSelect) {
    s.ingredientName = (name || "").trim();
    s.currentProductId = currentProductId || null;
    s.onSelect = onSelect || null;
    s.tab = currentProductId ? "search" : "search";
    s.searchResults = [];
    s.barcodeResult = null;
    s.currentProduct = null;

    // Заголовок
    $("pp-title").textContent = "Связать с продуктом";
    $("pp-subtitle").textContent = s.ingredientName || "(без названия)";

    clearStatus($("pp-status"));

    // Текущая связка
    if (s.currentProductId) {
      try {
        const data = await getJSON(`api/products/${s.currentProductId}`);
        s.currentProduct = data.product;
        renderCurrent();
      } catch (err) {
        console.warn("Не удалось загрузить текущий продукт:", err);
        $("pp-current").style.display = "none";
      }
    } else {
      $("pp-current").style.display = "none";
    }

    // Начальное состояние панелей
    $("pp-search-input").value = s.ingredientName;
    $("pp-barcode-input").value = "";
    $("pp-barcode-result").innerHTML = "";
    $("pp-search-results").innerHTML = "";
    resetCreateForm();

    switchTab("search");
    $("product-picker-overlay").classList.add("show");

    // Если ингредиент уже связан — не ищем автоматически
    if (!s.currentProductId && s.ingredientName) {
      setTimeout(() => searchProducts(s.ingredientName), 100);
    }
  }

  function close() {
    $("product-picker-overlay").classList.remove("show");
    s.ingredientName = "";
    s.currentProductId = null;
    s.onSelect = null;
    s.currentProduct = null;
  }

  // -----------------------------------------------------------------
  // Tabs
  // -----------------------------------------------------------------
  function switchTab(tab) {
    s.tab = tab;
    document.querySelectorAll("[data-pp-tab]").forEach((b) => {
      b.classList.toggle("active", b.dataset.ppTab === tab);
    });
    ["search", "barcode", "create"].forEach((t) => {
      const pane = $(`pp-pane-${t}`);
      if (pane) pane.style.display = t === tab ? "block" : "none";
    });

    if (tab === "barcode") {
      setTimeout(() => $("pp-barcode-input").focus(), 60);
    } else if (tab === "search") {
      setTimeout(() => $("pp-search-input").focus(), 60);
    } else if (tab === "create") {
      setTimeout(() => $("pp-new-name").focus(), 60);
    }
  }

  // -----------------------------------------------------------------
  // Текущая связка
  // -----------------------------------------------------------------
  function renderCurrent() {
    const box = $("pp-current");
    const p = s.currentProduct;
    if (!p) {
      box.style.display = "none";
      return;
    }
    box.style.display = "block";

    const img = p.image_url
      ? `<img class="pp-thumb" src="${escHtml(p.image_url)}" alt="">`
      : `<div class="pp-thumb pp-thumb-placeholder">📦</div>`;

    const barcode = p.barcode ? `<span class="pp-tag">🏷 ${escHtml(p.barcode)}</span>` : "";
    const brand = p.brand ? `<span class="pp-brand">${escHtml(p.brand)}</span>` : "";

    $("pp-current-info").innerHTML = `
      ${img}
      <div class="pp-info">
        <div class="pp-name">${escHtml(p.name || "")}</div>
        <div class="pp-meta">${brand} ${barcode}</div>
      </div>
    `;
  }

  // -----------------------------------------------------------------
  // Search by name
  // -----------------------------------------------------------------
  async function searchProducts(query) {
    const q = (query || "").trim();
    const container = $("pp-search-results");
    if (!q) {
      container.innerHTML = `<div class="pp-empty">Введите название для поиска</div>`;
      return;
    }

    s.searchLoading = true;
    container.innerHTML = `<div class="pp-loading"><span class="spinner"></span> Поиск…</div>`;

    try {
      const data = await getJSON(`api/products/search?q=${encodeURIComponent(q)}&limit=20`);
      s.searchResults = data.products || [];
      renderSearchResults();
    } catch (err) {
      container.innerHTML = `<div class="pp-empty error">${escHtml(err.message)}</div>`;
    } finally {
      s.searchLoading = false;
    }
  }

  function renderSearchResults() {
    const container = $("pp-search-results");
    const items = s.searchResults;

    if (!items.length) {
      container.innerHTML = `
        <div class="pp-empty">
          <div style="font-size:32px;opacity:0.5">📭</div>
          <p>Ничего не найдено по «${escHtml(s.ingredientName)}»</p>
          <p style="font-size:12px;color:var(--text-muted)">
            Создайте продукт вручную или поищите по штрих-коду.
          </p>
          <button class="btn primary" data-pp-goto-create>
            + Создать продукт «${escHtml(s.ingredientName)}»
          </button>
        </div>`;
      const gotoBtn = container.querySelector("[data-pp-goto-create]");
      if (gotoBtn) {
        gotoBtn.addEventListener("click", () => {
          switchTab("create");
          $("pp-new-name").value = s.ingredientName;
        });
      }
      return;
    }

    container.innerHTML = items.map((p) => {
      const img = p.image_url
        ? `<img class="pp-thumb" src="${escHtml(p.image_url)}" alt="">`
        : `<div class="pp-thumb pp-thumb-placeholder">📦</div>`;
      const brand = p.brand ? `<span class="pp-brand">${escHtml(p.brand)}</span>` : "";
      const barcode = p.barcode ? `<span class="pp-tag">🏷 ${escHtml(p.barcode)}</span>` : "";
      const isCurrent = p.product_id === s.currentProductId;
      const currentCls = isCurrent ? "pp-result-current" : "";

      return `<div class="pp-result ${currentCls}" data-pp-pick="${escHtml(p.product_id)}">
        ${img}
        <div class="pp-info">
          <div class="pp-name">${escHtml(p.name || "")}${isCurrent ? " ✓" : ""}</div>
          <div class="pp-meta">${brand} ${barcode}</div>
        </div>
        ${isCurrent ? `<span class="pp-current-badge">текущий</span>` : ""}
      </div>`;
    }).join("");

    container.querySelectorAll("[data-pp-pick]").forEach((el) => {
      el.addEventListener("click", () => pickProduct(el.dataset.ppPick));
    });
  }

  async function pickProduct(productId) {
    try {
      const data = await getJSON(`api/products/${productId}`);
      const product = data.product;
      const cb = s.onSelect;
      // Создаём alias "имя ингредиента" → product (если не занят другим)
      try {
        await postJSON(`api/products/${productId}/alias`, { alias: s.ingredientName });
      } catch (err) {
        // Конфликт алиасов — не критично, продолжаем связку
        console.warn("Alias не создан:", err.message);
      }
      close();
      if (cb) cb(productId, product);
    } catch (err) {
      setStatus($("pp-status"), "Ошибка: " + err.message, "error");
    }
  }

  // -----------------------------------------------------------------
  // Barcode lookup
  // -----------------------------------------------------------------
  async function onBarcodeSearch() {
    const barcode = $("pp-barcode-input").value.trim();
    if (!barcode) return;

    const btn = $("pp-barcode-search");
    const result = $("pp-barcode-result");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
    result.innerHTML = `<div class="pp-loading"><span class="spinner"></span> Поиск…</div>`;
    clearStatus($("pp-status"));

    try {
      const data = await postJSON("api/shopping/lookup", { barcode });
      s.barcodeResult = data.product;
      renderBarcodeResult(data.product);
    } catch (err) {
      result.innerHTML = `
        <div class="pp-empty error">
          <p>${escHtml(err.message)}</p>
          <button class="btn" data-pp-create-from-barcode>
            + Создать с barcode ${escHtml(barcode)}
          </button>
        </div>`;
      const btn2 = result.querySelector("[data-pp-create-from-barcode]");
      if (btn2) {
        btn2.addEventListener("click", () => {
          switchTab("create");
          $("pp-new-barcode").value = barcode;
          $("pp-new-name").value = s.ingredientName;
        });
      }
    } finally {
      btn.disabled = false;
      btn.textContent = "Найти";
    }
  }

  function renderBarcodeResult(p) {
    const container = $("pp-barcode-result");
    const img = p.image_url
      ? `<img class="pp-thumb-lg" src="${escHtml(p.image_url)}" alt="">`
      : `<div class="pp-thumb-lg pp-thumb-placeholder">📦</div>`;
    const source = p.source === "openfoodfacts" ? "🌍 OpenFoodFacts" : (p.source || "");

    container.innerHTML = `
      <div class="pp-barcode-card">
        ${img}
        <div class="pp-info">
          <div class="pp-name-lg">${escHtml(p.name || "")}</div>
          ${p.brand ? `<div class="pp-brand">${escHtml(p.brand)}</div>` : ""}
          ${p.category ? `<div class="pp-cat">${escHtml(p.category)}</div>` : ""}
          ${p.barcode ? `<div class="pp-tag">🏷 ${escHtml(p.barcode)}</div>` : ""}
          <div class="pp-source">${escHtml(source)}</div>
        </div>
      </div>
      <div class="pp-barcode-actions">
        <button class="btn primary" data-pp-create-bc>
          ✅ Использовать этот продукт
        </button>
        <button class="btn" data-pp-create-manual>
          ✏️ Открыть в редакторе
        </button>
      </div>
    `;

    container.querySelector("[data-pp-create-bc]").addEventListener("click", () => {
      pickFromBarcode(p);
    });
    container.querySelector("[data-pp-create-manual]").addEventListener("click", () => {
      switchTab("create");
      $("pp-new-name").value = p.name || "";
      $("pp-new-brand").value = p.brand || "";
      $("pp-new-category").value = p.category || "";
      $("pp-new-barcode").value = p.barcode || "";
    });
  }

  async function pickFromBarcode(offProduct) {
    try {
      // Проверим, нет ли уже такого продукта (по barcode)
      const search = await getJSON(`api/products/search?q=${encodeURIComponent(offProduct.barcode || offProduct.name)}&limit=5`);
      const existing = (search.products || []).find(
        (x) => x.barcode && x.barcode === offProduct.barcode
      );

      let productId;
      let product;

      if (existing) {
        productId = existing.product_id;
        product = existing;
      } else {
        // Создаём новый продукт в базе
        const created = await postJSON("api/products", {
          name: offProduct.name,
          brand: offProduct.brand || null,
          barcode: offProduct.barcode || null,
          image_url: offProduct.image_url || null,
          category: offProduct.category || null,
          source: offProduct.source || "manual",
        });
        productId = created.product.product_id;
        product = created.product;
      }

      // Пытаемся добавить алиас
      try {
        await postJSON(`api/products/${productId}/alias`, { alias: s.ingredientName });
      } catch (err) {
        console.warn("Alias не создан:", err.message);
      }

      const cb = s.onSelect;
      close();
      if (cb) cb(productId, product);
    } catch (err) {
      setStatus($("pp-status"), "Ошибка: " + err.message, "error");
    }
  }

  // -----------------------------------------------------------------
  // Create manually
  // -----------------------------------------------------------------
  function resetCreateForm() {
    $("pp-new-name").value = "";
    $("pp-new-brand").value = "";
    $("pp-new-barcode").value = "";
    $("pp-new-category").value = "";
    $("pp-new-aliases").value = s.ingredientName;
  }

  async function onCreateFromForm() {
    const name = $("pp-new-name").value.trim() || s.ingredientName;
    if (!name) {
      setStatus($("pp-status"), "Укажите название продукта.", "error");
      return;
    }

    const btn = $("pp-new-create");
    btn.disabled = true;
    btn.textContent = "Создание…";

    const aliases = $("pp-new-aliases").value
      .split(",")
      .map((x) => x.trim())
      .filter((x) => x.length > 0 && x.toLowerCase() !== name.toLowerCase());

    const payload = {
      name: name,
      brand: $("pp-new-brand").value.trim() || null,
      barcode: $("pp-new-barcode").value.trim() || null,
      category: $("pp-new-category").value.trim() || null,
      aliases: aliases,
      source: "manual",
    };

    try {
      const data = await postJSON("api/products", payload);
      const productId = data.product.product_id;
      const cb = s.onSelect;
      close();
      if (cb) cb(productId, data.product);
    } catch (err) {
      setStatus($("pp-status"), "Ошибка: " + err.message, "error");
      btn.disabled = false;
      btn.textContent = "💾 Создать и связать";
    }
  }

  // -----------------------------------------------------------------
  // Public
  // -----------------------------------------------------------------
  RM.productPicker = { setup, open, close };
})(window.RM);