/* Очередь подтверждения связок после массового импорта рецептов.
 *
 * Когда пользователь импортирует много рецептов сразу, каскад матчинга
 * находит кандидатов со средним confidence (0.80–0.95). Спрашивать про
 * каждый отдельно — это 20–30 диалогов подряд. Поэтому кандидаты собираются
 * в очередь, и пользователь разбирает их одним экраном.
 *
 * Сценарии:
 *   1. processAfterImport(recipeIds) — вызывается из imports.js после
 *      batch-импорта. Прогоняет все несвязанные ингредиенты через
 *      /api/matcher/match-batch с queue_pending=true, затем открывает
 *      модалку.
 *   2. open() — открыть очередь вручную (кнопка на вкладке «Продукты»).
 *   3. Каждый элемент: имя ингредиента + предложенный кандидат.
 *      Действия: Подтвердить / Пропустить / Выбрать другое.
 *   4. Подтверждение создаёт алиас в базе продуктов (см. /api/matcher/confirm).
 *
 * Требуемые id в index.html:
 *   matcher-batch-overlay
 *   mb-close, mb-title, mb-subtitle, mb-status
 *   mb-list, mb-empty
 *   mb-footer, mb-confirm-all, mb-skip-all, mb-close-footer
 *
 * Публичный API:
 *   RM.matcherBatch.setup()
 *   RM.matcherBatch.open()
 *   RM.matcherBatch.processAfterImport(recipeIds) -> Promise<number>
 */
"use strict";
(function (RM) {
  const { $, escHtml, setStatus, clearStatus } = RM.utils;
  const { getJSON, postJSON } = RM.api;

  // -----------------------------------------------------------------
  // Локальное состояние
  // -----------------------------------------------------------------
  const s = {
    items: [],              // [{query, normalized, match, candidates, ...}]
    loading: false,
    busy: false,
  };

  // -----------------------------------------------------------------
  // Setup
  // -----------------------------------------------------------------
  function setup() {
    $("mb-close").addEventListener("click", close);
    $("mb-close-footer").addEventListener("click", close);
    $("matcher-batch-overlay").addEventListener("click", (e) => {
      if (e.target === $("matcher-batch-overlay")) close();
    });

    $("mb-confirm-all").addEventListener("click", onConfirmAll);
    $("mb-skip-all").addEventListener("click", onSkipAll);
  }

  // -----------------------------------------------------------------
  // Open / close
  // -----------------------------------------------------------------
  async function open() {
    $("matcher-batch-overlay").classList.add("show");
    clearStatus($("mb-status"));
    await loadQueue();
  }

  function close() {
    $("matcher-batch-overlay").classList.remove("show");
  }

  async function loadQueue() {
    s.loading = true;
    $("mb-list").innerHTML = `<div class="pp-loading"><span class="spinner"></span> Загрузка…</div>`;
    $("mb-empty").style.display = "none";

    try {
      const data = await getJSON("api/matcher/queue");
      s.items = data.items || [];
      render();
    } catch (err) {
      $("mb-list").innerHTML = `<div class="pp-empty error">${escHtml(err.message)}</div>`;
    } finally {
      s.loading = false;
    }
  }

  // -----------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------
  function render() {
    const list = $("mb-list");
    const empty = $("mb-empty");
    const footer = $("mb-footer");
    const subtitle = $("mb-subtitle");

    const n = s.items.length;
    subtitle.textContent = n
      ? `${n} ${n === 1 ? "связка" : "связок"} требует подтверждения`
      : "";

    if (!n) {
      list.innerHTML = "";
      empty.style.display = "block";
      footer.style.display = "none";
      return;
    }

    empty.style.display = "none";
    footer.style.display = "flex";
    list.innerHTML = s.items.map(itemHtml).join("");
    bindItemEvents();
  }

  function itemHtml(item) {
    const match = item.match || {};
    const score = match.score != null ? Math.round(match.score * 100) : null;

    // Основной кандидат
    const img = match.image_url
      ? `<img class="mb-thumb" src="${escHtml(match.image_url)}" alt="">`
      : `<div class="mb-thumb mb-thumb-placeholder">📦</div>`;

    const brand = match.brand ? `<span class="mb-brand">${escHtml(match.brand)}</span>` : "";
    const barcode = match.barcode ? `<span class="mb-tag">🏷 ${escHtml(match.barcode)}</span>` : "";
    const methodTag = match.method
      ? `<span class="mb-tag">${escHtml(methodLabel(match.method))}</span>`
      : "";
    const providerTag = match.provider
      ? `<span class="mb-tag muted">${escHtml(match.provider)}</span>`
      : "";

    // Другие кандидаты (collapsed по умолчанию)
    const otherCandidates = (item.candidates || [])
      .filter((c) => c.product_id !== match.product_id)
      .slice(0, 5);

    const alternativesHtml = otherCandidates.length
      ? `<details class="mb-alts">
           <summary>Другие варианты (${otherCandidates.length})</summary>
           <div class="mb-alt-list">
             ${otherCandidates.map((c) => altRowHtml(item, c)).join("")}
           </div>
         </details>`
      : "";

    return `
      <div class="mb-item" data-item="${escHtml(item.query)}">
        <div class="mb-pair">
          <div class="mb-source">
            <span class="mb-label">Ингредиент</span>
            <span class="mb-value">${escHtml(item.query)}</span>
          </div>
          <div class="mb-arrow">→</div>
          <div class="mb-candidate">
            ${img}
            <div class="mb-info">
              <div class="mb-name">${escHtml(match.name || "")}</div>
              <div class="mb-meta">${brand} ${barcode}</div>
              <div class="mb-tags">
                ${score != null ? `<span class="mb-score">${score}%</span>` : ""}
                ${methodTag}
                ${providerTag}
              </div>
            </div>
          </div>
        </div>

        ${alternativesHtml}

        <div class="mb-actions">
          <button class="btn primary small" data-mb-confirm="${escHtml(item.query)}">
            ✅ Подтвердить
          </button>
          <button class="btn small" data-mb-choose="${escHtml(item.query)}">
            🔍 Выбрать другое
          </button>
          <button class="btn small danger" data-mb-skip="${escHtml(item.query)}">
            ✕ Пропустить
          </button>
        </div>
      </div>`;
  }

  function altRowHtml(item, candidate) {
    const score = candidate.score != null ? Math.round(candidate.score * 100) : null;
    const brand = candidate.brand ? `<span class="mb-brand">${escHtml(candidate.brand)}</span>` : "";
    const img = candidate.image_url
      ? `<img class="mb-thumb" src="${escHtml(candidate.image_url)}" alt="">`
      : `<div class="mb-thumb mb-thumb-placeholder">📦</div>`;

    return `<div class="mb-alt-row" data-mb-alt="${escHtml(item.query)}" data-mb-alt-pid="${escHtml(candidate.product_id)}">
      ${img}
      <div class="mb-info">
        <div class="mb-name">${escHtml(candidate.name || "")}</div>
        <div class="mb-meta">${brand}</div>
        <div class="mb-tags">
          ${score != null ? `<span class="mb-score">${score}%</span>` : ""}
        </div>
      </div>
    </div>`;
  }

  function methodLabel(m) {
    switch (m) {
      case "exact": return "точное";
      case "fuzzy": return "fuzzy";
      case "vector": return "vector";
      case "generative": return "LLM";
      case "manual": return "вручную";
      default: return m;
    }
  }

  // -----------------------------------------------------------------
  // Item events
  // -----------------------------------------------------------------
  function bindItemEvents() {
    document.querySelectorAll("[data-mb-confirm]").forEach((btn) => {
      btn.addEventListener("click", () => onConfirm(btn.dataset.mbConfirm));
    });
    document.querySelectorAll("[data-mb-skip]").forEach((btn) => {
      btn.addEventListener("click", () => onSkip(btn.dataset.mbSkip));
    });
    document.querySelectorAll("[data-mb-choose]").forEach((btn) => {
      btn.addEventListener("click", () => onChooseOther(btn.dataset.mbChoose));
    });
    document.querySelectorAll("[data-mb-alt]").forEach((row) => {
      row.addEventListener("click", () => {
        const q = row.dataset.mbAlt;
        const pid = row.dataset.mbAltPid;
        if (q && pid) onConfirmWithProduct(q, pid);
      });
    });
  }

  // -----------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------
  function findItem(query) {
    return s.items.find((x) => x.query === query);
  }

  async function onConfirm(query) {
    const item = findItem(query);
    if (!item || !item.match) return;
    await onConfirmWithProduct(query, item.match.product_id);
  }

  async function onConfirmWithProduct(query, productId) {
    if (s.busy) return;
    s.busy = true;
    try {
      await postJSON("api/matcher/confirm", {
        name: query,
        product_id: productId,
        add_alias: true,
      });
      s.items = s.items.filter((x) => x.query !== query);
      render();
    } catch (err) {
      setStatus($("mb-status"), "Ошибка: " + err.message, "error");
    } finally {
      s.busy = false;
    }
  }

  async function onSkip(query) {
    if (s.busy) return;
    s.busy = true;
    try {
      await postJSON("api/matcher/queue/remove", { query });
      s.items = s.items.filter((x) => x.query !== query);
      render();
    } catch (err) {
      setStatus($("mb-status"), "Ошибка: " + err.message, "error");
    } finally {
      s.busy = false;
    }
  }

  async function onChooseOther(query) {
    const item = findItem(query);
    if (!item) return;

    // Открываем product-picker поверх
    RM.productPicker.open(query, null, async (productId, product) => {
      if (!productId) return; // отмена
      await onConfirmWithProduct(query, productId);
    });
  }

  async function onConfirmAll() {
    if (s.busy) return;
    if (!s.items.length) return;
    if (!confirm(`Подтвердить все ${s.items.length} связок? Пропущенные останутся в очереди.`)) {
      return;
    }

    s.busy = true;
    const total = s.items.length;
    let done = 0;
    const remaining = [];

    for (const item of s.items) {
      if (!item.match) {
        remaining.push(item);
        continue;
      }
      try {
        await postJSON("api/matcher/confirm", {
          name: item.query,
          product_id: item.match.product_id,
          add_alias: true,
        });
        done += 1;
      } catch (err) {
        remaining.push(item);
      }
    }

    s.items = remaining;
    s.busy = false;
    setStatus($("mb-status"), `Подтверждено ${done} из ${total}.`, "success");
    render();
    setTimeout(() => clearStatus($("mb-status")), 3000);
  }

  async function onSkipAll() {
    if (s.busy) return;
    if (!s.items.length) return;
    if (!confirm(`Пропустить все ${s.items.length} связок? Они будут удалены из очереди.`)) {
      return;
    }
    s.busy = true;
    try {
      await postJSON("api/matcher/queue/clear", {});
      s.items = [];
      render();
      setStatus($("mb-status"), "Очередь очищена.", "success");
      setTimeout(() => clearStatus($("mb-status")), 2000);
    } catch (err) {
      setStatus($("mb-status"), "Ошибка: " + err.message, "error");
    } finally {
      s.busy = false;
    }
  }

  // -----------------------------------------------------------------
  // processAfterImport — вызывается из imports.js
  // -----------------------------------------------------------------
  //
  // recipeIds — список id только что импортированных рецептов.
  // Для каждого рецепта собираем имена ингредиентов, которых ещё нет
  // в связанном виде, и отправляем пачкой в /api/matcher/match-batch
  // с queue_pending=true.
  //
  // Возвращает количество найденных связок, требующих подтверждения.
  // Если таковых нет — модалка не открывается, возвращаем 0.

  async function processAfterImport(recipeIds) {
    if (!Array.isArray(recipeIds) || !recipeIds.length) return 0;

    // Собираем имена несвязанных ингредиентов
    const names = new Set();
    for (const rid of recipeIds) {
      try {
        const data = await getJSON(`api/recipes/${rid}`);
        const recipe = data.recipe;
        if (!recipe) continue;
        const ings = recipe.ingredients || [];
        for (const ing of ings) {
          if (!ing || typeof ing !== "object") continue;
          if (ing.is_heading || (ing.name || "").startsWith("#")) continue;
          if (ing.product_id) continue; // уже связан
          const name = (ing.name || "").trim();
          if (name) names.add(name);
        }
      } catch (err) {
        console.warn(`processAfterImport: не удалось загрузить рецепт ${rid}`, err);
      }
    }

    if (!names.size) return 0;

    try {
      const data = await postJSON("api/matcher/match-batch", {
        names: [...names],
        deduplicate: true,
        queue_pending: true,
      });
      const pending = (data.stats && data.stats.need_confirmation) || 0;
      if (pending > 0) {
        // Открываем очередь
        await open();
      }
      return pending;
    } catch (err) {
      console.warn("processAfterImport: matcher недоступен:", err.message);
      return 0;
    }
  }

  // -----------------------------------------------------------------
  // Public
  // -----------------------------------------------------------------
  RM.matcherBatch = {
    setup,
    open,
    close,
    processAfterImport,
  };
})(window.RM);