"use strict";
(function (RM) {
  const { $, escHtml, setStatus, clearStatus } = RM.utils;
  const { getJSON, postJSON } = RM.api;

  function setup() {
    $("sync-pull").addEventListener("click", onPull);
    $("sync-push").addEventListener("click", onPush);
  }

  async function load() {
    const box = $("sync-status");
    box.innerHTML = '<div class="loading"><span class="spinner"></span> Проверка соединения…</div>';
    try {
      const data = await getJSON("api/sync/status");
      box.innerHTML = `
        <div class="sync-info">
          <div class="sync-row"><span>Репозиторий:</span><b>${escHtml(data.repo)}</b></div>
          <div class="sync-row"><span>Ветка:</span><b>${escHtml(data.branch)}</b></div>
          <div class="sync-row"><span>Файл:</span><b>${escHtml(data.path)}</b></div>
          <div class="sync-row"><span>Статус:</span>
            ${data.exists
              ? `<b style="color:var(--success)">✓ файл найден</b>`
              : `<b style="color:var(--text-secondary)">файл ещё не создан</b>`}
          </div>
          ${data.sha ? `<div class="sync-row"><span>SHA:</span><code>${escHtml(data.sha.slice(0, 10))}…</code></div>` : ""}
        </div>`;
    } catch (err) {
      box.innerHTML = `<div class="empty" style="padding:20px 0"><div class="icon">⚠️</div><p>${escHtml(err.message)}</p></div>`;
    }
  }

  async function onPull() {
    if (!confirm("Забрать recipes.json из GitHub и ЗАМЕНИТЬ локальные рецепты?")) return;
    const msg = $("sync-msg");
    const btn = $("sync-pull");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Загрузка…';
    clearStatus(msg);
    try {
      const data = await postJSON("api/sync/pull", { replace_all: true });
      setStatus(msg, `✓ Загружено ${data.added} рецептов из GitHub.`, "success");
      RM.state.recipes = [];
      RM.recipes.load();
    } catch (err) {
      setStatus(msg, "Ошибка: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "⬇️ Забрать из GitHub";
    }
  }

  async function onPush() {
    if (!confirm("Залить текущие рецепты в GitHub? Локальный файл в репе будет перезаписан.")) return;
    const msg = $("sync-msg");
    const btn = $("sync-push");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Отправка…';
    clearStatus(msg);
    try {
      const data = await postJSON("api/sync/push", {});
      const verb = data.updated ? "обновлён" : "создан";
      const commit = data.commit_sha ? data.commit_sha.slice(0, 7) : "?";
      setStatus(msg, `✓ Файл ${verb} в GitHub (commit ${commit}).`, "success");
      load();
    } catch (err) {
      setStatus(msg, "Ошибка: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "⬆️ Отправить в GitHub";
    }
  }

  RM.sync = { setup, load };
})(window.RM);