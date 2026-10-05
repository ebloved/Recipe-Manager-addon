"use strict";
(function (RM) {
  const { $, setStatus } = RM.utils;
  const { postForm, postJSON } = RM.api;
  const state = RM.state;

  function setup() {
    $("yt-download").addEventListener("click", onDownload);
    $("yt-generate").addEventListener("click", onGenerate);
    $("yt-save").addEventListener("click", onSave);
  }

  async function onDownload() {
    const url = $("yt-url").value.trim();
    if (!url) return;
    const status = $("yt-status");
    const btn = $("yt-download");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Скачивание…';
    setStatus(status, "Скачиваем субтитры через yt-dlp…", "info");
    try {
      const fd = new FormData();
      fd.append("url", url);
      const data = await postForm("api/download", fd);
      state.currentJobId = data.job_id;
      $("yt-generate").disabled = false;
      setStatus(status, `✓ Скачано ${data.count} файлов. Нажмите «Сгенерировать».`, "success");
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "1. Скачать субтитры";
    }
  }

  async function onGenerate() {
    if (!state.currentJobId) return;
    const status = $("yt-status");
    const btn = $("yt-generate");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Генерация…';
    setStatus(status, "Отправляем субтитры в Gemini…", "info");
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

  RM.youtube = { setup };
})(window.RM);