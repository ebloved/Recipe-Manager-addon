"use strict";
(function (RM) {
  const { $, setStatus, clearStatus } = RM.utils;
  const { postForm, postJSON } = RM.api;
  const state = RM.state;

  let pendingMdFileContent = null;

  function setup() {
    $("scrape-fetch").addEventListener("click", onScrape);
    $("md-fetch").addEventListener("click", onMdUrl);
    $("md-file").addEventListener("change", onMdFileChange);
    $("md-file-save").addEventListener("click", onMdFileSave);
    $("md-paste-save").addEventListener("click", onMdPasteSave);
    $("manual-open-editor").addEventListener("click", onManualOpen);
  }

  async function onScrape() {
    const url = $("scrape-url").value.trim();
    if (!url) return;
    const status = $("scrape-status");
    const btn = $("scrape-fetch");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Загрузка…';
    clearStatus(status);
    try {
      const fd = new FormData();
      fd.append("url", url);
      const data = await postForm("api/scrape", fd);
      const r = data.recipe;
      RM.editor.open(null, () => {
        state.recipes = [];
        RM.recipes.load();
        RM.tabs.switchToRecipes();
      }, {
        name: r.name, description: r.description,
        source_url: r.source_url, image_url: r.image_url,
        servings: r.servings, servings_text: r.servings_text,
        prep_time: r.prep_time, cook_time: r.cook_time, total_time: r.total_time,
        tags: r.tags || [], courses: r.courses || [],
        categories: r.categories || [], collections: r.collections || [],
        cuisine: r.cuisine,
        ingredients: (r.ingredients || []).map((s) =>
          typeof s === "string" ? { name: s } : s),
        instructions: r.instructions || [],
      });
      setStatus(status, `✓ Загружено «${r.name}». Проверьте в редакторе.`, "success");
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Загрузить";
    }
  }

  async function onMdUrl() {
    const url = $("md-url").value.trim();
    if (!url) return;
    const status = $("md-url-status");
    const btn = $("md-fetch");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Загрузка…';
    clearStatus(status);
    try {
      const fd = new FormData();
      fd.append("url", url);
      const data = await postForm("api/recipes/import-url", fd);
      setStatus(status, `✓ Импортирован «${data.recipe.name}».`, "success");
      $("md-url").value = "";
      state.recipes = [];
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Загрузить и сохранить";
    }
  }

  function onMdFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      pendingMdFileContent = ev.target.result || "";
      $("md-file-name").textContent = `${file.name} (${(file.size/1024).toFixed(1)} KB)`;
      $("md-file-save").disabled = !pendingMdFileContent.trim();
    };
    reader.readAsText(file, "utf-8");
  }

  async function onMdFileSave() {
    if (!pendingMdFileContent) return;
    const status = $("md-file-status");
    const btn = $("md-file-save");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Сохранение…';
    clearStatus(status);
    try {
      const data = await postJSON("api/recipes", { markdown_content: pendingMdFileContent });
      setStatus(status, `✓ Рецепт «${data.recipe.name}» сохранён.`, "success");
      pendingMdFileContent = null;
      $("md-file").value = "";
      $("md-file-name").textContent = "";
      btn.disabled = true;
      state.recipes = [];
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
      btn.disabled = false;
    } finally {
      btn.textContent = "Сохранить файл";
    }
  }

  async function onMdPasteSave() {
    const md = $("md-paste").value.trim();
    if (!md) return;
    const status = $("md-paste-status");
    const btn = $("md-paste-save");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Сохранение…';
    clearStatus(status);
    try {
      const data = await postJSON("api/recipes", { markdown_content: md });
      setStatus(status, `✓ Рецепт «${data.recipe.name}» сохранён.`, "success");
      $("md-paste").value = "";
      state.recipes = [];
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Сохранить рецепт";
    }
  }

  function onManualOpen() {
    RM.editor.open(null, () => {
      state.recipes = [];
      RM.tabs.switchToRecipes();
      RM.recipes.load();
    });
  }

  RM.imports = { setup };
})(window.RM);