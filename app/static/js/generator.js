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
      if (data && data.job_id) {
        await pollJob(data.job_id);
      } else {
        setStatus(status, `✓ Создано ${data.created} предложений.`, "success");
        await loadSuggestions();
      }
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
        setStatus(status, "Ошибка: " + (j.error || "неизвестно"), "error");
        return;
      }
      if (elapsed > 300) {
        setStatus(status, "Ошибка: превышен лимит 5 минут", "error");
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
    if (!s) return;
    const md = s.markdown || "";
    const html = `<pre style="white-space:pre-wrap;font-size:12px;background:#f4f6f8;padding:12px;border-radius:8px;max-height:60vh;overflow:auto;color:#111">${escHtml(md)}</pre>`;
    const w = window.open("", "_blank", "width=800,height=700");
    if (!w) return;
    w.document.write(`<html><head><title>Preview</title><style>body{font-family:system-ui;padding:16px;background:#fff;color:#111}</style></head><body><h2>${escHtml(s.recipe_data?.name || "—")}</h2>${html}</body></html>`);
    w.document.close();
  }

  RM.generator = { setup, loadSuggestions };
})(window.RM);
