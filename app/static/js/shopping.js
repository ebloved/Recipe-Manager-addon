"use strict";
(function (RM) {
  const { $, escHtml, setStatus, clearStatus, scaleAmount } = RM.utils;
  const { getJSON, postJSON, patchJSON, del } = RM.api;
  const state = RM.state;

  state.shoppingItems = [];
  state.shoppingOnlyActive = false;
  state.recipeShopState = null;

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
    const amount = [item.amount, item.unit].filter(Boolean).join(" ");
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
          ${amount ? `<span class="shop-amount">${escHtml(amount)}</span>` : ""}
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

  // ====================================================================
  // Barcode lookup
  // ====================================================================
  function openBarcode() {
    $("barcode-input").value = "";
    $("barcode-result").innerHTML = "";
    clearStatus($("barcode-status"));
    $("barcode-overlay").classList.add("show");
    setTimeout(() => $("barcode-input").focus(), 50);
  }

  function closeBarcode() {
    $("barcode-overlay").classList.remove("show");
  }

  async function onBarcodeSearch() {
    const barcode = $("barcode-input").value.trim();
    if (!barcode) return;
    const status = $("barcode-status");
    const btn = $("barcode-search");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
    clearStatus(status);
    $("barcode-result").innerHTML = "";
    try {
      const data = await postJSON("api/shopping/lookup", { barcode });
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

  RM.shopping = { setup, load, render, openRecipeShop };
})(window.RM);