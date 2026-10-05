"use strict";
(function (RM) {
  const { $, escHtml, setStatus, clearStatus, scaleAmount } = RM.utils;
  const { getJSON, postJSON, patchJSON, del } = RM.api;
  const state = RM.state;

  state.shoppingItems = [];
  state.shoppingOnlyActive = false;
  state.recipeShopState = null;

  // Сканер
  let nativeStream = null;
  let nativeRaf = null;
  let html5Scanner = null;
  let detectedLock = false;

  // ====================================================================
  // Setup
  // ====================================================================
  function setup() {
    $("shopping-add").addEventListener("click", onAddManual);
    $("shopping-new-name").addEventListener("keydown", (e) => {
      if (e.key === "Enter") onAddManual();
    });
    $("shopping-clear-checked").addEventListener("click", onClearChecked);
    $("shopping-only-active").addEventListener("change", (e) => {
      state.shoppingOnlyActive = e.target.checked;
      render();
    });

    // Barcode modal
    $("shopping-lookup-open").addEventListener("click", openBarcode);
    $("barcode-close").addEventListener("click", closeBarcode);
    $("barcode-overlay").addEventListener("click", (e) => {
      if (e.target === $("barcode-overlay")) closeBarcode();
    });
    $("barcode-search").addEventListener("click", onBarcodeSearch);
    $("barcode-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") onBarcodeSearch();
    });
    $("barcode-scan").addEventListener("click", onBarcodeScan);
    $("barcode-scan-stop").addEventListener("click", stopScan);

    // Add-from-recipe modal
    $("recipe-shop-close").addEventListener("click", closeRecipeShop);
    $("recipe-shop-cancel").addEventListener("click", closeRecipeShop);
    $("recipe-shop-overlay").addEventListener("click", (e) => {
      if (e.target === $("recipe-shop-overlay")) closeRecipeShop();
    });
    $("recipe-shop-all").addEventListener("click", () => toggleAllRecipe(true));
    $("recipe-shop-none").addEventListener("click", () => toggleAllRecipe(false));
    $("recipe-shop-add").addEventListener("click", onRecipeShopAdd);
  }

  // ====================================================================
  // Load & render
  // ====================================================================
  async function load() {
    const container = $("shopping-container");
    container.innerHTML = '<div class="loading"><span class="spinner"></span> Загрузка…</div>';
    try {
      const data = await getJSON("api/shopping");
      state.shoppingItems = data.items || [];
      render();
    } catch (err) {
      container.innerHTML = `<div class="empty"><div class="icon">⚠️</div><p>${escHtml(err.message)}</p></div>`;
    }
  }

  function render() {
    const container = $("shopping-container");
    const items = state.shoppingOnlyActive
      ? state.shoppingItems.filter((i) => !i.checked)
      : state.shoppingItems;

    if (!items.length) {
      container.innerHTML = `<div class="empty">
        <div class="icon">🛒</div>
        <p>${state.shoppingOnlyActive ? "Нет активных товаров." : "Список пуст."}</p>
      </div>`;
      return;
    }

    const active = items.filter((i) => !i.checked);
    const done = items.filter((i) => i.checked);

    let html = `<div class="shopping-list">`;
    if (active.length) html += active.map(rowFor).join("");
    if (done.length) {
      html += `<div class="shopping-divider">Куплено (${done.length})</div>`;
      html += done.map(rowFor).join("");
    }
    html += `</div>`;

    container.innerHTML = html;
    bindRowEvents();
  }

  function rowFor(item) {
    const amountStr = [item.amount, item.unit].filter(Boolean).join(" ");
    const image = item.image_url
      ? `<img class="shop-thumb" src="${escHtml(item.image_url)}" alt="">`
      : `<div class="shop-thumb shop-thumb-placeholder">🛒</div>`;
    const note = item.note ? `<span class="shop-note">${escHtml(item.note)}</span>` : "";
    const brand = item.brand ? `<span class="shop-brand">${escHtml(item.brand)}</span>` : "";
    const source = item.recipe_name
      ? `<span class="shop-source">из «${escHtml(item.recipe_name)}»</span>`
      : "";
    const checked = item.checked ? "checked" : "";

    return `<div class="shop-row ${checked}" data-id="${escHtml(item.id)}">
      <label class="shop-check">
        <input type="checkbox" ${checked ? "checked" : ""} data-toggle="${escHtml(item.id)}">
      </label>
      ${image}
      <div class="shop-info">
        <div class="shop-name">${escHtml(item.name)}</div>
        <div class="shop-meta">
          <button class="shop-qty ${amountStr ? "" : "empty"}" data-qty="${escHtml(item.id)}" title="Изменить количество">
            ${amountStr ? escHtml(amountStr) : "+ кол-во"}
          </button>
          ${brand}
          ${source}
        </div>
        ${note}
      </div>
      <button class="shop-remove" data-remove="${escHtml(item.id)}" title="Удалить">×</button>
    </div>`;
  }

  function bindRowEvents() {
    document.querySelectorAll("[data-toggle]").forEach((cb) => {
      cb.addEventListener("change", () => onToggle(cb.dataset.toggle));
    });
    document.querySelectorAll("[data-remove]").forEach((btn) => {
      btn.addEventListener("click", () => onDelete(btn.dataset.remove));
    });
    document.querySelectorAll("[data-qty]").forEach((btn) => {
      btn.addEventListener("click", () => onEditQty(btn.dataset.qty));
    });
  }

  // ====================================================================
  // Actions
  // ====================================================================
  async function onAddManual() {
    const name = $("shopping-new-name").value.trim();
    if (!name) return;
    const amount = $("shopping-new-amount").value.trim() || null;
    const unit = $("shopping-new-unit").value.trim() || null;
    try {
      const data = await postJSON("api/shopping", { name, amount, unit });
      state.shoppingItems.push(data.item);
      $("shopping-new-name").value = "";
      $("shopping-new-amount").value = "";
      $("shopping-new-unit").value = "";
      render();
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  async function onToggle(id) {
    try {
      const data = await postJSON(`api/shopping/${id}/toggle`, {});
      const idx = state.shoppingItems.findIndex((i) => i.id === id);
      if (idx >= 0) state.shoppingItems[idx] = data.item;
      render();
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  async function onDelete(id) {
    try {
      await del(`api/shopping/${id}`);
      state.shoppingItems = state.shoppingItems.filter((i) => i.id !== id);
      render();
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  async function onClearChecked() {
    if (!confirm("Удалить все купленные товары?")) return;
    try {
      const data = await del("api/shopping/checked");
      state.shoppingItems = state.shoppingItems.filter((i) => !i.checked);
      render();
      console.log(`Удалено: ${data.removed}`);
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  // --- Inline qty edit ---
  async function onEditQty(id) {
    const item = state.shoppingItems.find((i) => i.id === id);
    if (!item) return;
    const row = document.querySelector(`.shop-row[data-id="${id}"]`);
    if (!row) return;
    const meta = row.querySelector(".shop-meta");
    const btn = row.querySelector(".shop-qty");
    if (!meta || !btn || meta.querySelector(".shop-qty-editor")) return;

    btn.style.display = "none";

    const wrap = document.createElement("span");
    wrap.className = "shop-qty-editor";
    wrap.innerHTML = `
      <input type="text" class="shop-qty-input shop-qty-amount" value="${escHtml(item.amount || "")}" placeholder="кол-во" inputmode="decimal">
      <input type="text" class="shop-qty-input shop-qty-unit" value="${escHtml(item.unit || "")}" placeholder="ед.">
      <button class="shop-qty-btn save" title="Сохранить">✓</button>
      <button class="shop-qty-btn cancel" title="Отмена">×</button>
    `;
    meta.insertBefore(wrap, btn.nextSibling);

    const amtInput = wrap.querySelector(".shop-qty-amount");
    const unitInput = wrap.querySelector(".shop-qty-unit");
    amtInput.focus();
    amtInput.select();

    let done = false;
    const finish = async (save) => {
      if (done) return;
      done = true;
      if (!save) { render(); return; }
      const amount = amtInput.value.trim() || null;
      const unit = unitInput.value.trim() || null;
      try {
        const data = await patchJSON(`api/shopping/${id}`, { amount, unit });
        const idx = state.shoppingItems.findIndex((i) => i.id === id);
        if (idx >= 0) state.shoppingItems[idx] = data.item;
        render();
      } catch (err) {
        alert("Ошибка: " + err.message);
        render();
      }
    };

    wrap.querySelector(".shop-qty-btn.save").addEventListener("click", (e) => {
      e.stopPropagation(); finish(true);
    });
    wrap.querySelector(".shop-qty-btn.cancel").addEventListener("click", (e) => {
      e.stopPropagation(); finish(false);
    });
    [amtInput, unitInput].forEach((el) => {
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); finish(true); }
        if (e.key === "Escape") { e.preventDefault(); finish(false); }
      });
      el.addEventListener("click", (e) => e.stopPropagation());
    });
  }

  // ====================================================================
  // Barcode modal
  // ====================================================================
  function openBarcode() {
    stopScan();
    $("barcode-input").value = "";
    $("barcode-result").innerHTML = "";
    clearStatus($("barcode-status"));
    $("barcode-overlay").classList.add("show");
    setTimeout(() => $("barcode-input").focus(), 50);
  }

  function closeBarcode() {
    stopScan();
    $("barcode-overlay").classList.remove("show");
  }

  async function onBarcodeSearch() {
    const barcode = $("barcode-input").value.trim();
    if (!barcode) return;
    const status = $("barcode-status");
    const btn = $("barcode-search");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Ищу…';
    setStatus(status, `Ищу товар ${barcode}…`, "info");
    $("barcode-result").innerHTML = "";
    try {
      const data = await postJSON("api/shopping/lookup", { barcode });
      clearStatus(status);
      renderBarcodeResult(data.product);
    } catch (err) {
      setStatus(status, err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Найти";
    }
  }

  function renderBarcodeResult(p) {
    const image = p.image_url
      ? `<img src="${escHtml(p.image_url)}" alt="">`
      : `<div class="bc-thumb-placeholder">🛒</div>`;
    const source = p.source === "national" ? "🇷🇺 Национальный каталог" : "🌍 OpenFoodFacts";
    const result = $("barcode-result");
    result.innerHTML = `<div class="bc-card">
      <div class="bc-thumb">${image}</div>
      <div class="bc-info">
        <div class="bc-name">${escHtml(p.name)}</div>
        ${p.brand ? `<div class="bc-brand">${escHtml(p.brand)}</div>` : ""}
        ${p.category ? `<div class="bc-cat">${escHtml(p.category)}</div>` : ""}
        <div class="bc-source">${source}</div>
      </div>
    </div>
    <div class="bc-add-row">
      <input type="text" id="bc-add-amount" placeholder="Кол-во" style="max-width:100px">
      <input type="text" id="bc-add-unit" placeholder="ед." style="max-width:80px">
      <button class="btn primary" id="bc-add">+ В список</button>
    </div>`;
    $("bc-add").addEventListener("click", () => addFromBarcode(p));
  }

  async function addFromBarcode(p) {
    const amount = $("bc-add-amount").value.trim() || null;
    const unit = $("bc-add-unit").value.trim() || null;
    try {
      const data = await postJSON("api/shopping", {
        name: p.name,
        brand: p.brand,
        barcode: p.barcode,
        image_url: p.image_url,
        category: p.category,
        amount,
        unit,
        source: p.source,
      });
      state.shoppingItems.push(data.item);
      closeBarcode();
      if (!$("panel-shopping").classList.contains("active")) {
        RM.tabs.switchTo("shopping");
      }
      render();
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  // ====================================================================
  // Barcode scanner (camera)
  // ====================================================================
  async function onBarcodeScan() {
    const status = $("barcode-status");
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus(status, "Браузер не даёт доступ к камере. Нужен HTTPS.", "error");
      return;
    }
    clearStatus(status);

    if ("BarcodeDetector" in window) {
      await startNativeScanner(status);
    } else if (typeof Html5Qrcode !== "undefined") {
      await startHtml5Scanner(status);
    } else {
      setStatus(status, "Библиотека сканирования не загрузилась. Введите код вручную.", "error");
    }
  }

  // --- Native (BarcodeDetector) -------------------------------------
  async function startNativeScanner(status) {
    const video = $("barcode-video");
    const wrapper = $("barcode-scanner");
    resetScanUI();
    try {
      nativeStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      video.srcObject = nativeStream;
      await video.play();
      wrapper.style.display = "block";

      const detector = new BarcodeDetector({
        formats: [
          "ean_13", "ean_8", "upc_a", "upc_e",
          "code_128", "code_39", "qr_code",
        ],
      });

      const tick = async () => {
        if (!nativeStream) return;
        try {
          const codes = await detector.detect(video);
          if (codes.length > 0) {
            const value = (codes[0].rawValue || "").trim();
            if (value && !detectedLock) {
              onCodeDetected(value);
              return;
            }
          }
        } catch (_) { /* ignore frame errors */ }
        nativeRaf = requestAnimationFrame(tick);
      };
      nativeRaf = requestAnimationFrame(tick);
    } catch (err) {
      setStatus(status, "Не удалось открыть камеру: " + (err.message || err), "error");
      stopScan();
    }
  }

  // --- html5-qrcode (iOS / Firefox) ---------------------------------
  async function startHtml5Scanner(status) {
    const wrapper = $("barcode-scanner");
    resetScanUI();
    $("barcode-video").style.display = "none";
    wrapper.style.display = "block";

    let container = $("html5qr-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "html5qr-container";
      container.style.width = "100%";
      container.style.height = "100%";
      wrapper.insertBefore(container, wrapper.firstChild);
    }

    try {
      html5Scanner = new Html5Qrcode("html5qr-container");
      await html5Scanner.start(
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
          const value = (decodedText || "").trim();
          if (value && !detectedLock) onCodeDetected(value);
        },
        () => { /* ignore per-frame errors */ }
      );
    } catch (err) {
      setStatus(status, "Не удалось открыть камеру: " + (err.message || err), "error");
      stopScan();
    }
  }

  // --- Обработка распознавания --------------------------------------
  function onCodeDetected(value) {
    detectedLock = true;
    stopCamera();
    flashDetected(value);
    setTimeout(() => {
      stopScan();
      $("barcode-input").value = value;
      onBarcodeSearch();
    }, 550);
  }

  function flashDetected(value) {
    const frame = document.querySelector(".barcode-scan-frame");
    const status = $("barcode-scan-status");
    const hint = $("barcode-scan-hint");
    if (frame) frame.classList.add("detected");
    if (hint) hint.style.display = "none";
    if (status) {
      status.textContent = "✓ Распознано: " + value;
      status.classList.add("show");
    }
  }

  // --- Остановка только камеры (оверлей остаётся на месте) ----------
  function stopCamera() {
    if (nativeRaf) { cancelAnimationFrame(nativeRaf); nativeRaf = null; }
    if (nativeStream) {
      nativeStream.getTracks().forEach((t) => t.stop());
      nativeStream = null;
    }
    if (html5Scanner) {
      try { html5Scanner.stop().then(() => html5Scanner.clear()); }
      catch (_) { /* ignore */ }
      html5Scanner = null;
    }
  }

  // --- Полная остановка + скрытие оверлея ---------------------------
  function stopScan() {
    stopCamera();
    const wrapper = $("barcode-scanner");
    const video = $("barcode-video");
    const container = $("html5qr-container");
    if (wrapper) wrapper.style.display = "none";
    if (video) { video.srcObject = null; video.style.display = "block"; }
    if (container) container.innerHTML = "";
    resetScanUI();
    detectedLock = false;
  }

  function resetScanUI() {
    const frame = document.querySelector(".barcode-scan-frame");
    const status = $("barcode-scan-status");
    const hint = $("barcode-scan-hint");
    if (frame) frame.classList.remove("detected");
    if (status) { status.classList.remove("show"); status.textContent = ""; }
    if (hint) hint.style.display = "";
  }

  // ====================================================================
  // Add from recipe
  // ====================================================================
  function openRecipeShop(recipe, multiplier) {
    const ingredients = (recipe.ingredients || []).map((ing) =>
      typeof ing === "string" ? { name: ing } : ing
    );
    state.recipeShopState = {
      recipe,
      multiplier: multiplier || 1,
      selected: new Set(
        ingredients
          .map((ing, idx) => (ing.is_heading || (ing.name || "").startsWith("#") ? -1 : idx))
          .filter((i) => i >= 0)
      ),
    };
    $("recipe-shop-title").textContent = `Добавить из «${recipe.name}»`;
    renderRecipeShop();
    $("recipe-shop-overlay").classList.add("show");
  }

  function closeRecipeShop() {
    $("recipe-shop-overlay").classList.remove("show");
    state.recipeShopState = null;
  }

  function renderRecipeShop() {
    const st = state.recipeShopState;
    if (!st) return;
    const ingredients = (st.recipe.ingredients || []).map((ing) =>
      typeof ing === "string" ? { name: ing } : ing
    );
    const body = $("recipe-shop-body");
    if (!ingredients.length) {
      body.innerHTML = `<p style="color:var(--text-secondary);text-align:center">Ингредиентов нет.</p>`;
      return;
    }

    body.innerHTML = `
      <div class="recipe-shop-scale">
        Масштаб порций: ×${st.multiplier}
      </div>
      <ul class="recipe-shop-list">
        ${ingredients.map((ing, idx) => {
          const isHeading = ing.is_heading || (ing.name || "").startsWith("#");
          if (isHeading) {
            const name = (ing.name || "").replace(/^#\s*/, "");
            return `<li class="rs-heading">${escHtml(name)}</li>`;
          }
          const amount = ing.amount
            ? scaleAmount(ing.amount, st.multiplier)
            : null;
          const amountStr = [amount, ing.unit].filter(Boolean).join(" ");
          const checked = st.selected.has(idx) ? "checked" : "";
          return `<li class="rs-item">
            <label>
              <input type="checkbox" ${checked} data-rs-idx="${idx}">
              <span class="rs-name">${escHtml(ing.name || "")}</span>
              ${amountStr ? `<span class="rs-amount">${escHtml(amountStr)}</span>` : ""}
            </label>
          </li>`;
        }).join("")}
      </ul>
      <div class="recipe-shop-summary" id="rs-summary"></div>
    `;

    body.querySelectorAll("[data-rs-idx]").forEach((cb) => {
      cb.addEventListener("change", () => {
        const idx = parseInt(cb.dataset.rsIdx, 10);
        if (cb.checked) st.selected.add(idx);
        else st.selected.delete(idx);
        updateSummary();
      });
    });
    updateSummary();
  }

  function toggleAllRecipe(on) {
    const st = state.recipeShopState;
    if (!st) return;
    const ingredients = (st.recipe.ingredients || []).map((ing) =>
      typeof ing === "string" ? { name: ing } : ing
    );
    st.selected = new Set();
    if (on) {
      ingredients.forEach((ing, idx) => {
        if (!ing.is_heading && !(ing.name || "").startsWith("#")) st.selected.add(idx);
      });
    }
    renderRecipeShop();
  }

  function updateSummary() {
    const st = state.recipeShopState;
    if (!st) return;
    const el = $("rs-summary");
    if (el) el.textContent = `Выбрано: ${st.selected.size}`;
  }

  async function onRecipeShopAdd() {
    const st = state.recipeShopState;
    if (!st) return;
    if (!st.selected.size) {
      alert("Ничего не выбрано.");
      return;
    }
    const btn = $("recipe-shop-add");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Добавление…';
    try {
      const data = await postJSON("api/shopping/from-recipe", {
        recipe_id: st.recipe.id,
        ingredient_indices: [...st.selected],
        multiplier: st.multiplier,
      });
      closeRecipeShop();
      if (!$("panel-shopping").classList.contains("active")) {
        RM.tabs.switchTo("shopping");
      }
      await load();
      console.log(`Добавлено: ${data.added}, объединено: ${data.merged}`);
    } catch (err) {
      alert("Ошибка: " + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Добавить";
    }
  }

  // ====================================================================
  // Быстрое добавление одного ингредиента из detail-view
  // ====================================================================
  async function addIngredient(ing, recipe, multiplier) {
    const name = (ing.name || "").trim();
    if (!name) return;
    const amount = ing.amount ? scaleAmount(ing.amount, multiplier || 1) : null;
    try {
      const data = await postJSON("api/shopping", {
        name,
        amount,
        unit: ing.unit || null,
        note: ing.notes || null,
        recipe_id: recipe?.id || null,
        recipe_name: recipe?.name || null,
        source: "recipe",
      });
      state.shoppingItems.push(data.item);
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  RM.shopping = { setup, load, render, openRecipeShop, addIngredient };
})(window.RM);