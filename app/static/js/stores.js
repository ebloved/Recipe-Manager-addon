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
    const configured = !!store.configured;
    const connected = !!store.connected;
    let status = "⚪ Не подключён";
    if (!configured) status = "🟡 OAuth не настроен";
    else if (connected) status = "🟢 Подключён";

    const meta = [];
    if (connected && store.expires_at) {
      meta.push(`Токен до: ${esc(formatDate(store.expires_at))}`);
    }
    if (connected && store.scopes) {
      meta.push(`Scopes: ${esc(store.scopes)}`);
    }
    if (!configured) {
      meta.push("Администратор должен задать VKUSVILL_CLIENT_ID / SECRET / REDIRECT_URI.");
    }

    let actions = "";
    if (configured) {
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

  function renderResult(data, target) {
    const box = target || $("stores-result");
    if (!box) return;
    const warnings = data.warnings || [];
    box.style.display = "block";
    box.innerHTML = `
      <div style="font-size:14px;font-weight:600;margin-bottom:8px;">Результат сборки корзины</div>
      ${data.cart_url
        ? `<div style="margin-bottom:8px;"><a href="${esc(data.cart_url)}" target="_blank" rel="noopener">Открыть корзину ВкусВилл →</a></div>`
        : '<div style="margin-bottom:8px;color:var(--danger)">Корзина не собрана.</div>'}
      <div style="font-size:13px;color:var(--text-secondary);">Позиций: ${data.items_count || 0}</div>
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
    if (box) {
      box.style.display = "block";
      box.innerHTML = '<div class="loading"><span class="spinner"></span> Собираю корзину… Это может занять до 2 минут.</div>';
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
        btn.textContent = defaultLabel || "🛒 Собрать корзину";
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
