"use strict";
(function (RM) {
  const { $, escHtml, setStatus, clearStatus } = RM.utils;
  const { getJSON, postJSON, postForm } = RM.api;
  const state = RM.state;

  // -----------------------------------------------------------------
  // Локальное состояние
  // -----------------------------------------------------------------
  let pendingMdFileContent = null;
  const s = {
    batchUploading: false,
  };

  // -----------------------------------------------------------------
  // Setup
  // -----------------------------------------------------------------
  function setup() {
    // --- Scrape with URL ---
    $("scrape-fetch").addEventListener("click", onScrape);

    // --- Markdown: URL ---
    $("md-fetch").addEventListener("click", onMdUrl);

    // --- Markdown: file (single) ---
    $("md-file").addEventListener("change", onMdFileChange);
    $("md-file-save").addEventListener("click", onMdFileSave);

    // --- Markdown: paste ---
    $("md-paste-save").addEventListener("click", onMdPasteSave);

    // --- Markdown: batch (multi-file) ---
    const batchInput = $("md-batch");
    if (batchInput) {
      batchInput.addEventListener("change", onMdBatchChange);
    }
    const batchBtn = $("md-batch-save");
    if (batchBtn) {
      batchBtn.addEventListener("click", onMdBatchSave);
    }

    // --- Manual: open editor ---
    $("manual-open-editor").addEventListener("click", onManualOpen);
  }

  // -----------------------------------------------------------------
  // Scrape from URL
  // -----------------------------------------------------------------
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

      // Открываем редактор с предзаполненными полями (не сохраняет сразу)
      RM.editor.open(null, () => {
        state.recipes = [];
        RM.recipes.load();
        RM.tabs.switchToRecipes();
      }, {
        name: r.name,
        description: r.description,
        source_url: r.source_url,
        image_url: r.image_url,
        servings: r.servings,
        servings_text: r.servings_text,
        prep_time: r.prep_time,
        cook_time: r.cook_time,
        total_time: r.total_time,
        tags: r.tags || [],
        courses: r.courses || [],
        categories: r.categories || [],
        collections: r.collections || [],
        cuisine: r.cuisine,
        ingredients: (r.ingredients || []).map((x) =>
          typeof x === "string" ? { name: x } : x),
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

  // -----------------------------------------------------------------
  // Markdown from URL
  // -----------------------------------------------------------------
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
      const recipe = data.recipe;

      setStatus(status, `✓ Импортирован «${recipe.name}».`, "success");
      $("md-url").value = "";
      state.recipes = [];

      // Прогон matcher-batch по одному рецепту.
      // Если найдены спорные связки — откроется очередь.
      if (RM.matcherBatch && recipe.id) {
        RM.matcherBatch.processAfterImport([recipe.id]).catch((e) => {
          console.warn("matcherBatch:", e);
        });
      }
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Загрузить и сохранить";
    }
  }

  // -----------------------------------------------------------------
  // Markdown: single file
  // -----------------------------------------------------------------
  function onMdFileChange(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (ev) => {
      pendingMdFileContent = ev.target.result || "";
      $("md-file-name").textContent =
        `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
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
      const data = await postJSON("api/recipes", {
        markdown_content: pendingMdFileContent,
      });
      const recipe = data.recipe;

      setStatus(status, `✓ Рецепт «${recipe.name}» сохранён.`, "success");
      pendingMdFileContent = null;
      $("md-file").value = "";
      $("md-file-name").textContent = "";
      btn.disabled = true;
      state.recipes = [];

      if (RM.matcherBatch && recipe.id) {
        RM.matcherBatch.processAfterImport([recipe.id]).catch((e) => {
          console.warn("matcherBatch:", e);
        });
      }
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
      btn.disabled = false;
    } finally {
      btn.textContent = "Сохранить файл";
    }
  }

  // -----------------------------------------------------------------
  // Markdown: paste
  // -----------------------------------------------------------------
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
      const recipe = data.recipe;

      setStatus(status, `✓ Рецепт «${recipe.name}» сохранён.`, "success");
      $("md-paste").value = "";
      state.recipes = [];

      if (RM.matcherBatch && recipe.id) {
        RM.matcherBatch.processAfterImport([recipe.id]).catch((e) => {
          console.warn("matcherBatch:", e);
        });
      }
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Сохранить рецепт";
    }
  }

  // -----------------------------------------------------------------
  // Markdown: batch (multiple files)
  // -----------------------------------------------------------------
  //
  // Отправляет все выбранные .md одним запросом.
  // Бэкенд (routes/imports.py) прогоняет через link_many_recipes с общим
  // barcode-кэшем: если в 20 файлах один и тот же продукт с одним barcode,
  // OFF спрашивают один раз.
  //
  // После сохранения прогоняет matcher-batch по всем id сразу.

  function onMdBatchChange(e) {
    const files = e.target.files;
    const btn = $("md-batch-save");
    const label = $("md-batch-name");
    if (!files || !files.length) {
      if (label) label.textContent = "";
      if (btn) btn.disabled = true;
      return;
    }
    if (label) {
      label.textContent = `Выбрано файлов: ${files.length}`;
    }
    if (btn) btn.disabled = false;
  }

  async function onMdBatchSave() {
    if (s.batchUploading) return;

    const input = $("md-batch");
    const files = input && input.files;
    if (!files || !files.length) return;

    const status = $("md-batch-status");
    const btn = $("md-batch-save");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Импорт…';
    clearStatus(status);

    s.batchUploading = true;

    try {
      const fd = new FormData();
      for (const f of files) {
        fd.append("files", f, f.name);
      }

      const resp = await fetch(RM.api.api("api/recipes/import-batch"), {
        method: "POST",
        body: fd,
      });
      const data = await resp.json();

      if (!resp.ok) {
        throw new Error(data.detail || JSON.stringify(data));
      }

      const imported = data.imported || 0;
      const failed = data.failed || 0;
      const recipes = data.recipes || [];
      const errors = data.errors || [];

      let msg = `✓ Импортировано ${imported} из ${files.length}`;
      if (failed) {
        msg += `, ошибок: ${failed}`;
      }
      setStatus(status, msg, failed ? "info" : "success");

      // Показываем ошибки, если есть
      if (errors.length) {
        const errorLines = errors
          .slice(0, 5)
          .map((e) => `• ${e.filename}: ${e.message || e.error || "unknown"}`)
          .join("\n");
        const suffix = errors.length > 5 ? `\n… и ещё ${errors.length - 5}` : "";
        console.warn("Ошибки импорта:\n" + errorLines + suffix);
      }

      // Очищаем форму
      input.value = "";
      const label = $("md-batch-name");
      if (label) label.textContent = "";
      state.recipes = [];

      // Прогон matcher-batch по всем импортированным id
      const recipeIds = recipes.map((r) => r.id).filter(Boolean);
      if (recipeIds.length && RM.matcherBatch) {
        // Не ждём — пусть работает в фоне. Пользователь может смотреть
        // список рецептов, а очередь подтверждений появится поверх.
        RM.matcherBatch.processAfterImport(recipeIds).catch((e) => {
          console.warn("matcherBatch после batch-импорта:", e);
        });
      }
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
    } finally {
      s.batchUploading = false;
      btn.disabled = false;
      btn.textContent = "Импортировать все";
    }
  }

  // -----------------------------------------------------------------
  // Manual (open editor)
  // -----------------------------------------------------------------
  function onManualOpen() {
    RM.editor.open(null, () => {
      state.recipes = [];
      RM.tabs.switchToRecipes();
      RM.recipes.load();
    });
  }

  // -----------------------------------------------------------------
  // Public
  // -----------------------------------------------------------------
  RM.imports = { setup };
})(window.RM);