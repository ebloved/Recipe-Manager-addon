"use strict";
(function (RM) {
  const { $, escHtml } = RM.utils;
  const { getJSON, postJSON, patchJSON, del } = RM.api;

  let current = null;
  let garnishMain = null;
  let toastTimer = null;
  let voiceStepIndex = -1;
  let voiceRecipeId = null;
  let voiceOutputEnabled = false;
  let voiceAudioEl = null;
  let stepAudioByRecipe = {};
  function kindOf(r) {
    return RM.recipes && RM.recipes.kindOf ? RM.recipes.kindOf(r) : "main";
  }

  function toast(message) {
    let el = $("cooking-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "cooking-toast";
      el.className = "cooking-toast";
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
  }

  function updateBadge() {
    const active = !!(current && current.active);
    const badge = $("cooking-badge");
    if (badge) {
      badge.style.display = active ? "inline-flex" : "none";
      badge.textContent = active ? "•" : "";
    }
    const tab = $("recipe-kind-cooking");
    if (tab) tab.classList.toggle("has-session", active);
  }

  async function refreshBadge() {
    try {
      current = await getJSON("api/cooking/current");
    } catch (e) {
      current = null;
    }
    updateBadge();
  }

  async function load() {
    const root = $("cooking-root");
    if (!root) return;
    root.innerHTML = '<div class="loading"><span class="spinner"></span> Загрузка…</div>';
    try {
      current = await getJSON("api/cooking/current");
    } catch (e) {
      root.innerHTML = `<div class="hint" style="color:var(--danger)">Ошибка: ${escHtml(e.message)}</div>`;
      return;
    }
    updateBadge();
    if (!current || !current.active) {
      root.innerHTML = `
        <div class="card">
          <div class="hint" style="font-size:14px;font-weight:600;">Сейчас ничего не готовится</div>
          <div class="hint" style="margin-top:6px;">Открой рецепт и нажми «🍳 На кухню».</div>
          <button class="btn primary" id="cooking-empty-recipes" style="margin-top:12px;">← К рецептам</button>
        </div>`;
      const btn = $("cooking-empty-recipes");
      if (btn) btn.onclick = () => RM.tabs.activateTab("recipes");
      return;
    }
    render();
  }

  function render() {
    const main = current.main_recipe;
    const side = current.side_recipe;
    const heading = $("cooking-heading");
    if (heading) {
      heading.textContent = [main && main.name, side && side.name].filter(Boolean).join("  +  ") || "Готовлю сейчас";
    }

    const ingredients = current.ingredients || [];
    const checkedCount = ingredients.filter((i) => i.checked).length;
    const ingredientsHtml = ingredients.length
      ? ingredients.map((item) => {
          const amount = [item.amount, item.unit].filter((x) => x !== null && x !== undefined && x !== "").join(" ");
          const sources = (item.sources || []).map((s) => `<span class="cooking-source">${s === "main" ? "основное" : "гарнир"}</span>`).join("");
          return `<label class="cooking-ing ${item.checked ? "checked" : ""}">
            <input type="checkbox" data-ing-key="${escHtml(item.key)}" ${item.checked ? "checked" : ""}>
            <span class="cooking-ing-name">${escHtml(item.name)}</span>
            ${amount ? `<span class="cooking-ing-amount">${escHtml(amount)}</span>` : ""}
            ${item.optional ? '<span class="cooking-optional">по желанию</span>' : ""}
            ${sources}
          </label>`;
        }).join("")
      : '<div class="hint">Ингредиенты не указаны.</div>';

    const mainRecipeId = main && main.id;
    const sideRecipeId = side && side.id;
    const stepsHtml = renderSteps(current.main_steps || [], "Основное блюдо", mainRecipeId);
    const sideHtml = current.side_steps && current.side_steps.length
      ? `<div class="cooking-divider">Основное готовится — переходим к гарниру</div>${renderSteps(current.side_steps, side ? side.name : "Гарнир", sideRecipeId)}`
      : "";

    $("cooking-root").innerHTML = `
      <div class="cooking-zone">
        <div class="cooking-zone-head">
          <span>🥕 Ингредиенты</span>
          <span class="cooking-counter">${checkedCount}/${ingredients.length}</span>
        </div>
        <div class="cooking-ingredients">${ingredientsHtml}</div>
      </div>
      <div class="cooking-zone">
        <div class="cooking-zone-head"><span>📋 Шаги</span></div>
        ${stepsHtml}
        ${sideHtml}
      </div>
      <div class="cooking-voice-bar" id="cooking-voice-bar" style="display:none">
        <div class="cooking-voice-controls">
          <button class="btn" id="cooking-voice-prev">Назад</button>
          <button class="btn primary" id="cooking-voice-next">Вперёд</button>
        </div>
        <div class="cooking-voice-meta">
          <label class="cooking-voice-toggle">
            <input type="checkbox" id="cooking-voice-output"> Включить озвучку
          </label>
          <span class="cooking-voice-step" id="cooking-voice-status"></span>
        </div>
      </div>
    `;

    $("cooking-root").querySelectorAll("input[data-ing-key]").forEach((cb) => {
      cb.addEventListener("change", onCheck);
    });
    $("cooking-root").querySelectorAll("[data-timer-seconds]").forEach((btn) => {
      btn.addEventListener("click", () => startTimer(btn));
    });
    setupVoice();
    applyAssistantVisibility();
  }

  function voiceStatus(text) {
    const el = $("cooking-voice-status");
    if (el) el.textContent = text;
  }

  function voiceSteps() {
    return Array.from(document.querySelectorAll("#cooking-root .cooking-step"));
  }

  function voiceStepText(el) {
    const body = el && el.querySelector(".cooking-step-body");
    if (!body) return "";
    const clone = body.cloneNode(true);
    clone.querySelectorAll(".cooking-timers").forEach((node) => node.remove());
    const text = clone.innerText || clone.textContent || "";
    return String(text).replace(/\n+/g, " ").trim();
  }

  function updateVoiceStepLabel() {
    const el = $("cooking-voice-status");
    if (!el) return;
    const steps = voiceSteps();
    if (!steps.length) {
      el.textContent = "В рецепте нет шагов";
      return;
    }
    const idx = voiceStepIndex < 0 ? 0 : Math.min(voiceStepIndex, steps.length - 1);
    const text = voiceStepText(steps[idx]);
    el.textContent = `Шаг ${idx + 1}/${steps.length}: ${text.slice(0, 100)}`;
  }

  async function loadStepAudio() {
    stepAudioByRecipe = {};
    const ids = [
      current && current.main_recipe && current.main_recipe.id,
      current && current.side_recipe && current.side_recipe.id,
    ].filter(Boolean);
    await Promise.all(ids.map(async (recipeId) => {
      try {
        const data = await getJSON(
          `api/recipes/${encodeURIComponent(recipeId)}/step-audio`
        );
        stepAudioByRecipe[recipeId] = data.items || [];
      } catch (_) {
        stepAudioByRecipe[recipeId] = [];
      }
    }));
  }

  async function playStepAudio(recipeId, index) {
    if (!voiceOutputEnabled || !recipeId) return;
    let items = stepAudioByRecipe[recipeId];
    if (!Array.isArray(items)) {
      items = [];
      stepAudioByRecipe[recipeId] = items;
    }
    let item = items.find((x) => Number(x.step_index) === Number(index));
    if (!item) {
      try {
        const data = await postJSON(
          `api/recipes/${encodeURIComponent(recipeId)}/step-audio/${index}`,
          {}
        );
        item = data.item;
        items.push(item);
      } catch (e) {
        voiceStatus("Аудио шага: " + e.message);
        return;
      }
    }
    if (!item) return;
    if (!voiceAudioEl) {
      voiceAudioEl = new Audio();
      voiceAudioEl.playsInline = true;
      voiceAudioEl.setAttribute("playsinline", "");
      if (navigator.audioSession) {
        try { navigator.audioSession.type = "playback"; } catch (_) {}
      }
    }
    try {
      voiceAudioEl.pause();
      voiceAudioEl.src = RM.utils.mediaUrl(item.url);
      await voiceAudioEl.play();
    } catch (e) {
      voiceStatus("Аудио: " + e.message);
    }
  }

  function assistantEnabled() {
    const cb = $("cooking-assistant-visible");
    return !!(cb && cb.checked);
  }

  function voiceSelect(index, options = {}) {
    const steps = voiceSteps();
    if (!steps.length) {
      voiceStatus("В рецепте нет шагов.");
      return;
    }
    voiceStepIndex = Math.max(0, Math.min(steps.length - 1, index));
    steps.forEach((el, i) => el.classList.toggle("voice-current", i === voiceStepIndex));
    if (options.scroll !== false) {
      steps[voiceStepIndex].scrollIntoView({ behavior: "smooth", block: "center" });
    }
    updateVoiceStepLabel();

    const stepEl = steps[voiceStepIndex];
    const recipeId = stepEl.dataset.recipeId
      || (current && current.main_recipe && current.main_recipe.id);
    const localIndex = parseInt(stepEl.dataset.stepIndex, 10);
    playStepAudio(recipeId, Number.isFinite(localIndex) ? localIndex : voiceStepIndex);
  }

  function voiceGo(delta) {
    voiceSelect(voiceStepIndex + delta);
  }

  function setupStepTap() {
    voiceSteps().forEach((el, index) => {
      el.onclick = (event) => {
        if (!assistantEnabled()) return;
        if (event.target.closest("button, a, input, label")) return;
        voiceSelect(index);
      };
    });
  }

  function setupVoice() {
    const outputToggle = $("cooking-voice-output");
    if (outputToggle) {
      voiceOutputEnabled = localStorage.getItem("rm_voice_output") === "1";
      outputToggle.checked = voiceOutputEnabled;
      outputToggle.onchange = () => {
        voiceOutputEnabled = outputToggle.checked;
        localStorage.setItem("rm_voice_output", voiceOutputEnabled ? "1" : "0");
        if (!voiceOutputEnabled && voiceAudioEl) {
          voiceAudioEl.pause();
        } else if (voiceOutputEnabled && voiceStepIndex >= 0) {
          playStepAudio(voiceStepIndex);
        }
      };
    }

    const next = $("cooking-voice-next");
    if (next) next.onclick = () => voiceGo(1);
    const prev = $("cooking-voice-prev");
    if (prev) prev.onclick = () => voiceGo(-1);

    const rid = [
      current && current.main_recipe && current.main_recipe.id,
      current && current.side_recipe && current.side_recipe.id,
    ].filter(Boolean).join("|");
    if (rid !== voiceRecipeId) {
      voiceRecipeId = rid;
      voiceStepIndex = -1;
      loadStepAudio();
    }
    setupStepTap();
    updateVoiceStepLabel();
  }

  function applyAssistantVisibility() {
    const bar = $("cooking-voice-bar");
    const enabled = assistantEnabled();
    if (bar) bar.style.display = enabled ? "flex" : "none";
    const steps = voiceSteps();
    steps.forEach((el) => el.classList.toggle("assistant-clickable", enabled));
    if (!enabled) {
      steps.forEach((el) => el.classList.remove("voice-current"));
      voiceStepIndex = -1;
      if (voiceAudioEl) voiceAudioEl.pause();
    }
  }

  function renderSteps(steps, title, recipeId) {
    if (!steps.length) {
      return `<div class="cooking-steps-block"><div class="cooking-steps-title">${escHtml(title)}</div><div class="hint">Шагов нет.</div></div>`;
    }
    const items = steps.map((step, idx) => {
      const text = String(step || "");
      const timers = [];
      const re = /(\d+(?:[.,]\d+)?)\s*(минут(?:ы)?|мин|час(?:а|ов)?)/gi;
      let m;
      while ((m = re.exec(text)) !== null) {
        const value = parseFloat(m[1].replace(",", "."));
        const unit = m[2].toLowerCase();
        const seconds = Math.round((unit.startsWith("час") ? value * 60 : value) * 60);
        if (seconds >= 10 && seconds <= 6 * 3600) {
          const label = `${m[1]} ${m[2]}`;
          timers.push(`<button class="cooking-timer-btn" data-timer-seconds="${seconds}" data-timer-label="${escHtml(label)}">⏱ ${escHtml(label)}</button>`);
        }
      }
      return `<div class="cooking-step" data-recipe-id="${escHtml(recipeId || "")}" data-step-index="${idx}">
        <div class="cooking-step-num">${idx + 1}</div>
        <div class="cooking-step-body">${RM.utils.renderMarkdown(text)}<div class="cooking-timers">${timers.join("")}</div></div>
      </div>`;
    }).join("");
    return `<div class="cooking-steps-block"><div class="cooking-steps-title">${escHtml(title)}</div>${items}</div>`;
  }

  function startTimer(btn) {
    if (btn.dataset.timerRunning === "1") return;
    let remaining = parseInt(btn.dataset.timerSeconds, 10) || 0;
    if (remaining <= 0) return;
    btn.dataset.timerRunning = "1";
    btn.disabled = true;
    const label = btn.dataset.timerLabel || "Таймер";
    let timer = null;
    const tick = () => {
      const mm = String(Math.floor(remaining / 60)).padStart(2, "0");
      const ss = String(remaining % 60).padStart(2, "0");
      btn.textContent = `⏱ ${mm}:${ss}`;
      if (remaining <= 0) {
        clearInterval(timer);
        btn.textContent = "⏰ Готово";
        btn.classList.add("done");
        toast(`Таймер «${label}» завершён`);
        return;
      }
      remaining -= 1;
    };
    tick();
    timer = setInterval(tick, 1000);
  }

  async function onCheck() {
    const checked = Array.from(document.querySelectorAll("input[data-ing-key]:checked"))
      .map((cb) => cb.dataset.ingKey);
    try {
      current = await patchJSON("api/cooking/current/check", { checked_ingredients: checked });
      updateBadge();
      // Перерисовываем счётчик и классы без полного reload.
      const total = (current.ingredients || []).length;
      const counter = document.querySelector(".cooking-counter");
      if (counter) counter.textContent = `${checked.length}/${total}`;
      document.querySelectorAll(".cooking-ing").forEach((label) => {
        const cb = label.querySelector("input[data-ing-key]");
        if (cb) label.classList.toggle("checked", cb.checked);
      });
    } catch (e) {
      toast("Ошибка сохранения: " + e.message);
    }
  }

  async function sendToPlan() {
    try {
      const data = await postJSON("api/cooking/current/send-to-plan", {});
      toast(`Добавлено в план: ${data.meal_type || "сегодня"}`);
      if (RM.planner && $("panel-planner").classList.contains("active")) RM.planner.load();
    } catch (e) {
      toast("Ошибка: " + e.message);
    }
  }

  async function sendToShopping() {
    try {
      const data = await postJSON("api/cooking/current/send-to-shopping", {});
      toast(`В покупки: добавлено ${data.added || 0}, объединено ${data.merged || 0}`);
    } catch (e) {
      toast("Ошибка: " + e.message);
    }
  }

  async function finish() {
    try {
      await del("api/cooking/current");
      current = null;
      if (voiceAudioEl) {
        voiceAudioEl.pause();
        voiceAudioEl = null;
      }
      updateBadge();
      toast("Готовка завершена");
      RM.tabs.activateTab("recipes");
    } catch (e) {
      toast("Ошибка: " + e.message);
    }
  }

  async function start(recipe) {
    if (!recipe || !recipe.id) return;
    const kind = kindOf(recipe);
    let payload;
    try {
      if (kind === "side") {
        const existing = await getJSON("api/cooking/current").catch(() => null);
        if (existing && existing.active && existing.main_recipe) {
          payload = { main_recipe_id: existing.main_recipe.id, side_recipe_id: recipe.id };
        } else {
          payload = { side_recipe_id: recipe.id };
        }
      } else {
        payload = { main_recipe_id: recipe.id };
      }
      current = await postJSON("api/cooking/current", payload);
      updateBadge();
      RM.tabs.activateTab("cooking");
      if (kind === "main" && !current.side_recipe) {
        openGarnishPicker(recipe);
      }
    } catch (e) {
      toast("Ошибка: " + e.message);
    }
  }

  function openGarnishPicker(mainRecipe) {
    garnishMain = mainRecipe;
    const title = $("garnish-picker-title");
    if (title) title.textContent = `Добавить гарнир к «${mainRecipe.name}»?`;
    const sub = $("garnish-picker-subtitle");
    if (sub) sub.textContent = "Можно пропустить — останется только основное блюдо.";
    const search = $("garnish-picker-search");
    if (search) search.value = "";
    $("garnish-picker").classList.add("show");
    loadGarnishRecipes();
  }

  function closeGarnishPicker() {
    $("garnish-picker").classList.remove("show");
    garnishMain = null;
  }

  async function loadGarnishRecipes() {
    const list = $("garnish-picker-list");
    if (!list) return;
    list.innerHTML = '<div class="loading"><span class="spinner"></span> Загрузка…</div>';
    if (!RM.state.recipes || !RM.state.recipes.length) {
      try {
        const data = await getJSON("api/recipes");
        RM.state.recipes = data.recipes || [];
      } catch (e) {
        list.innerHTML = `<div class="picker-empty">Ошибка: ${escHtml(e.message)}</div>`;
        return;
      }
    }
    renderGarnishList();
  }

  function renderGarnishList() {
    const list = $("garnish-picker-list");
    if (!list) return;
    const q = ($("garnish-picker-search").value || "").trim().toLowerCase();
    let recipes = (RM.state.recipes || []).filter((r) => kindOf(r) === "side");
    if (!recipes.length) recipes = (RM.state.recipes || []).filter((r) => kindOf(r) !== "other");
    if (q) {
      recipes = recipes.filter((r) => (r.name || "").toLowerCase().includes(q));
    }
    if (!recipes.length) {
      list.innerHTML = '<div class="picker-empty">Гарниры не найдены</div>';
      return;
    }
    list.innerHTML = recipes.map((r) => `
      <div class="picker-item" data-garnish-id="${escHtml(r.id)}">
        <div class="picker-thumb picker-placeholder">🥗</div>
        <div class="picker-info">
          <span class="picker-name">${escHtml(r.name || "(без названия)")}</span>
          <span class="picker-meta">${r.servings ? "👥 " + r.servings : ""}</span>
        </div>
      </div>
    `).join("");
    list.querySelectorAll("[data-garnish-id]").forEach((el) => {
      el.addEventListener("click", () => pickGarnish(el.dataset.garnishId));
    });
  }

  async function pickGarnish(recipeId) {
    if (!garnishMain) return;
    try {
      current = await postJSON("api/cooking/current", {
        main_recipe_id: garnishMain.id,
        side_recipe_id: recipeId,
      });
      closeGarnishPicker();
      updateBadge();
      load();
    } catch (e) {
      toast("Ошибка: " + e.message);
    }
  }

  function setup() {
    const back = $("cooking-back");
    if (back) back.onclick = () => RM.tabs.activateTab("recipes");
    const plan = $("cooking-send-plan");
    if (plan) plan.onclick = sendToPlan;
    const shop = $("cooking-send-shopping");
    if (shop) shop.onclick = sendToShopping;
    const finishBtn = $("cooking-finish");
    if (finishBtn) finishBtn.onclick = finish;

    const assistant = $("cooking-assistant-visible");
    if (assistant) {
      assistant.checked = localStorage.getItem("rm_assistant_visible") === "1";
      assistant.onchange = () => {
        localStorage.setItem("rm_assistant_visible", assistant.checked ? "1" : "0");
        applyAssistantVisibility();
      };
    }

    const close = $("garnish-picker-close");
    if (close) close.onclick = closeGarnishPicker;
    const skip = $("garnish-picker-skip");
    if (skip) skip.onclick = closeGarnishPicker;
    const overlay = $("garnish-picker");
    if (overlay) overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeGarnishPicker();
    });
    const search = $("garnish-picker-search");
    if (search) search.addEventListener("input", renderGarnishList);

    refreshBadge();
  }

  RM.cooking = { setup, load, start, refreshBadge };
})(window.RM);
