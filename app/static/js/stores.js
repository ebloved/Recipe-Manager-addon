"use strict";
(function (RM) {
  const { $ } = RM.utils;
  const esc = RM.utils.escHtml || ((s) => String(s));

  function formatDate(value) {
    if (!value) return "";
    try {
      return new Date(value).toLocaleString("ru-RU");
    } catch (e) {
      return value;
    }
  }

  function card(store) {
    const isAddress = store.auth_type === "address";
    const isMerchant = store.auth_type === "merchant";
    const configured = !!store.configured;
    const connected = !!store.connected;
    let status = "⚪ Не подключён";
    if (isAddress) {
      status = connected ? "🟢 Адрес указан" : "⚪ Укажите адрес доставки";
    } else if (isMerchant) {
      status = connected ? "🟢 Магазин указан" : "⚪ Укажите магазин";
    } else if (!configured) {
      status = "🟡 OAuth не настроен";
    } else if (connected) {
      status = "🟢 Подключён";
    }

    const meta = [];
    if (isAddress) {
      if (store.address) meta.push(`Адрес доставки: ${esc(store.address)}`);
      if (store.store_name) meta.push(`Магазин: ${esc(store.store_name)}`);
      if (store.hint) meta.push(esc(store.hint));
    } else if (isMerchant) {
      if (store.merchant_id) {
        meta.push(`Магазин: ${esc(store.store_name || "#" + store.merchant_id)}`);
      }
      meta.push("На auchan.ru → «Магазины» → ближайший → «Подробнее» → номер в адресе: <code>/shop/622/</code>.");
      meta.push("Можно вставить ссылку на магазин целиком.");
      if (store.hint) meta.push(esc(store.hint));
    } else {
      if (connected && store.expires_at) {
        meta.push(`Токен до: ${esc(formatDate(store.expires_at))}`);
      }
      if (connected && store.scopes) {
        meta.push(`Scopes: ${esc(store.scopes)}`);
      }
      if (!configured) {
        meta.push("Администратор должен задать VKUSVILL_CLIENT_ID / SECRET / REDIRECT_URI.");
      }
    }

    let actions = "";
    if (isAddress) {
      actions = `
        <div class="store-address-row">
          <input type="text" data-store-address-input="${esc(store.id)}"
                 value="${esc(store.address || "")}"
                 placeholder="Адрес доставки: город, улица, дом, квартира">
          <button class="btn" data-store-action="save-settings" data-store-id="${esc(store.id)}">Сохранить адрес доставки</button>
        </div>
        <div class="store-address-row">
          <input type="text" data-store-search-input="${esc(store.id)}"
                 placeholder="Найти товар, например Kinder Bueno">
          <button class="btn" data-store-action="search" data-store-id="${esc(store.id)}"${connected ? "" : " disabled"}>Найти</button>
        </div>
        <div class="store-actions">
          <button class="btn primary" data-store-action="cart" data-store-id="${esc(store.id)}"${connected ? "" : " disabled"}>🛒 Собрать корзину</button>
          <button class="btn" data-store-action="test" data-store-id="${esc(store.id)}"${connected ? "" : " disabled"}>Проверить</button>
          ${connected ? `<button class="btn" data-store-action="disconnect" data-store-id="${esc(store.id)}" style="color:var(--danger)">Удалить адрес</button>` : ""}
        </div>
      `;
    } else if (isMerchant) {
      actions = `
        <div class="store-address-row">
          <input type="text" data-store-merchant-input="${esc(store.id)}"
                 value="${esc(store.merchant_id || "")}"
                 placeholder="https://www.auchan.ru/shop/622/ или 622">
          <button class="btn" data-store-action="save-settings" data-store-id="${esc(store.id)}">Сохранить магазин</button>
        </div>
        <div class="store-address-row">
          <input type="text" data-store-search-input="${esc(store.id)}"
                 placeholder="Найти товар, например Kinder Bueno">
          <button class="btn" data-store-action="search" data-store-id="${esc(store.id)}"${connected ? "" : " disabled"}>Найти</button>
        </div>
        <div class="store-actions">
          <button class="btn primary" data-store-action="cart" data-store-id="${esc(store.id)}"${connected ? "" : " disabled"}>🔎 Подобрать товары</button>
          <button class="btn" data-store-action="test" data-store-id="${esc(store.id)}"${connected ? "" : " disabled"}>Проверить</button>
          ${connected ? `<button class="btn" data-store-action="disconnect" data-store-id="${esc(store.id)}" style="color:var(--danger)">Удалить магазин</button>` : ""}
        </div>
      `;
    } else if (configured) {
      if (connected) {
        actions = `
          <button class="btn primary" data-store-action="cart" data-store-id="${esc(store.id)}">🛒 Собрать корзину</button>
          <button class="btn" data-store-action="test" data-store-id="${esc(store.id)}">Проверить</button>
          <button class="btn" data-store-action="disconnect" data-store-id="${esc(store.id)}" style="color:var(--danger)">Отключить</button>
        `;
      } else {
        actions = `<button class="btn primary" data-store-action="connect" data-store-id="${esc(store.id)}">Подключить</button>`;
      }
    }

    return `
      <div class="store-card">
        <div class="store-card-head">
          <div class="store-name">${esc(store.name || store.id)}</div>
          <div class="store-status">${status}</div>
        </div>
        <div class="store-meta">${meta.map((m) => `<div>${m}</div>`).join("")}</div>
        <div class="store-actions">${actions}</div>
      </div>
    `;
  }

  async function load() {
    const box = $("stores-list");
    if (!box) return;
    box.innerHTML = '<div class="loading"><span class="spinner"></span> Загрузка магазинов…</div>';
    try {
      const data = await RM.api.getJSON("api/stores");
      const stores = data.stores || [];
      if (!stores.length) {
        box.innerHTML = '<div class="empty"><div class="icon">🏪</div><p>Магазины пока не настроены.</p></div>';
        return;
      }
      box.innerHTML = stores.map(card).join("");
    } catch (e) {
      box.innerHTML = `<div class="hint" style="color:var(--danger)">Ошибка: ${esc(e.message)}</div>`;
    }
  }

  async function connect(storeId) {
    window.location.href = RM.api.api(`api/stores/${storeId}/oauth/start`);
  }

  async function disconnect(storeId) {
    if (!confirm("Отключить магазин? Токен будет удалён.")) return;
    try {
      await RM.api.postJSON(`api/stores/${storeId}/disconnect`, {});
      await load();
    } catch (e) {
      alert("Ошибка отключения: " + e.message);
    }
  }

  async function test(storeId) {
    try {
      const data = await RM.api.postJSON(`api/stores/${storeId}/test`, {});
      alert(data.message || "OK");
    } catch (e) {
      alert("Ошибка проверки: " + e.message);
    }
  }

  async function saveSettings(storeId) {
    const addressInput = document.querySelector(`[data-store-address-input="${storeId}"]`);
    const merchantInput = document.querySelector(`[data-store-merchant-input="${storeId}"]`);
    const input = merchantInput || addressInput;
    const value = input ? input.value.trim() : "";
    const isMerchant = !!merchantInput;
    if (!value) {
      alert(isMerchant ? "Укажите ссылку на магазин или merchantId." : "Укажите адрес доставки.");
      return;
    }
    const btn = document.querySelector(`[data-store-action="save-settings"][data-store-id="${storeId}"]`);
    const old = btn ? btn.textContent : "";
    if (btn) {
      btn.disabled = true;
      btn.textContent = "⏳ Проверяю…";
    }
    try {
      const payload = isMerchant ? { merchant_id: value } : { address: value };
      const data = await RM.api.postJSON(`api/stores/${storeId}/settings`, payload);
      if (isMerchant) {
        alert(`Магазин сохранён: ${data.store_name || "#" + data.merchant_id}`);
      } else {
        const hub = data.store_name ? ` · ${data.store_name}` : "";
        alert(`Адрес сохранён: ${data.address}${hub}`);
      }
      await load();
    } catch (e) {
      alert("Ошибка сохранения: " + e.message);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = old || "Сохранить";
      }
    }
  }

  function renderSearch(data, target) {
    const box = target || $("stores-result");
    if (!box) return;
    const items = data.items || [];
    const total = Number(data.total || 0);
    const found = total > items.length ? `${items.length} из ${total}` : `${items.length}`;
    box.style.display = "block";
    box.innerHTML = `
      <div style="font-size:14px;font-weight:600;margin-bottom:8px;">
        Найдено: ${found}${data.store_name ? ` · ${esc(data.store_name)}` : ""}
      </div>
      ${items.length
        ? items.map((p) => {
          const unit = p.price_per === "weight_kg"
            ? " ₽/кг"
            : p.price_per === "weight_100g"
              ? " ₽/100 г"
              : " ₽";
          const perKg = p.price_per_kg || p.pricePerKg;
          return `
          <div class="store-product">
            <div class="store-product-name">
              ${p.url
                ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.name)}</a>`
                : esc(p.name)}
            </div>
            <div class="store-product-meta">
              ${p.price !== null && p.price !== undefined ? esc(String(p.price)) + unit : "цена н/д"}
              · остаток: ${p.stock !== null && p.stock !== undefined ? esc(String(p.stock)) : "—"}
              ${p.package ? " · " + esc(p.package) : ""}
              ${perKg && p.price_per !== "weight_kg" ? " · " + esc(String(perKg)) + " ₽/кг" : ""}
            </div>
          </div>`;
        }).join("")
        : '<div class="hint">Ничего не найдено.</div>'}
    `;
  }

  async function search(storeId) {
    const input = document.querySelector(`[data-store-search-input="${storeId}"]`);
    const query = input ? input.value.trim() : "";
    if (!query) {
      alert("Введите название товара.");
      return;
    }
    const box = $("stores-result");
    if (box) {
      box.style.display = "block";
      box.innerHTML = '<div class="loading"><span class="spinner"></span> Ищу в Ленте…</div>';
    }
    try {
      const data = await RM.api.postJSON(`api/stores/${storeId}/search`, { query });
      renderSearch(data, box);
    } catch (e) {
      if (box) {
        box.style.display = "block";
        box.innerHTML = `<div style="color:var(--danger)">Ошибка поиска: ${esc(e.message)}</div>`;
      }
    }
  }

  function renderResult(data, target) {
    const box = target || $("stores-result");
    if (!box) return;
    const warnings = data.warnings || [];
    const matches = data.matched_items || [];
    const storeName = data.store_name || "магазин";
    const title = data.links_only ? "Подобранные товары" : "Результат сборки корзины";
    box.style.display = "block";
    box.innerHTML = `
      <div style="font-size:14px;font-weight:600;margin-bottom:8px;">${title}</div>
      ${data.cart_url
        ? `<div style="margin-bottom:8px;"><a href="${esc(data.cart_url)}" target="_blank" rel="noopener">Открыть корзину «${esc(storeName)}» →</a></div>`
        : data.links_only
          ? '<div style="margin-bottom:8px;color:var(--text-secondary);">Корзина не создаётся — откройте карточки и добавьте товары вручную.</div>'
          : '<div style="margin-bottom:8px;color:var(--danger)">Корзина не собрана.</div>'}
      <div style="font-size:13px;color:var(--text-secondary);">Позиций: ${data.items_count || 0}</div>
      ${matches.length
        ? `<div style="margin-top:10px;">${matches.map((m) => {
          const unit = m.price_per === "weight_kg"
            ? " ₽/кг"
            : m.price_per === "weight_100g"
              ? " ₽/100 г"
              : " ₽";
          const qty = m.quantity_label || (m.quantity !== undefined ? `${m.quantity} шт` : "1 шт");
          return `
            <div class="store-product">
              <div class="store-product-name">
                ${m.url
                  ? `<a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.product_name || m.sku)}</a>`
                  : esc(m.product_name || m.sku)}
              </div>
              <div class="store-product-meta">
                ${m.price !== null && m.price !== undefined ? esc(String(m.price)) + unit : "цена н/д"}
                · ${esc(String(qty))}
                ${m.stock !== null && m.stock !== undefined ? " · остаток: " + esc(String(m.stock)) : ""}
              </div>
            </div>`;
        }).join("")}</div>`
        : ""}
      ${warnings.length
        ? `<div style="margin-top:10px;font-size:12px;color:var(--text-muted);"><b>Предупреждения:</b><ul>${warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>`
        : ""}
    `;
  }

  async function buildCart(storeId, opts = {}) {
    const btn = opts.button
      || document.querySelector(`[data-store-action="cart"][data-store-id="${storeId}"]`);
    const defaultLabel = btn ? btn.textContent : "";
    if (btn) {
      btn.disabled = true;
      btn.textContent = "⏳ Собираю…";
    }
    const box = opts.resultBox || $("stores-result");
    const actionText = storeId === "auchan" ? "Подбираю товары…" : "Собираю корзину…";
    if (box) {
      box.style.display = "block";
      box.innerHTML = `<div class="loading"><span class="spinner"></span> ${actionText} Это может занять до 2 минут.</div>`;
    }
    try {
      const data = await RM.api.postJSON(`api/stores/${storeId}/cart`, {});
      renderResult(data, box);
    } catch (e) {
      if (box) {
        box.style.display = "block";
        box.innerHTML = `<div style="color:var(--danger)">Ошибка сборки корзины: ${esc(e.message)}</div>`;
      }
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = defaultLabel || (storeId === "auchan" ? "🔎 Подобрать товары" : "🛒 Собрать корзину");
      }
    }
  }

  function setup() {
    const box = $("stores-list");
    if (box) {
      box.addEventListener("click", (event) => {
        const btn = event.target.closest("[data-store-action]");
        if (!btn) return;
        const action = btn.dataset.storeAction;
        const storeId = btn.dataset.storeId;
        if (action === "connect") connect(storeId);
        else if (action === "disconnect") disconnect(storeId);
        else if (action === "test") test(storeId);
        else if (action === "cart") buildCart(storeId);
        else if (action === "save-settings") saveSettings(storeId);
        else if (action === "search") search(storeId);
      });
    }

    const params = new URLSearchParams(window.location.search);
    const status = params.get("store_status");
    if (status) {
      const storeId = params.get("store_id") || "";
      const message = params.get("message") || "";
      if (status === "connected") {
        alert(`Магазин ${storeId} подключён.`);
      } else {
        alert(`Не удалось подключить магазин ${storeId}: ${message || "неизвестная ошибка"}`);
      }
      params.delete("store_status");
      params.delete("store_id");
      params.delete("message");
      const qs = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
    }
  }

  RM.stores = { setup, load, buildCart };
})(window.RM);
