/* Вкладка «Генератор» — меню на неделю.
 *
 * Собирает план из базы, генерирует недостающие рецепты через LLM,
 * показывает черновик и даёт одобрить/отклонить новые блюда.
 */
"use strict";
(function (RM) {
  const {
    $, escHtml, setStatus, clearStatus, toISO, getMonday, addDays, weekTitle,
    WEEKDAYS_SHORT,
  } = RM.utils;
  const { getJSON, postJSON, del } = RM.api;
  const state = RM.state;

  let currentDraft = null;
  let pollSeq = 0;
  let activePollJob = null;
  let previewSlot = null;

  function setup() {
    const card = $("mpg-card");
    if (!card) return;

    const nextMonday = addDays(getMonday(new Date()), 7);
    if ($("mpg-week-start")) $("mpg-week-start").value = toISO(nextMonday);

    $("mpg-run").addEventListener("click", onRun);
    $("mpg-draft").addEventListener("click", onDraftClick);

    loadAccess().then((ok) => {
      if (!ok) return;
      loadProfiles();
      loadActiveDraft();
    });
  }

  async function loadAccess() {
    let me = null;
    try {
      me = await getJSON("api/me");
      state.user = me;
    } catch (_) {
      me = state.user || null;
    }
    const allowed = !!(me && me.can_generate_meal_plan);
    $("mpg-card").style.display = allowed ? "" : "none";
    return allowed;
  }

  async function loadProfiles() {
    const select = $("mpg-profile");
    if (!select) return;
    try {
      const data = await getJSON("api/profiles");
      const profiles = data.profiles || [];
      let html = '<option value="">— активный из шапки —</option>';
      for (const profile of profiles) {
        const prefix = profile.icon ? `${profile.icon} ` : "";
        html += `<option value="${escHtml(profile.id)}">${escHtml(prefix + profile.name)}</option>`;
      }
      select.innerHTML = html;
    } catch (_) { /* профили опциональны */ }
  }

  async function loadActiveDraft() {
    try {
      const data = await getJSON("api/meal-plan/drafts?active=1");
      if (data && data.draft) {
        setDraft(data.draft);
      }
    } catch (err) {
      console.warn("[meal-plan-gen] load draft:", err.message);
    }
  }

  function selectedMeals() {
    return Array.from(document.querySelectorAll('input[name="mpg-meal"]:checked'))
      .map((el) => el.value);
  }

  async function onRun() {
    const btn = $("mpg-run");
    const meals = selectedMeals();
    if (!meals.length) {
      setStatus($("mpg-status"), "Выберите хотя бы один приём пищи.", "error");
      return;
    }
    const weekStart = $("mpg-week-start").value;
    if (!weekStart) {
      setStatus($("mpg-status"), "Выберите дату начала недели.", "error");
      return;
    }

    if (currentDraft && ["generating", "ready"].includes(currentDraft.status)) {
      if (!confirm("Уже есть черновик плана. Создать новый? Старый останется в истории.")) {
        return;
      }
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Составляем…';
    clearStatus($("mpg-status"));
    setStatus($("mpg-status"), "Собираем план…", "info");

    try {
      const data = await postJSON("api/meal-plan/generate", {
        week_start: weekStart,
        profile_id: $("mpg-profile").value || null,
        meals,
        servings: parseFloat($("mpg-servings").value) || 2,
        max_new: parseInt($("mpg-max-new").value, 10) || 0,
        prompt: $("mpg-prompt").value.trim() || null,
      });
      setDraft(data.draft);
    } catch (err) {
      setStatus($("mpg-status"), "Ошибка: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "🗓 Составить план";
    }
  }

  async function pollJob(jobId, draftId) {
    if (activePollJob === jobId) return;
    activePollJob = jobId;
    const seq = ++pollSeq;
    const t0 = Date.now();
    try {
      while (seq === pollSeq) {
        await sleep(2000);
        if (seq !== pollSeq) return;
        let job = null;
        try {
          job = await getJSON(`api/generator/jobs/${encodeURIComponent(jobId)}`);
        } catch (err) {
          if (/404/i.test(err.message || "")) {
            setStatus($("mpg-status"), "Задача потеряна. Откройте вкладку заново.", "error");
            return;
          }
        }
        if (job && job.progress) updateProgress(job.progress);
        try {
          const data = await getJSON(`api/meal-plan/drafts/${encodeURIComponent(draftId)}`);
          if (data && data.draft) setDraft(data.draft, true);
        } catch (_) { /* черновик мог быть отменён */ }

        if (job && job.status === "done") {
          setStatus($("mpg-status"), "План готов. Проверьте новые рецепты.", "success");
          await refreshDraft(draftId);
          return;
        }
        if (job && job.status === "error") {
          setStatus($("mpg-status"), "Ошибка: " + (job.error || "генерация не удалась"), "error");
          await refreshDraft(draftId);
          return;
        }
        if (Date.now() - t0 > 30 * 60 * 1000) {
          setStatus($("mpg-status"), "Превышен лимит ожидания (30 минут).", "error");
          return;
        }
      }
    } finally {
      if (activePollJob === jobId) activePollJob = null;
    }
  }

  async function refreshDraft(draftId) {
    try {
      const data = await getJSON(`api/meal-plan/drafts/${encodeURIComponent(draftId)}`);
      if (data && data.draft) setDraft(data.draft);
    } catch (_) { /* ignore */ }
  }

  function updateProgress(progress) {
    const wrap = $("mpg-progress");
    const bar = $("mpg-progress-bar");
    if (!wrap || !bar) return;
    const total = Math.max(1, Number(progress.total) || 1);
    const done = Math.min(total, Number(progress.done) || 0);
    const pct = Math.max(4, Math.min(100, Math.round((done / total) * 100)));
    wrap.style.display = "";
    bar.style.width = pct + "%";
    if (progress.stage) {
      setStatus($("mpg-status"), progress.stage, "info");
    }
  }

  function setDraft(draft, silent) {
    currentDraft = draft || null;
    renderDraft(silent);
    if (
      currentDraft
      && currentDraft.status === "generating"
      && currentDraft.job_id
      && activePollJob !== currentDraft.job_id
    ) {
      pollJob(currentDraft.job_id, currentDraft.id);
    }
  }

  function parseISO(value) {
    return new Date(String(value) + "T00:00:00");
  }

  function slotKey(slot) {
    return `${slot.date}|${slot.meal_type}`;
  }

  function renderDraft(silent) {
    const container = $("mpg-draft");
    if (!container) return;
    if (!currentDraft) {
      container.innerHTML = "";
      return;
    }

    const draft = currentDraft;
    const start = parseISO(draft.week_start);
    const meals = draft.meals || [];
    const slots = draft.slots || [];
    const byKey = new Map(slots.map((s) => [slotKey(s), s]));
    const pending = Number(draft.pending_count) || 0;

    let head = `<div class="mpg-draft-head">
      <div>
        <div class="mpg-draft-title">${escHtml(weekTitle(start))}</div>
        <div class="mpg-draft-sub">${escHtml(draft.profile_name || "Без профиля")} · ${escHtml(String(draft.servings || 1))} порц. · ${escHtml(statusText(draft.status))}</div>
      </div>
      ${draft.generated_count ? `<div class="mpg-draft-count">Сгенерировано: ${draft.generated_count}</div>` : ""}
    </div>`;

    if (draft.status === "generating") {
      head += `<div class="hint" style="margin:8px 0;">Идёт генерация. Можно подождать или посмотреть уже готовые слоты.</div>`;
    }
    if (draft.error) {
      head += `<div class="mpg-warning">⚠ ${escHtml(draft.error)}</div>`;
    }
    for (const warning of draft.warnings || []) {
      head += `<div class="mpg-warning">⚠ ${escHtml(warning)}</div>`;
    }

    let grid = '<div class="mpg-grid-wrap"><div class="mpg-grid">';
    grid += '<div class="mpg-corner"></div>';
    for (let i = 0; i < 7; i++) {
      const day = addDays(start, i);
      const iso = toISO(day);
      grid += `<div class="mpg-day-head ${iso === toISO(new Date()) ? "today" : ""}">
        <span>${WEEKDAYS_SHORT[i]}</span><b>${day.getDate()}</b>
      </div>`;
    }
    for (const meal of meals) {
      grid += `<div class="mpg-meal-label">${escHtml(RM.MEAL_LABELS[meal] || meal)}</div>`;
      for (let i = 0; i < 7; i++) {
        const day = addDays(start, i);
        const iso = toISO(day);
        const slot = byKey.get(`${iso}|${meal}`) || {
          date: iso, meal_type: meal, source: "empty",
        };
        grid += renderCell(slot);
      }
    }
    grid += "</div></div>";

    let actions = "";
    if (draft.status === "ready" || draft.status === "error") {
      const saveDisabled = pending > 0 || !draft.can_save;
      const hint = pending > 0
        ? `Одобрите новые рецепты: ${pending}.`
        : (!draft.can_save ? "Нет блюд для сохранения." : "");
      actions = `<div class="mpg-actions">
        <label class="mpg-shopping-check">
          <input type="checkbox" id="mpg-add-shopping">
          Добавить ингредиенты в покупки
        </label>
        <button class="btn primary" id="mpg-save" ${saveDisabled ? "disabled" : ""}>💾 Сохранить план</button>
        <button class="btn" id="mpg-discard">Отменить</button>
        ${hint ? `<span class="mpg-action-hint">${escHtml(hint)}</span>` : ""}
      </div>`;
    } else if (draft.status === "saved") {
      actions = `<div class="mpg-actions">
        <span class="mpg-saved">✅ План сохранён: ${draft.saved_count || 0} слотов.</span>
        <button class="btn" id="mpg-discard">Закрыть черновик</button>
      </div>`;
    }

    container.innerHTML = head + grid + actions;
    if (!silent) {
      if (draft.status === "ready" && (draft.generated_count || 0) > 0) {
        updateProgress({
          stage: pending ? `Одобрите ${pending} рецепт(ов)` : "План готов",
          done: draft.generated_count || 0,
          total: Math.max(1, draft.generated_count || 1),
        });
      } else if (draft.status === "saved" || draft.status === "error" || draft.status === "ready") {
        $("mpg-progress").style.display = "none";
      }
    }
  }

  function renderCell(slot) {
    const mealLabel = RM.MEAL_LABELS[slot.meal_type] || slot.meal_type;
    if (slot.suggestion_id) {
      const suggestion = slot.suggestion || {};
      const recipe = suggestion.recipe_data || {};
      const hasError = !!suggestion.error;
      return `<div class="mpg-cell pending ${hasError ? "error" : ""}"
        data-mpg-suggestion="${escHtml(slot.suggestion_id)}"
        title="Открыть предпросмотр">
        <span class="mpg-badge">Требует одобрения</span>
        <span class="mpg-dish-name">${escHtml(recipe.name || "(не распознано)")}</span>
        ${hasError ? `<span class="mpg-cell-error">⚠</span>` : ""}
      </div>`;
    }
    if (slot.recipe_id || (slot.recipe && slot.recipe.id)) {
      const recipe = slot.recipe || {};
      const badge = slot.source === "existing"
        ? `<span class="mpg-badge muted">уже в плане</span>`
        : `<span class="mpg-badge base">из базы</span>`;
      return `<div class="mpg-cell filled" data-mpg-open-recipe="${escHtml(recipe.id || slot.recipe_id || "")}" title="Открыть рецепт">
        ${badge}
        <span class="mpg-dish-name">${escHtml(recipe.name || "(без названия)")}</span>
      </div>`;
    }
    return `<div class="mpg-cell empty">
      <button class="mpg-empty-btn" data-mpg-replace="${escHtml(slot.date)}|${escHtml(slot.meal_type)}"
        title="Сгенерировать замену для этого слота">＋</button>
      <span class="mpg-empty-label">${escHtml(mealLabel)}</span>
    </div>`;
  }

  function statusText(status) {
    return {
      generating: "генерация…",
      ready: "черновик",
      saved: "сохранён",
      discarded: "отменён",
      error: "ошибка",
    }[status] || status || "";
  }

  async function onDraftClick(event) {
    const suggestionEl = event.target.closest("[data-mpg-suggestion]");
    if (suggestionEl) {
      const sid = suggestionEl.dataset.mpgSuggestion;
      const slot = (currentDraft.slots || []).find((s) => s.suggestion_id === sid);
      if (slot) openPreview(slot);
      return;
    }

    const replaceEl = event.target.closest("[data-mpg-replace]");
    if (replaceEl) {
      const [date, meal] = replaceEl.dataset.mpgReplace.split("|");
      await replaceSlot(date, meal);
      return;
    }

    const openEl = event.target.closest("[data-mpg-open-recipe]");
    if (openEl) {
      await openRecipe(openEl.dataset.mpgOpenRecipe);
      return;
    }

    if (event.target.closest("#mpg-save")) {
      await saveDraft();
      return;
    }
    if (event.target.closest("#mpg-discard")) {
      await discardDraft();
    }
  }

  function openPreview(slot) {
    if (!RM.generator || !RM.generator.previewSuggestion) {
      alert("Модуль предпросмотра не загружен. Обновите страницу.");
      return;
    }
    previewSlot = slot;
    const suggestion = slot.suggestion || {};
    RM.generator.previewSuggestion(suggestion);

    const actions = $("gen-preview-plan-actions");
    if (!actions) return;
    const disabled = suggestion.error ? "disabled" : "";
    actions.innerHTML = `
      <button class="btn primary" data-mpg-preview-act="approve" ${disabled}>✅ Одобрить и добавить в план</button>
      <button class="btn danger" data-mpg-preview-act="reject">🗑 Отклонить</button>
      ${suggestion.error ? `<span class="mpg-action-hint">Рецепт не распознан — одобрение недоступно.</span>` : ""}
    `;
    actions.style.display = "flex";
    actions.onclick = async (event) => {
      const action = event.target.closest("[data-mpg-preview-act]")?.dataset.mpgPreviewAct;
      if (!action) return;
      if (action === "approve") await approveSuggestion();
      else if (action === "reject") await rejectSuggestion();
    };
  }

  async function approveSuggestion() {
    if (!currentDraft || !previewSlot || !previewSlot.suggestion_id) return;
    const sid = previewSlot.suggestion_id;
    try {
      const data = await postJSON(
        `api/meal-plan/drafts/${encodeURIComponent(currentDraft.id)}/approve`,
        { suggestion_id: sid },
      );
      if (RM.generator.closePreview) RM.generator.closePreview();
      previewSlot = null;
      setDraft(data.draft);
      if (RM.recipes && RM.recipes.load) RM.recipes.load();
    } catch (err) {
      alert("Ошибка одобрения: " + err.message);
    }
  }

  async function rejectSuggestion() {
    if (!currentDraft || !previewSlot || !previewSlot.suggestion_id) return;
    const sid = previewSlot.suggestion_id;
    try {
      const data = await postJSON(
        `api/meal-plan/drafts/${encodeURIComponent(currentDraft.id)}/reject`,
        { suggestion_id: sid },
      );
      if (RM.generator.closePreview) RM.generator.closePreview();
      previewSlot = null;
      setDraft(data.draft);
    } catch (err) {
      alert("Ошибка отклонения: " + err.message);
    }
  }

  async function replaceSlot(date, meal) {
    if (!currentDraft) return;
    if (currentDraft.status === "generating") {
      alert("Дождитесь окончания текущей генерации.");
      return;
    }
    try {
      setStatus($("mpg-status"), "Генерируем замену…", "info");
      const data = await postJSON(
        `api/meal-plan/drafts/${encodeURIComponent(currentDraft.id)}/replace`,
        { date, meal_type: meal },
      );
      setDraft(data.draft);
    } catch (err) {
      setStatus($("mpg-status"), "Ошибка: " + err.message, "error");
    }
  }

  async function saveDraft() {
    if (!currentDraft) return;
    if ((Number(currentDraft.pending_count) || 0) > 0) {
      alert("Сначала одобрите или отклоните все новые рецепты.");
      return;
    }
    const addShopping = !!$("mpg-add-shopping")?.checked;
    const btn = $("mpg-save");
    if (btn) btn.disabled = true;
    try {
      const data = await postJSON(
        `api/meal-plan/drafts/${encodeURIComponent(currentDraft.id)}/save`,
        { add_to_shopping: addShopping },
      );
      setDraft(data.draft);
      const parts = [`Сохранено слотов: ${data.saved}`];
      if (data.skipped_existing) parts.push(`пропущено занятых: ${data.skipped_existing}`);
      if (addShopping) {
        parts.push(`в покупки: ${data.shopping?.total || 0} (объединено: ${data.shopping?.merged || 0})`);
      }
      alert(parts.join("\n"));
      if (RM.planner && RM.planner.load) RM.planner.load();
      if (RM.recipes && RM.recipes.load) RM.recipes.load();
      if (addShopping && RM.shopping && RM.shopping.load) RM.shopping.load();
    } catch (err) {
      alert("Ошибка сохранения: " + err.message);
      if (btn) btn.disabled = false;
    }
  }

  async function discardDraft() {
    if (!currentDraft) return;
    if (currentDraft.status === "generating") {
      alert("Дождитесь окончания генерации.");
      return;
    }
    const message = currentDraft.status === "saved"
      ? "Закрыть черновик? План уже сохранён."
      : "Отменить план? Неодобренные рецепты будут удалены.";
    if (!confirm(message)) return;
    try {
      await del(`api/meal-plan/drafts/${encodeURIComponent(currentDraft.id)}`);
      currentDraft = null;
      pollSeq++;
      activePollJob = null;
      $("mpg-draft").innerHTML = "";
      $("mpg-progress").style.display = "none";
      setStatus($("mpg-status"), "", "info");
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  async function openRecipe(recipeId) {
    if (!recipeId) return;
    try {
      const data = await getJSON(`api/recipes/${encodeURIComponent(recipeId)}`);
      if (data && data.recipe && RM.detail) RM.detail.open(data.recipe);
    } catch (err) {
      alert("Не удалось открыть рецепт: " + err.message);
    }
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function refresh() {
    const allowed = await loadAccess();
    if (!allowed) return;
    await loadProfiles();
    await loadActiveDraft();
  }

  RM.mealPlanGen = { setup, loadActiveDraft, refresh };
})(window.RM);
