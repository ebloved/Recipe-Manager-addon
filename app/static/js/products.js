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

  // Редактор продукта
  let editorState = null; // { product, isNew, aliases: [...] }

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

  async function load() {
    const container = $("products-container");
    container.innerHTML = '<div class="loading"><span class="spinner"></span> Загрузка…</div>';
    try {
      const params = new URLSearchParams();
      params.set("include_deleted", String(state.productsFilter.showDeleted));
      const data = await getJSON(`api/ingredients?${params.toString()}`);
      state.products = data.products || [];
      await fillCategoryFilter();
      render();
    } catch (err) {
      container.innerHTML = `<div class="empty"><div class="icon">⚠️</div><p>${escHtml(err.message)}</p></div>`;
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

  function render() {
    const container = $("products-container");
    const f = state.productsFilter;

    let items = state.products.slice();
    if (f.q) {
      const q = f.q.toLowerCase();
      items = items.filter((p) => {
        if ((p.name || "").toLowerCase().includes(q)) return true;
        for (const a of p.aliases || []) {
          if (String(a).toLowerCase().includes(q)) return true;
        }
        if (p.brand && String(p.brand).toLowerCase().includes(q)) return true;
        if (p.barcode && String(p.barcode).includes(q)) return true;
        return false;
      });
    }
    if (f.category) {
      items = items.filter((p) => p.category === f.category);
    }

    if (!items.length) {
      container.innerHTML = `<div class="empty">
        <div class="icon">🧺</div>
        <p>${f.q || f.category ? "Ничего не найдено." : "Справочник пуст."}</p>
      </div>`;
      return;
    }

    // Группируем по категориям
    const byCat = {};
    for (const p of items) {
      const cat = p.category || "Без категории";
      (byCat[cat] || (byCat[cat] = [])).push(p);
    }
    const sortedCats = Object.keys(byCat).sort();

    let html = "";
    for (const cat of sortedCats) {
      html += `<div class="products-group-title">${escHtml(cat)} <span class="products-group-count">${byCat[cat].length}</span></div>`;
      html += `<div class="products-grid">`;
      for (const p of byCat[cat]) html += productCard(p);
      html += `</div>`;
    }

    container.innerHTML = html;

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
          ${deleted}
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
    $("product-editor-scanner").style.display = "none";
    $("product-editor-overlay").classList.add("show");
  }

  function closeEditor() {
    stopScanner();
    $("product-editor-overlay").classList.remove("show");
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