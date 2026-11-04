/* UI матчинга ингредиентов с продуктами.
 *
 * Публичное API:
 *   RM.matcher.openForRecipe(recipe, ingredientIndex)  — открыть модалку для одного ингредиента
 *   RM.matcher.openBatch(recipe)                        — открыть модалку для всех несвязанных
 *   RM.matcher.linkIngredient(recipeId, ingredientIndex, productId) — применить одну связку
 *
 * Модалки создаются динамически при первом вызове — id фиксированы:
 *   matcher-overlay       — оверлей
 *   matcher-panel         — панель
 *   matcher-title         — заголовок
 *   matcher-query         — текст запроса (имя ингредиента)
 *   matcher-close         — закрыть
 *   matcher-status        — плашка статуса
 *   matcher-search-input  — поле поиска по продуктам
 *   matcher-candidates    — список кандидатов
 *   matcher-manual-btn    — открыть редактор нового продукта
 *   matcher-skip-btn      — пропустить (для batch-режима)
 */
"use strict";
(function (RM) {
  const { $, escHtml, setStatus, clearStatus, normalize } = RM.utils || {};
  const { getJSON, postJSON } = RM.api;
  const state = RM.state;

  let overlayEl = null;
  let currentContext = null; // { recipe, ingredientIndex, name, isBatch, queue, onDone }

  // =====================================================================
  // Публичное API
  // =====================================================================

  function setup() {
    // Ничего не делаем при инициализации — модалка создаётся лениво
  }

  async function openForRecipe(recipe, ingredientIndex, onDone) {
    const ing = getIngredient(recipe, ingredientIndex);
    if (!ing) return;
    const name = getIngredientName(ing);
    if (!name) return;

    currentContext = {
      recipe,
      ingredientIndex,
      name,
      isBatch: false,
      onDone: onDone || null,
    };
    ensureOverlay();
    await runMatch(name, recipe);
  }

  async function openBatch(recipe, onDone) {
    const ingredients = getIngredients(recipe);
    const unmatched = [];
    ingredients.forEach((ing, idx) => {
      if (ing && typeof ing === "object" && ing.product_id) return; // уже связан
      const name = getIngredientName(ing);
      if (!name) return;
      if (ing.is_heading || name.startsWith("#")) return; // заголовки не связываем
      unmatched.push({ index: idx, name });
    });

    if (!unmatched.length) {
      alert("Все ингредиенты уже связаны с продуктами.");
      return;
    }

    currentContext = {
      recipe,
      isBatch: true,
      queue: unmatched,
      onDone: onDone || null,
    };
    ensureOverlay();
    await runNextInQueue();
  }

  // =====================================================================
  // Логика очереди (batch-режим)
  // =====================================================================

  async function runNextInQueue() {
    if (!currentContext || !currentContext.isBatch) return;
    if (!currentContext.queue.length) {
      closeOverlay();
      if (currentContext.onDone) currentContext.onDone({ completed: true });
      return;
    }
    const next = currentContext.queue[0];
    currentContext.ingredientIndex = next.index;
    currentContext.name = next.name;
    await runMatch(next.name, currentContext.recipe);
  }

  function skipCurrent() {
    if (!currentContext) return;
    if (currentContext.isBatch) {
      currentContext.queue.shift();
      runNextInQueue();
    } else {
      closeOverlay();
    }
  }

  // =====================================================================
  // Матчинг и рендер
  // =====================================================================

  async function runMatch(name, recipe) {
    setTitle(name, currentContext.isBatch);
    setStatus($("matcher-status"), "Ищу соответствие…", "info");
    $("matcher-candidates").innerHTML = "";
    $("matcher-search-input").value = "";

    try {
      const data = await postJSON("api/matcher/match", {
        name,
        context: recipe ? { recipe_name: recipe.name } : null,
      });
      renderMatchResult(data);
    } catch (err) {
      setStatus($("matcher-status"), "Ошибка: " + err.message, "error");
    }
  }

  function renderMatchResult(data) {
    const status = $("matcher-status");
    const candidates = data.candidates || [];
    const match = data.match;

    if (data.decision === "matched" && match) {
      setStatus(status, "✓ Найдено точное соответствие. Подтвердить?", "success");
      renderCandidates([match, ...candidates.filter((c) => c.product_id !== match.product_id)]);
      return;
    }

    if (data.decision === "suggest" && candidates.length) {
      setStatus(status, "Возможно, одно из этих. Выберите подходящее.", "info");
      renderCandidates(candidates);
      return;
    }

    // not_found
    setStatus(status, "Не найдено в справочнике. Введите название вручную или добавьте продукт.", "info");
    $("matcher-candidates").innerHTML = `
      <div class="matcher-empty">
        <div class="matcher-empty-icon">🔍</div>
        <p>Ничего похожего нет в базе продуктов.</p>
        <button class="btn" id="matcher-manual-btn">✏️ Создать новый продукт</button>
      </div>`;
    const manualBtn = $("matcher-manual-btn");
    if (manualBtn) {
      manualBtn.addEventListener("click", openManualCreator);
    }
  }

  function renderCandidates(candidates) {
    const container = $("matcher-candidates");
    if (!candidates.length) {
      container.innerHTML = `<div class="matcher-empty"><p>Нет кандидатов.</p></div>`;
      return;
    }

    container.innerHTML = candidates.map((c) => {
      const img = c.image_url
        ? `<img class="matcher-thumb" src="${escHtml(c.image_url)}" alt="">`
        : `<div class="matcher-thumb matcher-thumb-placeholder">🧺</div>`;
      const brand = c.brand ? `<span class="matcher-brand">${escHtml(c.brand)}</span>` : "";
      const method = methodBadge(c.method);
      const score = c.score ? `<span class="matcher-score">${Math.round(c.score * 100)}%</span>` : "";
      const alias = c.matched_alias ? `<span class="matcher-alias">через «${escHtml(c.matched_alias)}»</span>` : "";
      const n = c.nutrition_per_100g || {};
      const kcal = n.calories != null ? `<span class="matcher-kcal">${Math.round(n.calories)} ккал/100г</span>` : "";

      return `<div class="matcher-candidate" data-product-id="${escHtml(c.product_id)}">
        ${img}
        <div class="matcher-info">
          <div class="matcher-name">${escHtml(c.name || "(без названия)")} ${score}</div>
          <div class="matcher-meta">${brand} ${method} ${kcal}</div>
          ${alias ? `<div class="matcher-sub">${alias}</div>` : ""}
        </div>
        <button class="matcher-choose-btn">Привязать</button>
      </div>`;
    }).join("");

    container.querySelectorAll(".matcher-candidate").forEach((el) => {
      el.addEventListener("click", () => {
        const productId = el.dataset.productId;
        confirmLink(productId);
      });
    });
  }

  function methodBadge(method) {
    const map = {
      exact: `<span class="matcher-method exact">точное</span>`,
      fuzzy: `<span class="matcher-method fuzzy">похожее</span>`,
      vector: `<span class="matcher-method vector">семантика</span>`,
      generative: `<span class="matcher-method gen">ИИ</span>`,
      manual: `<span class="matcher-method manual">вручную</span>`,
    };
    return map[method] || "";
  }

  // =====================================================================
  // Действия
  // =====================================================================

  async function confirmLink(productId) {
    if (!currentContext) return;
    const status = $("matcher-status");
    setStatus(status, "Применяю связку…", "info");

    try {
      await postJSON("api/matcher/confirm", {
        name: currentContext.name,
        product_id: productId,
        add_alias: true,
        apply_to_recipe_id: currentContext.recipe ? currentContext.recipe.id : null,
      });

      // Обновляем локальную копию рецепта
      if (currentContext.recipe && currentContext.recipe.ingredients) {
        const ing = currentContext.recipe.ingredients[currentContext.ingredientIndex];
        if (ing && typeof ing === "object") {
          ing.product_id = productId;
        }
      }

      if (currentContext.isBatch) {
        currentContext.queue.shift();
        await runNextInQueue();
      } else {
        closeOverlay();
        if (currentContext.onDone) currentContext.onDone({ linked: true, productId });
      }
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
    }
  }

  function openManualCreator() {
    // Закрываем текущую модалку, открываем редактор продукта
    // с предзаполненным именем.
    const name = currentContext ? currentContext.name : "";
    closeOverlay();
    if (RM.products && RM.products.openEditor) {
      RM.products.openEditor(null);
      // Заполнить имя после открытия (отложенно)
      setTimeout(() => {
        const nameInput = document.getElementById("product-editor-name");
        if (nameInput) nameInput.value = name;
      }, 100);
    }
  }

  // =====================================================================
  // Утилиты
  // =====================================================================

  function getIngredients(recipe) {
    return (recipe && recipe.ingredients) || [];
  }

  function getIngredient(recipe, idx) {
    const arr = getIngredients(recipe);
    return arr[idx] || null;
  }

  function getIngredientName(ing) {
    if (!ing) return "";
    if (typeof ing === "string") return ing.trim();
    return (ing.name || "").trim();
  }

  // =====================================================================
  // Оверлей: создание и управление
  // =====================================================================

  function ensureOverlay() {
    if (overlayEl) {
      overlayEl.classList.add("show");
      return;
    }
    const html = `
      <div class="matcher-overlay" id="matcher-overlay">
        <div class="matcher-panel">
          <div class="matcher-header">
            <h3 id="matcher-title">Связать ингредиент</h3>
            <button class="matcher-close" id="matcher-close">×</button>
          </div>

          <div class="matcher-query-box">
            <span class="matcher-query-label">Ингредиент:</span>
            <span class="matcher-query" id="matcher-query"></span>
          </div>

          <div class="status" id="matcher-status"></div>

          <div class="matcher-search-wrap">
            <input type="text" id="matcher-search-input"
                   placeholder="Уточнить поиск по названию…">
          </div>

          <div class="matcher-candidates" id="matcher-candidates"></div>

          <div class="matcher-footer">
            <div>
              <button class="btn" id="matcher-manual-btn">✏️ Создать новый продукт</button>
            </div>
            <div class="matcher-footer-right">
              <button class="btn" id="matcher-skip-btn">Пропустить</button>
            </div>
          </div>
        </div>
      </div>`;
    const wrap = document.createElement("div");
    wrap.innerHTML = html;
    overlayEl = wrap.firstElementChild;
    document.body.appendChild(overlayEl);

    $("matcher-close").addEventListener("click", closeOverlay);
    $("matcher-skip-btn").addEventListener("click", skipCurrent);
    $("matcher-manual-btn").addEventListener("click", openManualCreator);
    overlayEl.addEventListener("click", (e) => {
      if (e.target === overlayEl) closeOverlay();
    });

    // Поиск по продуктам в справочнике
    let searchTimer = null;
    $("matcher-search-input").addEventListener("input", (e) => {
      clearTimeout(searchTimer);
      const q = e.target.value.trim();
      searchTimer = setTimeout(() => doLocalSearch(q), 250);
    });

    overlayEl.classList.add("show");
  }

  function closeOverlay() {
    if (overlayEl) overlayEl.classList.remove("show");
    currentContext = null;
  }

  async function doLocalSearch(q) {
    if (!q) {
      // Возвращаемся к результатам матчинга
      await runMatch(currentContext ? currentContext.name : "", currentContext ? currentContext.recipe : null);
      return;
    }
    try {
      const data = await getJSON(`api/ingredients?q=${encodeURIComponent(q)}`);
      const items = (data.products || []).map((p) => ({
        product_id: p.id,
        name: p.name,
        brand: p.brand,
        image_url: p.image_url,
        nutrition_per_100g: p.nutrition_per_100g,
        method: "manual",
        score: 0,
        matched_alias: null,
      }));
      renderCandidates(items);
    } catch (err) {
      console.warn("[matcher] local search failed:", err);
    }
  }

  function setTitle(name, isBatch) {
    const title = $("matcher-title");
    if (!title) return;
    if (isBatch && currentContext) {
      const total = currentContext.queue.length;
      title.textContent = `Связать ингредиент (осталось: ${total})`;
    } else {
      title.textContent = "Связать ингредиент";
    }
    const q = $("matcher-query");
    if (q) q.textContent = name;
  }

  // =====================================================================
  // Экспорт
  // =====================================================================

  RM.matcher = {
    setup,
    openForRecipe,
    openBatch,
  };
})(window.RM);