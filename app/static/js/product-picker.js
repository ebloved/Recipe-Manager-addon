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
 *      - поиск по штрих-коду (ручной ввод + камера через BarcodeDetector
 *        или html5-qrcode),
 *      - создание нового продукта вручную.
 *
 * API-контракт (см. app/routes/ingredients.py):
 *   GET    /api/ingredients?q=&category=&include_deleted=
 *   GET    /api/ingredients/{id}            → {"product": {...}}
 *   POST   /api/ingredients                 → {"product": {...}} (409 если barcode занят)
 *   PATCH  /api/ingredients/{id}            → {"product": {...}}
 *   DELETE /api/ingredients/{id}            → soft delete
 *   POST   /api/ingredients/{id}/aliases    → {"product": {...}}
 *   POST   /api/ingredients/lookup          → {found, local, product, source, message}
 *   POST   /api/ingredients/import-from-off → {product, created}
 *
 * Публичный API:
 *   RM.productPicker.open(name, currentProductId, onSelect, options)
 *     name             — имя ингредиента
 *     currentProductId — текущий id продукта (или null)
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
    tab: "search",
    searchResults: [],
    searchLoading: false,
    barcodeResult: null,
    barcodeLoading: false,
    creating: false,
    currentProduct: null,
  };

  let searchTimer = null;

  // Сканер
  let scanNativeStream = null;
  let scanNativeRaf = null;
  let scanHtml5 = null;
  let scanDetectedLock = false;

  // -----------------------------------------------------------------
  // Setup
  // -----------------------------------------------------------------
  function setup() {
    $("pp-close").addEventListener("click", close);
    $("product-picker-overlay").addEventListener("click", (e) => {
      if (e.target === $("product-picker-overlay")) close();
    });

    document.querySelectorAll("[data-pp-tab]").forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.ppTab));
    });

    $("pp-search-input").addEventListener("input", (e) => {
      clearTimeout(searchTimer);
      const q = e.target.value.trim();
      searchTimer = setTimeout(() => searchProducts(q), 250);
    });

    $("pp-barcode-search").addEventListener("click", onBarcodeSearch);
    $("pp-barcode-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") onBarcodeSearch();
    });

    $("pp-barcode-scan").addEventListener("click", onScanClick);
    $("pp-barcode-scan-stop").addEventListener("click", stopScanner);

    $("pp-new-create").addEventListener("click", onCreateFromForm);

    $("pp-current-unlink").addEventListener("click", () => {
      if (!confirm(`Отвязать «${s.ingredientName}» от продукта?`)) return;
      const cb = s.onSelect;
      stopScanner();
      close();
      if (cb) cb(null, null);
    });
  }

  // -----------------------------------------------------------------
  // Open / close
  // -----------------------------------------------------------------
  async function open(name, currentProductId, onSelect, options) {
    const opts = options || {};

    s.ingredientName = (name || "").trim();
    s.currentProductId = currentProductId || null;
    s.onSelect = onSelect || null;
    s.searchResults = [];
    s.barcodeResult = null;
    s.currentProduct = null;

    $("pp-title").textContent = opts.title || "Связать с продуктом";
    $("pp-subtitle").textContent = s.ingredientName || opts.subtitle || "";

    clearStatus($("pp-status"));

    // Текущая связка
    if (s.currentProductId) {
      try {
        const data = await getJSON(`api/ingredients/${s.currentProductId}`);
        s.currentProduct = data.product;
        renderCurrent();
      } catch (err) {
        console.warn("Не удалось загрузить текущий продукт:", err);
        $("pp-current").style.display = "none";
      }
    } else {
      $("pp-current").style.display = "none";
    }

    $("pp-search-input").value = s.ingredientName;
    $("pp-barcode-input").value = "";
    $("pp-barcode-result").innerHTML = "";
    $("pp-search-results").innerHTML = "";
    resetCreateForm();
    stopScanner();

    switchTab(opts.tab || "search");
    $("product-picker-overlay").classList.add("show");

    if (!s.currentProductId && s.ingredientName && !opts.tab) {
      setTimeout(() => searchProducts(s.ingredientName), 100);
    }
  }

  function close() {
    stopScanner();
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
    if (s.tab === "barcode" && tab !== "barcode") {
      stopScanner();
    }
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
  // Поиск по имени
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
      const data = await getJSON(`api/ingredients?q=${encodeURIComponent(q)}`);
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
    const items = s.searchResults.slice(0, 20);

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
      const isCurrent = p.id === s.currentProductId;
      const currentCls = isCurrent ? "pp-result-current" : "";

      return `<div class="pp-result ${currentCls}" data-pp-pick="${escHtml(p.id)}">
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
      const data = await getJSON(`api/ingredients/${productId}`);
      const product = data.product;
      const cb = s.onSelect;

      // Добавляем alias, если у продукта ещё нет этого имени
      if (s.ingredientName) {
        const aliases = Array.isArray(product.aliases) ? product.aliases : [];
        const alreadyHas = aliases.some(
          (a) => String(a).toLowerCase() === s.ingredientName.toLowerCase()
        );
        if (!alreadyHas) {
          try {
            await postJSON(`api/ingredients/${productId}/aliases`, {
              alias: s.ingredientName,
            });
          } catch (err) {
            console.warn("Alias не создан:", err.message);
          }
        }
      }

      stopScanner();
      close();
      if (cb) cb(productId, product);
    } catch (err) {
      setStatus($("pp-status"), "Ошибка: " + err.message, "error");
    }
  }

  // -----------------------------------------------------------------
  // Поиск по штрих-коду (ручной ввод)
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
      const data = await postJSON("api/ingredients/lookup", { barcode });

      // Уже в локальной базе — сразу показываем как найденное
      if (data.local && data.product) {
        s.barcodeResult = data.product;
        renderBarcodeResult(data.product, { local: true });
        return;
      }

      // Внутренний штрих-код магазина (весовой товар)
      if (data.source === "internal_barcode") {
        result.innerHTML = `
          <div class="pp-empty">
            <p>${escHtml(data.message || "Весовой товар магазина.")}</p>
            <button class="btn" data-pp-create-from-barcode>
              + Создать вручную с barcode ${escHtml(barcode)}
            </button>
          </div>`;
        bindCreateFromBarcode(barcode);
        return;
      }

      // Не найдено в OFF
      if (!data.found || !data.product) {
        result.innerHTML = `
          <div class="pp-empty">
            <p>Не найдено в Open Food Facts.</p>
            <button class="btn" data-pp-create-from-barcode>
              + Создать вручную с barcode ${escHtml(barcode)}
            </button>
          </div>`;
        bindCreateFromBarcode(barcode);
        return;
      }

      // Нашли в OFF — показываем карточку для подтверждения
      s.barcodeResult = data.product;
      renderBarcodeResult(data.product, { local: false, cached: data.cached });
    } catch (err) {
      result.innerHTML = `
        <div class="pp-empty error">
          <p>${escHtml(err.message)}</p>
        </div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = "Найти";
    }
  }

  function bindCreateFromBarcode(barcode) {
    const btn = $("pp-barcode-result").querySelector("[data-pp-create-from-barcode]");
    if (!btn) return;
    btn.addEventListener("click", () => {
      switchTab("create");
      $("pp-new-barcode").value = barcode;
      $("pp-new-name").value = s.ingredientName;
    });
  }

  function renderBarcodeResult(p, meta) {
    const container = $("pp-barcode-result");
    const img = p.image_url
      ? `<img class="pp-thumb-lg" src="${escHtml(p.image_url)}" alt="">`
      : `<div class="pp-thumb-lg pp-thumb-placeholder">📦</div>`;

    let sourceLabel = "";
    if (meta.local) {
      sourceLabel = "📚 Уже в справочнике";
    } else if (p.source === "openfoodfacts" || p.source === "off") {
      sourceLabel = meta.cached ? "🌍 OpenFoodFacts (из кэша)" : "🌍 OpenFoodFacts";
    } else {
      sourceLabel = escHtml(p.source || "");
    }

    const nutrition = p.nutrition_per_100g || {};
    const nutrRow = (nutrition.calories || nutrition.protein || nutrition.fat)
      ? `<div class="pp-nutrition">
           ${nutrition.calories ? `<span>${nutrition.calories} ккал</span>` : ""}
           ${nutrition.protein ? `<span>Б ${nutrition.protein}</span>` : ""}
           ${nutrition.fat ? `<span>Ж ${nutrition.fat}</span>` : ""}
           ${nutrition.carbohydrates ? `<span>У ${nutrition.carbohydrates}</span>` : ""}
         </div>`
      : "";

    container.innerHTML = `
      <div class="pp-barcode-card">
        ${img}
        <div class="pp-info">
          <div class="pp-name-lg">${escHtml(p.name || "")}</div>
          ${p.brand ? `<div class="pp-brand">${escHtml(p.brand)}</div>` : ""}
          ${p.category ? `<div class="pp-cat">${escHtml(p.category)}</div>` : ""}
          ${p.barcode ? `<div class="pp-tag">🏷 ${escHtml(p.barcode)}</div>` : ""}
          ${nutrRow}
          <div class="pp-source">${sourceLabel}</div>
        </div>
      </div>
      <div class="pp-barcode-actions">
        <button class="btn primary" data-pp-use-bc>
          ✅ Использовать этот продукт
        </button>
        <button class="btn" data-pp-edit-manual>
          ✏️ Открыть в редакторе
        </button>
      </div>
    `;

    container.querySelector("[data-pp-use-bc]").addEventListener("click", () => {
      useBarcodeProduct(p, meta.local);
    });
    container.querySelector("[data-pp-edit-manual]").addEventListener("click", () => {
      switchTab("create");
      $("pp-new-name").value = p.name || "";
      $("pp-new-brand").value = p.brand || "";
      $("pp-new-category").value = p.category || "";
      $("pp-new-barcode").value = p.barcode || "";
    });
  }

  async function useBarcodeProduct(p, alreadyLocal) {
    try {
      let productId;
      let product;

      if (alreadyLocal && p.id) {
        // Уже в справочнике — используем как есть
        productId = p.id;
        product = p;
      } else {
        // Сохраняем в базу через import-from-off
        const created = await postJSON("api/ingredients/import-from-off", p);
        productId = created.product.id;
        product = created.product;
      }

      // Добавляем alias, если его нет
      if (s.ingredientName) {
        const aliases = Array.isArray(product.aliases) ? product.aliases : [];
        const alreadyHas = aliases.some(
          (a) => String(a).toLowerCase() === s.ingredientName.toLowerCase()
        );
        if (!alreadyHas) {
          try {
            await postJSON(`api/ingredients/${productId}/aliases`, {
              alias: s.ingredientName,
            });
          } catch (err) {
            console.warn("Alias не создан:", err.message);
          }
        }
      }

      const cb = s.onSelect;
      stopScanner();
      close();
      if (cb) cb(productId, product);
    } catch (err) {
      setStatus($("pp-status"), "Ошибка: " + err.message, "error");
    }
  }

  // -----------------------------------------------------------------
  // Создание продукта вручную
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
      const data = await postJSON("api/ingredients", payload);
      const product = data.product;
      const cb = s.onSelect;
      stopScanner();
      close();
      if (cb) cb(product.id, product);
    } catch (err) {
      // 409 — продукт с таким barcode уже есть. Попробуем найти и использовать.
      if (String(err.message).includes("409") || String(err.message).includes("уже есть")) {
        setStatus(
          $("pp-status"),
          "Продукт с таким штрих-кодом уже есть. Ищем…",
          "info"
        );
        // Попробуем поискать по barcode
        const barcode = payload.barcode;
        if (barcode) {
          try {
            const data = await postJSON("api/ingredients/lookup", { barcode });
            if (data.local && data.product) {
              const cb = s.onSelect;
              stopScanner();
              close();
              if (cb) cb(data.product.id, data.product);
              return;
            }
          } catch (_) {}
        }
      }
      setStatus($("pp-status"), "Ошибка: " + err.message, "error");
      btn.disabled = false;
      btn.textContent = "💾 Создать и связать";
    }
  }

  // -----------------------------------------------------------------
  // Сканер камерой
  // -----------------------------------------------------------------
  async function onScanClick() {
    const status = $("pp-status");
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
    const video = $("pp-barcode-video");
    const wrapper = $("pp-barcode-scanner");
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
    const wrapper = $("pp-barcode-scanner");
    resetScannerUI();
    $("pp-barcode-video").style.display = "none";
    wrapper.style.display = "block";

    let container = document.getElementById("pp-barcode-html5qr");
    if (!container) {
      container = document.createElement("div");
      container.id = "pp-barcode-html5qr";
      container.className = "html5qr-container";
      wrapper.insertBefore(container, wrapper.firstChild);
    }

    try {
      scanHtml5 = new Html5Qrcode("pp-barcode-html5qr");
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
      $("pp-barcode-input").value = value;
      onBarcodeSearch();
    }, 500);
  }

  function flashScannerDetected(value) {
    const frame = document.querySelector("#pp-barcode-scanner .barcode-scan-frame");
    const st = $("pp-barcode-scan-status");
    const hint = $("pp-barcode-scan-hint");
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
    const wrapper = $("pp-barcode-scanner");
    const video = $("pp-barcode-video");
    const container = document.getElementById("pp-barcode-html5qr");
    if (wrapper) wrapper.style.display = "none";
    if (video) { video.srcObject = null; video.style.display = "block"; }
    if (container) container.innerHTML = "";
    resetScannerUI();
    scanDetectedLock = false;
  }

  function resetScannerUI() {
    const frame = document.querySelector("#pp-barcode-scanner .barcode-scan-frame");
    const st = $("pp-barcode-scan-status");
    const hint = $("pp-barcode-scan-hint");
    if (frame) frame.classList.remove("detected");
    if (st) { st.classList.remove("show"); st.textContent = ""; }
    if (hint) hint.style.display = "";
  }

  // -----------------------------------------------------------------
  // Public
  // -----------------------------------------------------------------
  RM.productPicker = { setup, open, close };
})(window.RM);