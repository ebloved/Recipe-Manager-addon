/* Профили генерации рецептов.
 *
 * Требуемые id в index.html:
 *   profile-selector         — контейнер в шапке
 *   profile-selector-icon    — иконка активного профиля
 *   profile-select           — <select> активного профиля
 *   profile-manage-btn       — кнопка "⚙️ Управление"
 *   profiles-overlay         — оверлей модалки управления
 *   profiles-close           — закрыть модалку
 *   profiles-add             — добавить новый профиль
 *   profiles-list            — список профилей в модалке
 *   profiles-editor          — блок редактора (скрыт по умолчанию)
 *   profiles-editor-title    — заголовок редактора
 *   profile-name, profile-icon, profile-description
 *   profile-max-kcal, profile-max-active, profile-max-total,
 *   profile-min-protein, profile-max-sugar,
 *   profile-avoid-methods, profile-prefer-methods,
 *   profile-avoid-ingredients, profile-prefer-ingredients,
 *   profile-delete, profile-cancel, profile-save,
 *   profile-editor-status
 */
"use strict";
(function (RM) {
  const { $, escHtml, setStatus, clearStatus } = RM.utils;
  const { getJSON, postJSON, patchJSON, del } = RM.api;
  const state = RM.state;

  state.profiles = [];
  state.activeProfileId = null;

  // Локальное состояние редактора
  let editorState = null; // { profile, isNew }

  // =====================================================================
  // Setup
  // =====================================================================

  function setup() {
    $("profile-select").addEventListener("change", onSelectActive);
    $("profile-manage-btn").addEventListener("click", openManager);

    $("profiles-close").addEventListener("click", closeManager);
    $("profiles-overlay").addEventListener("click", (e) => {
      if (e.target === $("profiles-overlay")) closeManager();
    });
    $("profiles-add").addEventListener("click", () => openEditor(null));

    $("profile-save").addEventListener("click", onSave);
    $("profile-cancel").addEventListener("click", closeEditor);
    $("profile-delete").addEventListener("click", onDelete);
  }

  // =====================================================================
  // Загрузка
  // =====================================================================

  async function load() {
    try {
      const data = await getJSON("api/profiles");
      state.profiles = data.profiles || [];
      state.activeProfileId = data.active_id || null;
      renderSelector();
      if ($("profiles-overlay").classList.contains("show")) {
        renderList();
      }
    } catch (err) {
      console.warn("[profiles] load failed:", err.message);
      state.profiles = [];
      state.activeProfileId = null;
      renderSelector();
    }
  }

  // =====================================================================
  // Селектор в шапке
  // =====================================================================

  function renderSelector() {
    const sel = $("profile-select");
    const icon = $("profile-selector-icon");
    const current = state.activeProfileId || "";

    let html = `<option value="">Без профиля</option>`;
    for (const p of state.profiles) {
      const prefix = p.icon ? `${p.icon} ` : "";
      html += `<option value="${escHtml(p.id)}">${escHtml(prefix + p.name)}</option>`;
    }
    sel.innerHTML = html;
    sel.value = current;

    const active = state.profiles.find((p) => p.id === current);
    icon.textContent = active && active.icon ? active.icon : "🍽";
  }

  async function onSelectActive(e) {
    const id = e.target.value || null;
    try {
      await postJSON("api/profiles/active", { profile_id: id });
      state.activeProfileId = id;
      renderSelector();
      if ($("profiles-overlay").classList.contains("show")) renderList();
    } catch (err) {
      alert("Не удалось переключить профиль: " + err.message);
      renderSelector();
    }
  }

  function getActive() {
    if (!state.activeProfileId) return null;
    return state.profiles.find((p) => p.id === state.activeProfileId) || null;
  }

  // =====================================================================
  // Модалка управления
  // =====================================================================

  function openManager() {
    closeEditor();
    $("profiles-overlay").classList.add("show");
    renderList();
  }

  function closeManager() {
    $("profiles-overlay").classList.remove("show");
    closeEditor();
  }

  function renderList() {
    const list = $("profiles-list");
    if (!state.profiles.length) {
      list.innerHTML = `<div class="profiles-empty">Профилей пока нет. Нажмите «+ Новый».</div>`;
      return;
    }

    list.innerHTML = state.profiles.map((p) => {
      const active = p.id === state.activeProfileId;
      const c = p.constraints || {};
      const badges = [];
      if (c.max_calories_per_serving) badges.push(`≤${c.max_calories_per_serving} ккал`);
      if (c.max_active_time_min) badges.push(`≤${c.max_active_time_min} мин`);
      if (c.min_protein_per_serving_g) badges.push(`белок ≥${c.min_protein_per_serving_g} г`);
      const badgesHtml = badges.length
        ? `<div class="profile-card-badges">${badges.map((b) => `<span class="profile-badge">${escHtml(b)}</span>`).join("")}</div>`
        : "";

      return `<div class="profile-card ${active ? "active" : ""}" data-profile-id="${escHtml(p.id)}">
        <div class="profile-card-icon">${escHtml(p.icon || "🍽")}</div>
        <div class="profile-card-info">
          <div class="profile-card-name">
            ${escHtml(p.name)}
            ${active ? `<span class="profile-card-active">активный</span>` : ""}
          </div>
          ${p.description ? `<div class="profile-card-desc">${escHtml(p.description)}</div>` : ""}
          ${badgesHtml}
        </div>
        <button class="profile-card-edit" title="Редактировать">✏️</button>
      </div>`;
    }).join("");

    list.querySelectorAll(".profile-card").forEach((card) => {
      card.addEventListener("click", (e) => {
        if (e.target.closest(".profile-card-edit")) {
          e.stopPropagation();
          const id = card.dataset.profileId;
          const p = state.profiles.find((x) => x.id === id);
          if (p) openEditor(p);
          return;
        }
        setActive(card.dataset.profileId);
      });
    });

    async function setActive(id) {
      try {
        await postJSON("api/profiles/active", { profile_id: id });
        state.activeProfileId = id;
        renderSelector();
        renderList();
      } catch (err) {
        alert("Ошибка: " + err.message);
      }
    }
  }

  // =====================================================================
  // Редактор профиля
  // =====================================================================

  function openEditor(profile) {
    const isNew = !profile || !profile.id;
    const p = profile || {};
    const c = p.constraints || {};

    editorState = { profile: p, isNew };

    $("profiles-editor-title").textContent = isNew ? "Новый профиль" : "Редактирование";
    $("profile-name").value = p.name || "";
    $("profile-icon").value = p.icon || "";
    $("profile-description").value = p.description || "";

    $("profile-max-kcal").value = c.max_calories_per_serving ?? "";
    $("profile-max-active").value = c.max_active_time_min ?? "";
    $("profile-max-total").value = c.max_total_time_min ?? "";
    $("profile-min-protein").value = c.min_protein_per_serving_g ?? "";
    $("profile-max-sugar").value = c.max_sugar_per_serving_g ?? "";

    $("profile-avoid-methods").value = (c.avoid_methods || []).join(", ");
    $("profile-prefer-methods").value = (c.prefer_methods || []).join(", ");
    $("profile-avoid-ingredients").value = (c.avoid_ingredients || []).join(", ");
    $("profile-prefer-ingredients").value = (c.prefer_ingredients || []).join(", ");

    const delBtn = $("profile-delete");
    delBtn.style.display = isNew ? "none" : "inline-flex";

    // Сброс кнопки "Сохранить" — иначе она остаётся в состоянии
    // "Сохранение…" после предыдущего успешного сохранения.
    const saveBtn = $("profile-save");
    saveBtn.disabled = false;
    saveBtn.textContent = "💾 Сохранить";

    clearStatus($("profile-editor-status"));
    $("profiles-list").style.display = "none";
    $("profiles-editor").style.display = "block";
    $("profiles-title").textContent = isNew ? "Новый профиль" : p.name || "Профиль";
  }

  function closeEditor() {
    $("profiles-editor").style.display = "none";
    $("profiles-list").style.display = "block";
    $("profiles-title").textContent = "Профили генерации";
    editorState = null;
  }

  function readNum(id) {
    const v = $(id).value.trim();
    if (v === "") return null;
    const n = parseFloat(v.replace(",", "."));
    return isNaN(n) ? null : n;
  }

  function readList(id) {
    return ($(id).value || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  async function onSave() {
    if (!editorState) return;
    const status = $("profile-editor-status");
    const name = $("profile-name").value.trim();
    if (!name) {
      setStatus(status, "Укажите название профиля.", "error");
      return;
    }

    const payload = {
      name,
      icon: $("profile-icon").value.trim() || null,
      description: $("profile-description").value.trim() || null,
      constraints: {
        max_calories_per_serving: readNum("profile-max-kcal"),
        max_active_time_min: readNum("profile-max-active"),
        max_total_time_min: readNum("profile-max-total"),
        min_protein_per_serving_g: readNum("profile-min-protein"),
        max_sugar_per_serving_g: readNum("profile-max-sugar"),
        avoid_methods: readList("profile-avoid-methods"),
        prefer_methods: readList("profile-prefer-methods"),
        avoid_ingredients: readList("profile-avoid-ingredients"),
        prefer_ingredients: readList("profile-prefer-ingredients"),
      },
    };

    const btn = $("profile-save");
    btn.disabled = true;
    btn.textContent = "Сохранение…";
    clearStatus(status);

    try {
      if (editorState.isNew) {
        await postJSON("api/profiles", payload);
      } else {
        await patchJSON(`api/profiles/${editorState.profile.id}`, payload);
      }
      setStatus(status, "✓ Профиль сохранён.", "success");
      await load();
      setTimeout(() => {
        closeEditor();
        renderList();
      }, 350);
    } catch (err) {
      setStatus(status, "Ошибка: " + err.message, "error");
      btn.disabled = false;
      btn.textContent = "💾 Сохранить";
    }
  }

  async function onDelete() {
    if (!editorState || editorState.isNew) return;
    const p = editorState.profile;
    if (!confirm(`Удалить профиль «${p.name}»?`)) return;
    try {
      await del(`api/profiles/${p.id}`);
      await load();
      closeEditor();
      renderList();
    } catch (err) {
      alert("Ошибка: " + err.message);
    }
  }

  // =====================================================================
  // Экспорт
  // =====================================================================

  RM.profiles = { setup, load, render: renderList, getActive };
})(window.RM);