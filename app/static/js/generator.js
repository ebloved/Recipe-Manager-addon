/* Вкладка «Генератор» — генерация рецептов через LLM.
 *
 * Требуемые id в index.html:
 *   panel-generator
 *   gen-profile-select, gen-topic, gen-count, gen-samples
 *   gen-run-btn, gen-status
 *   gen-suggestions
 *
 * Использует:
 *   RM.api.getJSON / postJSON / del
 *   RM.utils.$
 */
"use strict";
(function (RM) {
  const { $, escHtml, setStatus, clearStatus } = RM.utils;
  const { getJSON, postJSON, del } = RM.api;
  const state = RM.state;

  state.generatorSuggestions = [];

  function setup() {
    $("gen-run-btn").addEventListener("click", onRun);
    const closeBtn = $("gen-preview-close");
    if (closeBtn) closeBtn.addEventListener("click", closePreview);
    const overlay = $("gen-preview-overlay");
    if (overlay) overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closePreview();
    });
    document.querySelectorAll(".gen-preview-tab").forEach((tab) => {
      tab.addEventListener("click", () => setPreviewTab(tab.dataset.view));
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && $("gen-preview-overlay").classList.contains("show")) {
        closePreview();
      }
    });
    loadSuggestions();
  }

  async function loadSuggestions() {
    const container = $("gen-suggestions");
    container.innerHTML = '<div class="loading"><span class="spinner"></span> Загрузка…</div>';
    try {
      const data = await getJSON("api/generator/suggestions?status=all");
      state.generatorSuggestions = data.suggestions || [];
      renderSuggestions();
      try {
        const pending = await getJSON("api/generator/jobs?status=pending");
        if (pending.jobs && pending.jobs.length) {
          pollJob(pending.jobs[0].id);
        }
      } catch (_) { /* нет jobs endpoint — ок */ }
    } catch (err) {
      container.innerHTML = `<div class="empty"><p>Ошибка: ${escHtml(err.message)}</p></div>`;
    }
  }

  async function onRun() {
    const status = $("gen-status");
    const btn = $("gen-run-btn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Генерация…';
    clearStatus(status);
    setStatus(status, "Генерирую рецепт через LLM…", "info");

    const profileId = $("gen-profile-select").value || null;
    const topic = $("gen-topic").value.trim() || null;
    const count = parseInt($("gen-count").value, 10) || 1;
    const samples = parseInt($("gen-samples").value, 10) || 0;

    try {
      const data = await postJSON("api/generator/run", {
        profile_id: profileId,
        topic,
        count,
        samples_count: samples,
      });
      if (!data || !data.job_id) {
        setStatus(status, "Ошибка: неожиданный ответ сервера (нет job_id). Обновите страницу (Ctrl+Shift+R).", "error");
        return;
      }
      await pollJob(data.job_id);
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "✨ Сгенерировать";
    }
  }

  function _sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

  async function pollJob(jobId) {
    const status = $("gen-status");
    const t0 = Date.now();
    while (true) {
      await _sleep(2000);
      const elapsed = Math.round((Date.now() - t0) / 1000);
      setStatus(status, `Генерирую… ${elapsed}s`, "info");
      let j;
      try {
        j = await getJSON(`api/generator/jobs/${jobId}`);
      } catch (err) {
        if (/404|not found/i.test(err.message || "")) {
          setStatus(status, "Ошибка: задача потеряна (перезапуск аддона?)", "error");
          return;
        }
        continue;
      }
      if (j.status === "done") {
        setStatus(status, `✓ Создано ${j.created} предложений.`, "success");
        await loadSuggestions();
        return;
      }
      if (j.status === "error") {
        // Ошибка приходит как строка из job.error
        const errMsg = j.error || "неизвестно";
        setStatus(status, "Ошибка: " + errMsg, "error");
        return;
      }
      // pending / in_progress — просто продолжаем поллинг
      if (elapsed > 900) {
        setStatus(status, "Ошибка: превышен лимит 15 минут", "error");
        return;
      }
    }
  }

  function renderSuggestions() {
    const container = $("gen-suggestions");
    const items = state.generatorSuggestions;

    if (!items.length) {
      container.innerHTML = '<div class="empty"><div class="icon">✨</div><p>Пока нет предложений. Нажмите «Сгенерировать».</p></div>';
      return;
    }

    const pending = items.filter((s) => s.status === "pending");
    const others = items.filter((s) => s.status !== "pending");

    let html = "";
    if (pending.length) {
      html += `<div class="gen-section-title">Ожидают решения (${pending.length})</div>`;
      html += pending.map(renderCard).join("");
    }
    if (others.length) {
      html += `<div class="gen-section-title">Обработанные (${others.length})</div>`;
      html += others.slice(0, 20).map(renderCard).join("");
    }
    container.innerHTML = html;

    container.querySelectorAll("[data-gen-id]").forEach((el) => {
      el.addEventListener("click", (e) => {
        const id = el.dataset.genId;
        const action = e.target.closest("[data-gen-action]")?.dataset.genAction;
        if (!action) return;
        e.stopPropagation();
        if (action === "accept") accept(id);
        else if (action === "reject") reject(id);
        else if (action === "preview") preview(id);
      });
    });
  }

  function renderCard(s) {
    const r = s.recipe_data || {};
    const name = r.name || "(не распознано)";
    const statusBadge = {
      pending: `<span class="gen-badge pending">ожидает</span>`,
      accepted: `<span class="gen-badge accepted">принят</span>`,
      rejected: `<span class="gen-badge rejected">отклонён</span>`,
    }[s.status] || "";

    const profile = s.profile_name ? `<span class="gen-meta-item">🎯 ${escHtml(s.profile_name)}</span>` : "";
    const topic = s.topic ? `<span class="gen-meta-item">💡 ${escHtml(s.topic)}</span>` : "";
    const provider = s.provider ? `<span class="gen-meta-item">🤖 ${escHtml(s.provider)}</span>` : "";

    const errHtml = s.error ? `<div class="gen-error">⚠ ${escHtml(s.error)}</div>` : "";

    const actions = s.status === "pending"
      ? `<div class="gen-actions">
           <button class="btn primary" data-gen-action="accept">✅ Принять</button>
           <button class="btn" data-gen-action="preview">👁 Просмотр</button>
           <button class="btn danger" data-gen-action="reject">🗑 Отклонить</button>
         </div>`
      : `<div class="gen-actions">
           <button class="btn" data-gen-action="preview">👁 Просмотр</button>
           ${s.status === "rejected" ? `<button class="btn danger" data-gen-action="reject">Удалить</button>` : ""}
         </div>`;

    // Используем существующий .card для фона/бордера — не зависим от неизвестных CSS vars
    return `<div class="card gen-card" data-gen-id="${escHtml(s.id)}">
      <div class="gen-card-header">
        <h3 class="gen-card-name">${escHtml(name)}</h3>
        ${statusBadge}
      </div>
      <div class="gen-meta">${profile} ${topic} ${provider}</div>
      ${errHtml}
      ${actions}
    </div>`;
  }

  async function accept(id) {
    try {
      const data = await postJSON(`api/generator/suggestions/${id}/accept`, {});
      await loadSuggestions();
      if (RM.recipes && RM.recipes.load) RM.recipes.load();
      alert(`Рецепт «${data.recipe.name || "—"}» добавлен в библиотеку.`);
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  async function reject(id) {
    if (!confirm("Отклонить и удалить предложение?")) return;
    try {
      await del(`api/generator/suggestions/${id}`);
      await loadSuggestions();
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  function preview(id) {
    const s = state.generatorSuggestions.find((x) => x.id === id);
    if (!s) {
      console.error("[preview] suggestion not found:", id);
      alert("Предложение не найдено. Обновите страницу.");
      return;
    }
    const r = s.recipe_data || {};
    $("gen-preview-title").textContent = r.name || "(не распознано)";
    $("gen-preview-raw").textContent = s.markdown || "(нет markdown)";

    const rendered = $("gen-preview-rendered");
    if (s.error) {
      rendered.innerHTML = `<div class="gen-error">⚠ ${escHtml(s.error)}</div>` +
        `<p style="margin-top:12px;color:var(--text-muted)">Сырой Markdown доступен во вкладке RAW.</p>`;
    } else if (r && Object.keys(r).length) {
      rendered.innerHTML = renderPreviewRecipe(r);
    } else {
      rendered.innerHTML = `<p style="color:var(--text-muted)">Не удалось распарсить рецепт. Смотрите RAW.</p>`;
    }

    setPreviewTab("rendered");
    $("gen-preview-overlay").classList.add("show");
    $("gen-preview-close").focus();
  }

  function setPreviewTab(view) {
    document.querySelectorAll(".gen-preview-tab").forEach((t) => {
      t.classList.toggle("active", t.dataset.view === view);
    });
    $("gen-preview-rendered").style.display = view === "rendered" ? "" : "none";
    $("gen-preview-raw").style.display = view === "raw" ? "" : "none";
  }

  function closePreview() {
    $("gen-preview-overlay").classList.remove("show");
  }

  function renderPreviewRecipe(r) {
    const parts = [];
    if (r.description) {
      parts.push(`<p class="gen-preview-desc">${escHtml(r.description)}</p>`);
    }
    const meta = [];
    const t = r.total_time || r.time || ((r.prep_time || 0) + (r.cook_time || 0)) || null;
    if (t) meta.push(`⏱ ${escHtml(String(t))} мин`);
    if (r.servings) meta.push(`👥 ${escHtml(String(r.servings))}`);
    if (r.active_time != null) {
      meta.push(`🎯 ${escHtml(String(r.active_time))} мин акт.`
        + (r.active_time_estimated ? " <small>(оценка)</small>" : ""));
    }
    if (Array.isArray(r.tags) && r.tags.length) {
      meta.push(r.tags.slice(0, 5).map((x) => escHtml(String(x))).join(", "));
    }
    if (meta.length) {
      parts.push(`<div class="gen-preview-meta">${meta.join(" · ")}</div>`);
    }
    if (r.nutrition && typeof r.nutrition === "object") {
      const n = r.nutrition;
      const nn = [];
      if (n.calories) nn.push(`${n.calories} ккал`);
      if (n.protein) nn.push(`Б: ${n.protein}г`);
      if (n.fat) nn.push(`Ж: ${n.fat}г`);
      if (n.carbohydrates) nn.push(`У: ${n.carbohydrates}г`);
      if (nn.length) {
        parts.push(`<div class="gen-preview-nutrition">${nn.map(escHtml).join(" · ")}</div>`);
      }
    }
    const ing = r.ingredients || [];
    if (ing.length) {
      parts.push("<h4>Ингредиенты</h4><ul>");
      for (const i of ing) {
        if (typeof i === "string") {
          parts.push(`<li>${escHtml(i)}</li>`);
          continue;
        }
        const headParts = [];
        if (i.amount) headParts.push(String(i.amount));
        if (i.unit) headParts.push(String(i.unit));
        const head = headParts.join(" ");
        const line = (head ? head + " " : "") + (i.name || "");
        const note = i.notes ? ` <small>(${escHtml(String(i.notes))})</small>` : "";
        parts.push(`<li>${escHtml(line)}${note}</li>`);
      }
      parts.push("</ul>");
    }
    const inst = r.instructions || [];
    if (inst.length) {
      parts.push("<h4>Шаги</h4><ol>");
      for (const step of inst) {
        parts.push(`<li>${escHtml(String(step))}</li>`);
      }
      parts.push("</ol>");
    }
    return `<div class="gen-preview-recipe">${parts.join("")}</div>`;
  }

  RM.generator = { setup, loadSuggestions };
})(window.RM);
