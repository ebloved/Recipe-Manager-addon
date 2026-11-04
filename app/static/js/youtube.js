"use strict";
(function (RM) {
  const { $, setStatus } = RM.utils;
  const { getJSON, postForm, postJSON } = RM.api;
  const state = RM.state;

  function setup() {
    const bind = (id, fn) => { const el = $(id); if (el) el.addEventListener("click", fn); };
    bind("yt-download", onDownload);
    bind("yt-generate", onGenerate);
    bind("yt-save", onSave);
    applyStatus();
  }

  // Скрывает вкладку YouTube, если фича выключена.
  function hideYoutubeTab() {
    const tab = $("subtab-add-yt");
    const panel = $("subpanel-add-yt");
    const wasActive = tab && tab.classList.contains("active");
    if (tab) tab.style.display = "none";
    if (panel) {
      panel.classList.remove("active");
      panel.style.display = "none";
    }
    if (wasActive) {
      const fallback = document.querySelector('.sub-tab[data-subpanel="add-scrape"]');
      if (fallback) {
        fallback.classList.add("active");
        const target = $("subpanel-add-scrape");
        if (target) target.classList.add("active");
      }
    }
  }

  function applyQuota(quota) {
    const q = quota || {};
    const blocked = !!q.blocked;
    const form = $("yt-form-card");
    const card = $("yt-quota-card");
    const message = $("yt-quota-message");
    const preview = $("yt-preview-card");

    if (!blocked) {
      if (card) card.style.display = "none";
      if (form) form.style.display = "";
      return;
    }
    if (form) form.style.display = "none";
    if (preview) preview.style.display = "none";
    if (card) card.style.display = "";
    if (message) {
      message.textContent = q.reason === "token_missing"
        ? "Импорт временно недоступен: Apify не настроен. Обратитесь к администратору."
        : "Импорт временно недоступен: лимит транскрипций исчерпан. Попробуйте позже.";
    }
  }

  async function applyStatus() {
    let data;
    try {
      data = await getJSON("api/youtube/status");
    } catch (e) {
      return; // при ошибке не ломаем UI
    }
    if (data.enabled === false) {
      hideYoutubeTab();
      return;
    }
    applyQuota(data.quota || {});
  }

  async function onDownload() {
    const url = $("yt-url").value.trim();
    if (!url) return;
    const status = $("yt-status");
    const btn = $("yt-download");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Получение…';
    setStatus(status, "Запрашиваем транскрипт через Apify…", "info");
    try {
      const fd = new FormData();
      fd.append("url", url);
      const data = await postForm("api/download", fd);
      state.currentJobId = data.job_id;
      $("yt-generate").disabled = false;
      const suffix = data.cached
        ? "транскрипт из кэша, кредиты не потрачены"
        : `получено ${data.chars} символов`;
      setStatus(status, `✓ Готово: ${suffix}. Нажмите «Сгенерировать».`, "success");
      await applyStatus();
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
      await applyStatus();
    } finally {
      btn.disabled = false;
      btn.textContent = "1. Получить транскрипт";
    }
  }

  async function onGenerate() {
    if (!state.currentJobId) return;
    const status = $("yt-status");
    const btn = $("yt-generate");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Генерация…';
    setStatus(status, "Отправляем транскрипт в LLM…", "info");
    try {
      const fd = new FormData();
      fd.append("job_id", state.currentJobId);
      const data = await postForm("api/generate-recipe", fd);
      $("yt-md").value = data.markdown;
      $("yt-preview-card").style.display = "block";
      setStatus(status, `✓ Сгенерировано моделью ${data.model}.`, "success");
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "2. Сгенерировать рецепт";
    }
  }

  async function onSave() {
    const md = $("yt-md").value.trim();
    if (!md) return;
    const status = $("yt-status");
    const btn = $("yt-save");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Сохранение…';
    try {
      const data = await postJSON("api/recipes", { markdown_content: md });
      setStatus(status, `✓ Рецепт «${data.recipe.name}» сохранён.`, "success");
      $("yt-preview-card").style.display = "none";
      $("yt-md").value = "";
      $("yt-url").value = "";
      state.currentJobId = null;
      $("yt-generate").disabled = true;
      state.recipes = [];
    } catch (err) {
      setStatus(status, "Ошибка сохранения: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "💾 Сохранить в рецепты";
    }
  }

  RM.youtube = { setup, refreshStatus: applyStatus };
})(window.RM);
