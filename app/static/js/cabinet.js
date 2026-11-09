"use strict";
(function (RM) {
  const { $, escHtml } = RM.utils;
  const { getJSON, postJSON, del } = RM.api;

  function setup() {
    const btnTour = $("btn-start-tour");
    if (btnTour && RM.walkthrough) btnTour.onclick = () => RM.walkthrough.start("main");

    const btnCabTour = $("btn-cabinet-tour");
    if (btnCabTour && RM.walkthrough) btnCabTour.onclick = () => RM.walkthrough.start("cabinet");

    // Синхронизация управляется своим модулем
    if (RM.sync) RM.sync.setup();

    // Вкладка журнала — только для админа.
    refreshAuditTab();
  }

  async function refreshAuditTab() {
    try {
      let me = RM.state.user;
      if (!me) me = await getJSON("api/me");
      const tab = $("tab-audit");
      if (tab) tab.style.display = me && me.role === "admin" ? "" : "none";
    } catch (e) {
      const tab = $("tab-audit");
      if (tab) tab.style.display = "none";
    }
  }

  async function load() {
    try { await loadUser(); } catch (e) { console.error("loadUser", e); }
    try { await loadProgress(); } catch (e) { console.error("loadProgress", e); }
    try { await loadSettings(); } catch (e) { console.error("loadSettings", e); }
    try { await loadAdmin(); } catch (e) { console.error("loadAdmin", e); }
    try { await loadApify(); } catch (e) { console.error("loadApify", e); }
    try { await loadLLMForm(); } catch (e) { console.error("loadLLMForm", e); }
    if (RM.sync) {
      try { await RM.sync.load(); } catch (e) { console.error("sync", e); }
    }
    try { await loadVersion(); } catch (e) { console.error("loadVersion", e); }
    try { await loadPendingWeights(); } catch (e) { console.error("loadPendingWeights", e); }
  }

  async function loadApify() {
    const card = $("cabinet-apify");
    if (!card) return;
    let me = RM.state.user;
    if (!me) {
      try { me = await getJSON("api/me"); RM.state.user = me; } catch (e) { return; }
    }
    if (!me || me.role !== "admin") {
      card.style.display = "none";
      return;
    }
    card.style.display = "block";
    const btn = $("apify-refresh");
    if (btn) btn.onclick = () => renderApify(true);
    await renderApify(false);
  }

  async function renderApify(force) {
    const summary = $("apify-summary");
    const bar = $("apify-bar");
    const details = $("apify-details");
    if (!summary || !bar) return;
    try {
      const q = await getJSON("api/youtube/limits" + (force ? "?refresh=1" : ""));
      if (q.reason === "token_missing") {
        summary.textContent = "Apify не настроен: задайте APIFY_TOKEN.";
        summary.style.color = "var(--danger)";
        bar.style.width = "0%";
        details.textContent = "YouTube-импорт недоступен.";
        return;
      }
      if (!q.available) {
        summary.textContent = "Не удалось получить лимиты Apify.";
        summary.style.color = "var(--danger)";
        bar.style.width = "0%";
        details.textContent = q.error || "";
        return;
      }
      const used = Number(q.used_usd || 0);
      const limit = Number(q.limit_usd || 0);
      const percent = Math.min(100, Number(q.percent || 0));
      const color = percent < 50 ? "#16a34a" : percent <= 80 ? "#f5a623" : "#dc2626";
      const usedText = used >= 0.01 ? used.toFixed(2) : used.toFixed(4);
      summary.textContent = `Использовано $${usedText} из $${limit.toFixed(2)} (${percent.toFixed(1)}%)` +
        (q.blocked ? " — импорт заблокирован" : "");
      summary.style.color = color;
      bar.style.width = percent + "%";
      bar.style.background = color;
      const threshold = Math.round((q.stop_ratio || 0.9) * 100);
      const checked = q.checked_at ? new Date(q.checked_at * 1000).toLocaleTimeString() : "—";
      details.textContent = `Порог блокировки: ${threshold}% · Актор: ${q.actor || "—"} · Проверено: ${checked}`;
    } catch (e) {
      summary.textContent = "Ошибка: " + e.message;
      summary.style.color = "var(--danger)";
    }
  }

  async function loadUser() {
    const box = $("cabinet-user");
    if (!box) return;
    try {
      const data = await getJSON("api/me");
      box.innerHTML = `
        <div class="hint">
          <div style="font-size:16px; font-weight:600; margin-bottom:4px">
            👤 ${escHtml(data.name || "Пользователь")}
          </div>
          <div style="font-size:13px; color:var(--text-secondary)">
            Источник: ${data.source === 'ha' ? 'Home Assistant' : 'Прямой доступ'}
          </div>
        </div>
        <div style="margin-top:12px; padding-top:12px; border-top:1px solid var(--border);">
          <label style="display:inline-flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
            <input type="checkbox" id="cabinet-show-side-recipes" style="width:18px; height:18px; accent-color:var(--accent);">
            Показывать гарнир
          </label>
          <div style="font-size:11px; line-height:1.4; color:var(--text-muted); margin-top:5px;">
            Показывать карточки гарниров в списке рецептов.
          </div>

          <label style="display:inline-flex; align-items:center; gap:8px; font-size:13px; cursor:pointer; margin-top:12px;">
            <input type="checkbox" id="cabinet-offer-side" style="width:18px; height:18px; accent-color:var(--accent);">
            Предлагать гарнир
          </label>
          <div style="font-size:11px; line-height:1.4; color:var(--text-muted); margin-top:5px;">
            Предлагать гарнир при добавлении в «На кухню». Для блюд с тегом
            «самостоятельное» не работает.
          </div>

          ${data.can_use_progress ? `
          <label style="display:inline-flex; align-items:center; gap:8px; font-size:13px; cursor:pointer; margin-top:12px;">
            <input type="checkbox" id="cabinet-show-progress" style="width:18px; height:18px; accent-color:var(--accent);">
            Показывать «Мой прогресс»
          </label>
          <div style="font-size:11px; line-height:1.4; color:var(--text-muted); margin-top:5px;">
            Показывать карточку с ростом, весом и BMI-ориентиром.
          </div>` : ""}
        </div>`;

      const showSideRecipes = $("cabinet-show-side-recipes");
      if (showSideRecipes) {
        showSideRecipes.checked = RM.prefs
          ? RM.prefs.getShowSideRecipes()
          : true;
        showSideRecipes.onchange = (e) => {
          if (RM.prefs) RM.prefs.setShowSideRecipes(e.target.checked);
          if (RM.recipes && RM.recipes.filterAndRender) {
            RM.recipes.filterAndRender();
          }
        };
      }

      const offerSide = $("cabinet-offer-side");
      if (offerSide) {
        offerSide.checked = RM.prefs
          ? RM.prefs.getOfferSideCooking()
          : true;
        offerSide.onchange = (e) => {
          if (RM.prefs) RM.prefs.setOfferSideCooking(e.target.checked);
        };
      }
    } catch (err) {
      box.innerHTML = `<div class="hint" style="color:var(--danger)">Ошибка: ${escHtml(err.message)}</div>`;
    }
  }


  function progressStatus(text, type) {
    const el = $("progress-status");
    if (!el) return;
    el.textContent = text || "";
    el.className = "status" + (text ? " show " + (type || "info") : "");
  }

  function renderProgress(metrics) {
    const box = $("progress-result");
    if (!box) return;
    if (!metrics) {
      box.innerHTML = '<div class="hint" style="font-size:11px; margin-top:12px;">Укажите рост и вес, чтобы увидеть BMI и здоровый диапазон веса.</div>';
      return;
    }
    const rows = [
      { id: "low", label: "Ниже нормы", range: "< 18.5" },
      { id: "normal", label: "В пределах нормы", range: "18.5–24.9" },
      { id: "above", label: "Выше нормы", range: "25–29.9" },
      { id: "high", label: "Значительно выше нормы", range: "30+" },
    ];
    const active = metrics.category ? metrics.category.id : "";
    const healthy = metrics.healthy_range_kg || {};
    let target = "";
    if (metrics.target_weight_kg) {
      target = `<div class="progress-target">
        Цель: <b>${escHtml(String(metrics.target_weight_kg))} кг</b>
        ${metrics.target_bmi ? `· BMI ${escHtml(String(metrics.target_bmi))}` : ""}
        ${metrics.target_category ? `(${escHtml(metrics.target_category.label)})` : ""}
      </div>`;
      if (metrics.target_category && metrics.target_category.id !== "normal") {
        target += `<div class="progress-warning">Целевой вес вне типичного диапазона. Это ориентир, а не рекомендация — обсудите с врачом.</div>`;
      }
    }
    box.innerHTML = `
      <div class="progress-summary">
        <div class="progress-bmi-main">
          <b>${escHtml(String(metrics.bmi))}</b>
          <span>BMI</span>
        </div>
        <div>
          <div class="progress-bmi-label">${escHtml(metrics.category ? metrics.category.label : "")}</div>
          <div class="progress-muted">${escHtml(metrics.category ? metrics.category.range : "")}</div>
        </div>
      </div>
      <div class="progress-healthy">
        Здоровый диапазон для роста: <b>${escHtml(String(healthy.min ?? "—"))}–${escHtml(String(healthy.max ?? "—"))} кг</b>
      </div>
      ${target}
      <table class="bmi-table">
        <thead><tr><th>BMI</th><th>Категория</th><th>Диапазон</th></tr></thead>
        <tbody>
          ${rows.map((row) => `<tr class="${row.id === active ? "active" : ""}">
            <td>${row.id === active ? `● ${escHtml(String(metrics.bmi))}` : ""}</td>
            <td>${escHtml(row.label)}</td>
            <td>${escHtml(row.range)}</td>
          </tr>`).join("")}
        </tbody>
      </table>`;
  }

  async function loadProgress() {
    const card = $("cabinet-progress");
    if (!card) return;
    let data;
    try {
      data = await getJSON("api/progress");
    } catch (_) {
      card.style.display = "none";
      return;
    }
    const enabled = data.enabled !== false;
    const toggle = $("cabinet-show-progress");
    if (toggle) {
      toggle.checked = enabled;
      if (!toggle.dataset.bound) {
        toggle.dataset.bound = "1";
        toggle.onchange = async (e) => {
          try {
            await postJSON("api/progress", { enabled: e.target.checked });
            if (e.target.checked) {
              await loadProgress();
            } else {
              card.style.display = "none";
            }
          } catch (err) {
            e.target.checked = !e.target.checked;
            alert("Ошибка сохранения: " + err.message);
          }
        };
      }
    }
    card.style.display = enabled ? "" : "none";
    if (!enabled) return;

    const progress = data.progress || {};
    if ($("progress-height")) $("progress-height").value = progress.height_cm ?? "";
    if ($("progress-weight")) $("progress-weight").value = progress.weight_kg ?? "";
    if ($("progress-target")) $("progress-target").value = progress.target_weight_kg ?? "";
    renderProgress(data.metrics || null);
    progressStatus("");

    const save = $("progress-save");
    if (save && !save.dataset.bound) {
      save.dataset.bound = "1";
      save.onclick = async () => {
        const height = parseFloat($("progress-height")?.value || "");
        const weight = parseFloat($("progress-weight")?.value || "");
        const targetRaw = $("progress-target")?.value || "";
        const target = targetRaw ? parseFloat(targetRaw) : null;
        if (!Number.isFinite(height) || !Number.isFinite(weight)) {
          progressStatus("Укажите рост и вес.", "error");
          return;
        }
        save.disabled = true;
        progressStatus("Сохранение…", "info");
        try {
          const result = await postJSON("api/progress", {
            height_cm: height,
            weight_kg: weight,
            target_weight_kg: target,
          });
          renderProgress(result.metrics || null);
          progressStatus("Сохранено.", "success");
          if ($("cabinet-progress")) $("cabinet-progress").style.display = "";
        } catch (err) {
          progressStatus("Ошибка: " + err.message, "error");
        } finally {
          save.disabled = false;
        }
      };
    }
  }

  async function loadSettings() {
    try {
      const data = await getJSON("api/settings");
      const chk = $("setting-auto-time");
      if (chk) {
        chk.checked = !!data.generator_auto_active_time;
        chk.onchange = async (e) => {
          try {
            await postJSON("api/settings", { generator_auto_active_time: e.target.checked });
          } catch (err) {
            alert("Ошибка сохранения: " + err.message);
            e.target.checked = !e.target.checked;
          }
        };
      }

      let me = RM.state.user;
      if (!me) me = await getJSON("api/me");

      // Системные настройки (только админ)
      if (me && me.role === "admin") {
        const sysBox = $("admin-system-settings");
        if (sysBox) sysBox.style.display = "block";
        
        if ($("setting-poll-duration")) $("setting-poll-duration").value = data.gemini_poll_duration || 300;
        if ($("setting-gen-tokens")) $("setting-gen-tokens").value = data.generator_max_tokens || 15000;
        if ($("setting-adapt-tokens")) $("setting-adapt-tokens").value = data.adapter_max_tokens || 4000;
        if ($("setting-tts-enabled")) $("setting-tts-enabled").checked = !!data.tts_enabled;
        if ($("setting-tts-limit")) $("setting-tts-limit").value = data.tts_daily_limit || 10;
        if ($("setting-audit-days")) $("setting-audit-days").value = data.audit_retention_days || 90;
        if ($("setting-visual-effect")) $("setting-visual-effect").value = data.visual_effect || "none";
        if ($("setting-meal-plan-gen")) {
          $("setting-meal-plan-gen").checked = data.meal_plan_gen_access === "admin" || data.meal_plan_gen_access === "all";
        }

        const btnSys = $("btn-save-sys-settings");
        if (btnSys) {
          btnSys.onclick = async () => {
            btnSys.disabled = true;
            try {
              await postJSON("api/settings", {
                gemini_poll_duration: parseFloat($("setting-poll-duration").value),
                generator_max_tokens: parseInt($("setting-gen-tokens").value),
                adapter_max_tokens: parseInt($("setting-adapt-tokens").value),
                tts_enabled: !!$("setting-tts-enabled")?.checked,
                tts_daily_limit: parseInt($("setting-tts-limit").value || "10", 10),
                audit_retention_days: parseInt($("setting-audit-days").value || "90", 10),
                visual_effect: $("setting-visual-effect")?.value || "none",
                meal_plan_gen_access: $("setting-meal-plan-gen")?.checked ? "admin" : "off"
              });
              if (RM.snow) {
                RM.snow.setEffect($("setting-visual-effect")?.value || "none");
              }
              if (RM.mealPlanGen && RM.mealPlanGen.refresh) {
                RM.mealPlanGen.refresh();
              }
              alert("Системные настройки сохранены!");
            } catch (e) { alert(e.message); }
            finally { btnSys.disabled = false; }
          };
        }

        // Telegram
        const tgTokenEl = $("setting-tg-token");
        const tgChatEl = $("setting-tg-chat");
        const tgStatus = $("tg-status");
        const btnSaveTg = $("btn-save-tg");

        if (tgTokenEl && tgChatEl && tgStatus && btnSaveTg) {
          tgTokenEl.value = data.telegram_bot_token || "";
          tgChatEl.value = data.telegram_chat_id || "";
          
          const updateTgStatus = (token, cid) => {
            if (token && cid) {
              tgStatus.innerHTML = "🟢 Подключен";
              tgStatus.style.color = "var(--success)";
            } else if (token && !cid) {
              tgStatus.innerHTML = "🟡 Ожидает сообщения";
              tgStatus.style.color = "#f5a623";
            } else {
              tgStatus.innerHTML = "🔴 Не настроен";
              tgStatus.style.color = "var(--text-muted)";
            }
          };
          updateTgStatus(data.telegram_bot_token, data.telegram_chat_id);

          btnSaveTg.onclick = async () => {
            btnSaveTg.disabled = true;
            try {
              const token = tgTokenEl.value.trim();
              const cid = tgChatEl.value.trim();
              await postJSON("api/settings", {
                telegram_bot_token: token,
                telegram_chat_id: cid
              });
              updateTgStatus(token, cid);
              
              if (token && !cid) {
                let pollCount = 0;
                const pollId = setInterval(async () => {
                  pollCount++;
                  try {
                    const fresh = await getJSON("api/settings");
                    if (fresh.telegram_chat_id) {
                      clearInterval(pollId);
                      tgChatEl.value = fresh.telegram_chat_id;
                      updateTgStatus(fresh.telegram_bot_token, fresh.telegram_chat_id);
                    }
                  } catch (e) {}
                  if (pollCount > 30) clearInterval(pollId);
                }, 2000);
              } else {
                alert("Настройки Telegram сохранены!");
              }
            } catch(e) { alert(e.message); }
            finally { btnSaveTg.disabled = false; }
          };
        }
      }
    } catch (e) { console.warn("Settings load error:", e); }
  }

  async function loadAdmin() {
    try {
      const me = await getJSON("api/me");
      const auditTab = $("tab-audit");
      if (me.role !== "admin") {
        if (auditTab) auditTab.style.display = "none";
        const syncCard = $("cabinet-sync");
        if (syncCard) syncCard.style.display = "none";
        return;
      }
      if (auditTab) auditTab.style.display = "";

      const adminCard = $("cabinet-admin");
      if (adminCard) adminCard.style.display = "block";
      
      const btnW = document.getElementById("btn-admin-weights");
      if (btnW && typeof openWeightsAdmin === 'function' && !btnW.dataset.bound) {
        btnW.dataset.bound = "1";
        btnW.onclick = openWeightsAdmin;
      }

      const data = await getJSON("api/admin/users");
      const list = $("admin-users-list");
      
      let html = "";
      if (data.users && data.users.length) {
        html += data.users.map(u => `
          <div style="display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--border); align-items:center;">
            <span><b>${escHtml(u.name || "Без имени")}</b> <small style="color:var(--text-muted)">(${escHtml(u.email)}) - ${u.role}</small></span>
            ${u.role !== "admin" ? `<button onclick="RM.cabinet.deleteUser('${u.email}')" class="btn" style="color:var(--danger); padding:4px 8px; font-size:12px;">Удалить</button>` : ""}
          </div>
        `).join("");
      }

      if (data.pending_emails && data.pending_emails.length) {
        html += data.pending_emails.map(email => `
          <div style="display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid var(--border); align-items:center;">
            <span><i>${escHtml(email)}</i> <small style="color:var(--text-muted)">(ожидает входа)</small></span>
            <button onclick="RM.cabinet.deleteUser('${email}')" class="btn" style="color:var(--danger); padding:4px 8px; font-size:12px;">Удалить</button>
          </div>
        `).join("");
      }

      if (!html) html = "<p style='color:var(--text-muted)'>Список пуст.</p>";
      if (list) list.innerHTML = html;

      const btnAdd = $("admin-add-btn");
      const newEmail = $("admin-new-email");
      if (btnAdd && newEmail) {
        btnAdd.onclick = async () => {
          const email = newEmail.value.trim();
          if (!email) return;
          try {
            await postJSON("api/admin/users", { email });
            newEmail.value = "";
            loadAdmin();
          } catch(e) { alert(e.message); }
        };
      }
    } catch (e) { console.warn("Admin load error", e); }
  }

  async function loadLLMForm() {
    try {
      const me = await getJSON("api/me");
      if (me.source !== "oauth") return;

      const form = $("cabinet-llm-form");
      if (form) form.style.display = "block";

      // Привязка кнопки «Загрузить модели» (v3.5.9)
      const btnLoadModels = $("btn-load-models");
      if (btnLoadModels) btnLoadModels.onclick = () => loadCustomModels();

      // Загружаем: сохранённые ключи + текущую цепочку
      let conf = {};
      try { conf = await getJSON("api/me/llm") || {}; } catch (e) { console.warn("me/llm", e); }

      let cascade = { chain: [], active: null, admin_providers: [] };
      try { cascade = await getJSON("api/me/llm/cascade") || cascade; } catch (e) { console.warn("me/llm/cascade", e); }

      // Логика удаления ключей (v3.6.5)
      const btnClearOrca = $("btn-clear-orca");
      if (btnClearOrca) {
        btnClearOrca.style.display = conf.orcarouter_api_key_set ? "inline-block" : "none";
        btnClearOrca.onclick = async () => {
          if (!confirm("Удалить ключ OrcaRouter?")) return;
          try { await postJSON("api/me/llm", { orcarouter_api_key: "" }); loadLLMForm(); } catch(e) { alert(e.message); }
        };
      }

      const btnClearExt = $("btn-clear-ext");
      if (btnClearExt) {
        btnClearExt.style.display = (conf.external_llm_url || conf.external_llm_key_set) ? "inline-block" : "none";
        btnClearExt.onclick = async () => {
          if (!confirm("Удалить настройки Custom AI?")) return;
          try { await postJSON("api/me/llm", { external_llm_url: "", external_llm_key: "" }); loadLLMForm(); } catch(e) { alert(e.message); }
        };
      }

      const btnClearGemini = $("btn-clear-gemini");
      if (btnClearGemini) {
        btnClearGemini.style.display = conf.gemini_api_key_set ? "inline-block" : "none";
        btnClearGemini.onclick = async () => {
          if (!confirm("Удалить ключ Gemini?")) return;
          try { await postJSON("api/me/llm", { gemini_api_key: "" }); loadLLMForm(); } catch(e) { alert(e.message); }
        };
      }


      // ------- OrcaRouter -------
      const orcaInput = $("user-orca-key");
      const orcaBadge = $("orca-badge");
      const orcaStatus = $("orca-status");
      if (conf.orcarouter_api_key_set) {
        orcaInput.placeholder = "•••••••• (сохранён)";
        orcaBadge.innerHTML = "🟢 сохранён";
        orcaBadge.style.color = "var(--success)";
        orcaStatus.innerHTML = "🟢 активен";
        orcaStatus.style.color = "var(--success)";
      } else {
        orcaInput.placeholder = "sk-orca-...";
        orcaBadge.innerHTML = "";
        orcaStatus.innerHTML = "⚪ не задан";
        orcaStatus.style.color = "var(--text-muted)";
      }

      // ------- Custom AI -------
      const extUrl = $("user-ext-url");
      const extKey = $("user-ext-key");
      const extModel = $("user-ext-model");
      const customBadge = $("custom-badge");
      const customStatus = $("custom-status");
      if (conf.external_llm_url) extUrl.value = conf.external_llm_url;
      if (conf.external_llm_model) extModel.value = conf.external_llm_model;
      if (conf.external_llm_key_set) {
        extKey.placeholder = "•••••••• (сохранён)";
        customBadge.innerHTML = "🟢 сохранён";
        customBadge.style.color = "var(--success)";
        customStatus.innerHTML = "🟢 активен";
        customStatus.style.color = "var(--success)";
      } else {
        extKey.placeholder = "sk-...";
        customBadge.innerHTML = "";
        customStatus.innerHTML = "⚪ не задан";
        customStatus.style.color = "var(--text-muted)";
      }

      // ------- Gemini -------
      const gemInput = $("user-gemini-key");
      const gemBadge = $("gemini-badge");
      const gemStatus = $("gemini-status");
      if (conf.gemini_api_key_set) {
        gemInput.placeholder = "•••••••• (сохранён)";
        gemBadge.innerHTML = "🟢 сохранён";
        gemBadge.style.color = "var(--success)";
        gemStatus.innerHTML = "🟢 активен";
        gemStatus.style.color = "var(--success)";
      } else {
        gemInput.placeholder = "AIzaSy...";
        gemBadge.innerHTML = "🟡 без ключа — 5 RPD на admin-ключе";
        gemBadge.style.color = "#f5a623";
        gemStatus.innerHTML = "⚪ не задан (5 RPD)";
        gemStatus.style.color = "var(--text-muted)";
      }

      // ------- Сейчас используется -------
      const activeEl = $("llm-active");
      if (activeEl) {
        activeEl.textContent = cascade.active || "нет доступных провайдеров";
        activeEl.style.fontWeight = "600";
      }

      // ------- Admin-резервные (только если пришли) -------
      const adminBlock = $("llm-admin-block");
      const adminList = $("llm-admin-list");
      if (adminBlock && adminList) {
        const aps = cascade.admin_providers || [];
        if (aps.length) {
          adminBlock.style.display = "block";
          adminList.innerHTML = aps.map(p => {
            const label = p.name === "gemini" ? "✨ Gemini" : p.name === "hermes" ? "🔧 Hermes" : p.name;
            const status = p.available
              ? '<span style="color:var(--success);">🟢 настроен</span>'
              : '<span style="color:var(--text-muted);">🔴 не настроен</span>';
            const model = p.model ? `<span style="color:var(--text-muted); margin-left:6px;">${escHtml(p.model)}</span>` : "";
            return `<div style="display:flex; justify-content:space-between; padding:3px 0;">${label}${model}${status}</div>`;
          }).join("");
        } else {
          adminBlock.style.display = "none";
        }
      }

      // ------- Save -------
      const btn = $("btn-save-llm");
      const status = $("llm-save-status");
      btn.onclick = async () => {
        btn.disabled = true;
        if (status) { status.innerHTML = "⏳ Сохранение..."; status.style.color = "var(--text-muted)"; }

        const orcaKey = orcaInput.value.trim();
        const extUrlVal = extUrl.value.trim();
        const extKeyVal = extKey.value.trim();
        const extModelVal = extModel.value.trim();
        const gemKey = gemInput.value.trim();

        // Валидируем новые ключи перед сохранением
        if (orcaKey) {
          orcaBadge.innerHTML = "⏳ проверка…";
          orcaBadge.style.color = "var(--text-muted)";
          try {
            await postJSON("api/me/llm/validate/orcarouter", { key: orcaKey });
          } catch (err) {
            orcaBadge.innerHTML = "🔴 " + err.message;
            orcaBadge.style.color = "var(--danger)";
            btn.disabled = false;
            return;
          }
        }
        if (extUrlVal && extKeyVal) {
          customBadge.innerHTML = "⏳ проверка…";
          customBadge.style.color = "var(--text-muted)";
          try {
            await postJSON("api/me/llm/validate/custom", {
              url: extUrlVal,
              key: extKeyVal,
              model: extModelVal || "gpt-4o-mini",
            });
          } catch (err) {
            customBadge.innerHTML = "🔴 " + err.message;
            customBadge.style.color = "var(--danger)";
            btn.disabled = false;
            return;
          }
        }
        if (gemKey) {
          gemBadge.innerHTML = "⏳ проверка…";
          gemBadge.style.color = "var(--text-muted)";
          try {
            await postJSON("api/me/llm/validate", { key: gemKey });
          } catch (err) {
            gemBadge.innerHTML = "🔴 " + err.message;
            gemBadge.style.color = "var(--danger)";
            btn.disabled = false;
            return;
          }
        }

        const payload = { preferred_provider: "auto" };
        if (orcaKey) payload.orcarouter_api_key = orcaKey;
        if (extUrlVal) payload.external_llm_url = extUrlVal;
        if (extKeyVal) payload.external_llm_key = extKeyVal;
        if (extModelVal) payload.external_llm_model = extModelVal;
        if (gemKey) payload.gemini_api_key = gemKey;

        try {
          await postJSON("api/me/llm", payload);
          if (status) { status.innerHTML = "✅ Сохранено!"; status.style.color = "var(--success)"; }

          if (orcaKey) {
            orcaInput.value = "";
            orcaInput.placeholder = "•••••••• (сохранён)";
            orcaBadge.innerHTML = "🟢 сохранён";
            orcaBadge.style.color = "var(--success)";
            orcaStatus.innerHTML = "🟢 активен";
            orcaStatus.style.color = "var(--success)";
          }
          if (extKeyVal) {
            extKey.value = "";
            extKey.placeholder = "•••••••• (сохранён)";
            customBadge.innerHTML = "🟢 сохранён";
            customBadge.style.color = "var(--success)";
            customStatus.innerHTML = "🟢 активен";
            customStatus.style.color = "var(--success)";
          }
          if (gemKey) {
            gemInput.value = "";
            gemInput.placeholder = "•••••••• (сохранён)";
            gemBadge.innerHTML = "🟢 сохранён";
            gemBadge.style.color = "var(--success)";
            gemStatus.innerHTML = "🟢 активен";
            gemStatus.style.color = "var(--success)";
          }

          // Перечитываем активную цепочку
          try {
            const fresh = await getJSON("api/me/llm/cascade");
            if (fresh && fresh.active) {
              activeEl.textContent = fresh.active;
            }
          } catch (_) {}

          setTimeout(() => {
            if (status && status.innerHTML === "✅ Сохранено!") status.innerHTML = "";
          }, 3000);
        } catch (e) {
          if (status) { status.innerHTML = "❌ " + e.message; status.style.color = "var(--danger)"; }
        } finally {
          btn.disabled = false;
        }
      };
    } catch (e) { console.warn("LLM form error", e); }
  }


  async function loadVersion() {
    try {
      const data = await getJSON("api/generator/status");
      if (data.version) {
        const el = $("cabinet-version");
        if (el) el.textContent = data.version;
      }
    } catch (_) {}
  }

  async function deleteUser(email) {
    if (!confirm("Удалить пользователя?")) return;
    try {
      await del(`api/admin/users/${encodeURIComponent(email)}`);
      loadAdmin();
    } catch (e) { alert(e.message); }
  }

  async function loadPendingWeights() {
    try {
      const data = await RM.api.getJSON("api/me/weights/pending");
      const box = document.getElementById("cabinet-weights");
      if (!box) return;
      const product = String(data.product || "").trim();
      if (!product || data.reason !== "ok") { box.style.display = "none"; return; }
      box.style.display = "block";
      const unit = String(data.unit || "шт").trim();
      document.getElementById("weights-question").textContent = `Сколько грамм в 1 ${unit}: ${product}?`;
      document.getElementById("weights-input").value = "";
      document.getElementById("weights-save").onclick = async () => {
        const val = document.getElementById("weights-input").value;
        if (!val || parseFloat(val) <= 0) return;
        const btn = document.getElementById("weights-save");
        btn.disabled = true;
        try {
          await RM.api.postJSON("api/me/weights", { name: data.product, weight: val });
          loadPendingWeights();
        } catch (e) { alert("Ошибка: " + e.message); }
        finally { btn.disabled = false; }
      };
      document.getElementById("weights-skip").onclick = () => { box.style.display = "none"; };
    } catch (e) { console.error("[weights] error:", e); }
  }

  async function openWeightsAdmin() {
    const modal = document.getElementById("weights-admin-modal");
    if (!modal) return;
    const list = document.getElementById("weights-admin-list");
    list.innerHTML = '<div class="loading"><span class="spinner"></span> Загрузка…</div>';
    modal.classList.add("show");
    try {
      const data = await RM.api.getJSON("api/admin/piece_weights");
      const entries = Object.entries(data.weights || {}).sort((a, b) => a[0].localeCompare(b[0]));
      if (!entries.length) {
        list.innerHTML = '<p style="color:var(--text-muted)">Нет записей</p>';
      } else {
        list.innerHTML = entries.map(([name, weight]) => `
          <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid var(--border);">
            <span>${escHtml(name)}</span>
            <span style="display:flex; gap:8px; align-items:center;">
              <input type="number" value="${weight}" style="width:80px; padding:4px; border-radius:4px; border:1px solid var(--border); background:var(--surface); color:var(--text);" data-name="${escHtml(name)}">
              <button class="btn" data-del="${escHtml(name)}" style="color:var(--danger); padding:2px 8px; font-size:12px;">×</button>
            </span>
          </div>
        `).join("");
        list.querySelectorAll("input[data-name]").forEach(inp => {
          inp.onchange = async () => {
            try { await RM.api.postJSON("api/admin/piece_weights", { name: inp.dataset.name, weight: parseFloat(inp.value) }); }
            catch (e) { alert(e.message); }
          };
        });
        list.querySelectorAll("button[data-del]").forEach(btn => {
          btn.onclick = async () => {
            if (!confirm("Удалить переопределение?")) return;
            try {
              await RM.api.del(`api/admin/piece_weights/${encodeURIComponent(btn.dataset.del)}`);
              openWeightsAdmin();
            } catch (e) { alert(e.message); }
          };
        });
      }
    } catch (e) {
      list.innerHTML = `<p style="color:var(--danger)">Ошибка: ${escHtml(e.message)}</p>`;
    }
    const closeBtn = document.getElementById("weights-admin-close");
    if (closeBtn) closeBtn.onclick = () => modal.classList.remove("show");
    modal.onclick = (e) => { if (e.target === modal) modal.classList.remove("show"); };
    const addBtn = document.getElementById("weights-admin-add");
    if (addBtn && !addBtn.dataset.bound) {
      addBtn.dataset.bound = "1";
      addBtn.onclick = async () => {
        const name = document.getElementById("weights-admin-new-name").value.trim();
        const weight = parseFloat(document.getElementById("weights-admin-new-weight").value);
        if (!name || !weight) return;
        try {
          await RM.api.postJSON("api/admin/piece_weights", { name, weight });
          document.getElementById("weights-admin-new-name").value = "";
          document.getElementById("weights-admin-new-weight").value = "";
          openWeightsAdmin();
        } catch (e) { alert(e.message); }
      };
    }
  }

  async function loadCustomModels() {
    const url = $("user-ext-url").value.trim();
    const key = $("user-ext-key").value.trim();
    const status = $("custom-models-status");
    const btn = $("btn-load-models");
    const input = $("user-ext-model");
    const select = $("user-ext-model-select");

    if (!url || !key) {
      if (status) {
        status.innerHTML = "⚠ Введите URL и API Key";
        status.style.color = "#f5a623";
      }
      return;
    }

    if (btn) btn.disabled = true;
    if (status) {
      status.innerHTML = "⏳ Загрузка моделей...";
      status.style.color = "var(--text-muted)";
    }

    try {
      const data = await postJSON("api/me/llm/custom/models", { url, key });
      const models = data.models || [];
      if (!models.length) {
        if (status) {
          status.innerHTML = "⚠ " + (data.error || "Список моделей пуст");
          status.style.color = "#f5a623";
        }
        return;
      }

      select.innerHTML = '<option value="">— ввести вручную —</option>'
        + models.map(m => `<option value="${escHtml(m)}">${escHtml(m)}</option>`).join("");

      const current = input.value.trim();
      if (current && models.includes(current)) {
        select.value = current;
      }

      input.style.display = "none";
      select.style.display = "block";

      select.onchange = () => {
        if (select.value === "") {
          input.style.display = "block";
          select.style.display = "none";
          input.focus();
        } else {
          input.value = select.value;
        }
      };

      if (status) {
        status.innerHTML = `✓ ${models.length} моделей на endpoint`;
        status.style.color = "var(--success)";
      }
    } catch (e) {
      if (status) {
        status.innerHTML = "✗ " + e.message;
        status.style.color = "var(--danger)";
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // --- Журнал действий ------------------------------------------------
  const AUDIT_PAGE = 100;
  let auditOffset = 0;
  const auditCache = new Map();
  let auditBound = false;
  let auditActionsLoaded = false;
  let auditTimer = null;

  function auditTime(value) {
    if (!value) return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleString("ru-RU");
  }

  function auditDuration(ms) {
    if (ms === null || ms === undefined) return "";
    if (Number(ms) < 1000) return `${ms} мс`;
    return `${(Number(ms) / 1000).toFixed(1)} с`;
  }

  function auditStatus(status) {
    const map = {
      ok: ["OK", "#16a34a"],
      error: ["Ошибка", "var(--danger)"],
      running: ["Выполняется", "#f5a623"],
      denied: ["Запрещено", "var(--text-muted)"]
    };
    const [label, color] = map[status] || [status || "—", "var(--text-muted)"];
    return `<span style="display:inline-block;padding:2px 7px;border-radius:999px;background:${color};color:#fff;font-size:11px;font-weight:600;white-space:nowrap;">${escHtml(label)}</span>`;
  }

  function auditActor(e) {
    const name = e.actor_name || e.actor_email || e.actor_id || "—";
    const parts = [];
    if (e.actor_email && e.actor_email !== name) parts.push(e.actor_email);
    if (e.actor_role) parts.push(e.actor_role);
    if (e.actor_kind === "automation") parts.push("автоматизация");
    return `<div>${escHtml(name)}</div>` +
      (parts.length ? `<div style="font-size:11px;color:var(--text-muted)">${escHtml(parts.join(" · "))}</div>` : "");
  }

  function auditTarget(e) {
    const name = e.target_name || e.target_id || "—";
    const sub = e.target_type
      ? `${e.target_type}${e.target_id && e.target_name ? " · " + e.target_id : ""}`
      : "";
    return `<div>${escHtml(name)}</div>` +
      (sub ? `<div style="font-size:11px;color:var(--text-muted)">${escHtml(sub)}</div>` : "");
  }

  function auditRow(e) {
    const details = `<button class="btn audit-details-btn" data-audit-id="${escHtml(e.id)}">Детали</button>`;
    const dur = auditDuration(e.duration_ms);
    const shortId = (e.id || "").slice(0, 8);
    const triedModels = (e.details && Array.isArray(e.details.models_tried))
      ? e.details.models_tried.map((item) => item && item.model).filter(Boolean)
      : [];
    const errorMeta = [
      e.error_code,
      e.error_provider,
      ...(triedModels.length ? triedModels : [e.error_model])
    ].filter(Boolean).join(" · ");
    return `<tr class="audit-row">
      <td data-label="Время" class="audit-time">${escHtml(auditTime(e.created_at))}<div title="${escHtml(e.id || "")}" class="audit-id">${escHtml(shortId)}…</div></td>
      <td data-label="Кто" class="audit-actor">${auditActor(e)}</td>
      <td data-label="Действие" class="audit-action">${escHtml(e.action_label || e.action || "—")}<div class="audit-sub">${escHtml(e.action || "")}</div></td>
      <td data-label="Объект" class="audit-target">${auditTarget(e)}</td>
      <td data-label="Статус" class="audit-status-cell">${auditStatus(e.status)}${dur ? `<div class="audit-sub">${escHtml(dur)}</div>` : ""}</td>
      <td data-label="Ошибка / детали" class="audit-error-cell">${e.error ? `<div class="audit-error">${escHtml(e.error)}</div>` : ""}${errorMeta ? `<div class="audit-error-meta">${escHtml(errorMeta)}</div>` : ""}${details}</td>
    </tr>`;
  }

  function jsonHtml(value, indent = 0) {
    const pad = "  ".repeat(indent);
    const padInner = "  ".repeat(indent + 1);
    if (value === null || value === undefined) return '<span class="json-null">null</span>';
    if (typeof value === "string") return `<span class="json-string">${escHtml(JSON.stringify(value))}</span>`;
    if (typeof value === "number") return `<span class="json-number">${escHtml(String(value))}</span>`;
    if (typeof value === "boolean") return `<span class="json-bool">${value}</span>`;
    if (Array.isArray(value)) {
      if (!value.length) return "[]";
      return "[\n" + value.map((item) => padInner + jsonHtml(item, indent + 1)).join(",\n") + "\n" + pad + "]";
    }
    if (typeof value === "object") {
      const keys = Object.keys(value);
      if (!keys.length) return "{}";
      return "{\n" + keys.map((key) =>
        padInner + `<span class="json-key">${escHtml(JSON.stringify(key))}</span>: ` + jsonHtml(value[key], indent + 1)
      ).join(",\n") + "\n" + pad + "}";
    }
    return escHtml(String(value));
  }

  async function copyAuditId(value, button) {
    const text = String(value || "");
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const area = document.createElement("textarea");
        area.value = text;
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }
      if (button) {
        const label = button.textContent;
        button.textContent = "Скопировано";
        setTimeout(() => { button.textContent = label; }, 1500);
      }
    } catch (e) {
      if (button) button.textContent = "Не удалось";
    }
  }

  function openAuditModal(eventId) {
    const e = auditCache.get(eventId);
    if (!e) return;
    const payload = {
      id: e.id,
      time: e.created_at,
      actor: {
        kind: e.actor_kind,
        id: e.actor_id,
        name: e.actor_name,
        email: e.actor_email,
        role: e.actor_role
      },
      action: { code: e.action, label: e.action_label },
      target: { type: e.target_type, id: e.target_id, name: e.target_name },
      status: e.status,
      http_status: e.http_status,
      duration_ms: e.duration_ms,
      method: e.method,
      path: e.path,
      ip: e.ip,
      user_agent: e.user_agent,
      error: e.error,
      error_code: e.error_code,
      error_provider: e.error_provider,
      error_model: e.error_model,
      details: e.details,
      correlation_id: e.correlation_id
    };
    const meta = $("audit-modal-meta");
    if (meta) {
      meta.innerHTML = `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px;">
        <span style="font-size:12px;color:var(--text-muted)">ID события:</span>
        <code style="font-size:12px;word-break:break-all;">${escHtml(e.id)}</code>
        <button class="btn" id="audit-modal-copy" style="padding:4px 8px;font-size:11px;">Копировать</button>
      </div>`;
      const copy = $("audit-modal-copy");
      if (copy) copy.onclick = () => copyAuditId(e.id, copy);
    }
    const body = $("audit-modal-body");
    if (body) body.innerHTML = `<div class="audit-json">${jsonHtml(payload)}</div>`;
    const modal = $("audit-modal");
    if (modal) modal.classList.add("show");
  }

  function closeAuditModal() {
    const modal = $("audit-modal");
    if (modal) modal.classList.remove("show");
  }

  function auditTable(items) {
    if (!items.length) return `<div class="hint">Событий нет.</div>`;
    return `<div class="audit-table-wrap">
      <table class="audit-table">
        <thead><tr>
          <th>Время</th><th>Кто</th><th>Действие</th><th>Объект</th><th>Статус</th><th>Ошибка / детали</th>
        </tr></thead>
        <tbody>${items.map(auditRow).join("")}</tbody>
      </table>
    </div>`;
  }

  async function loadAuditActions() {
    const sel = $("audit-action");
    if (!sel) return;
    try {
      const data = await getJSON("api/admin/audit/actions");
      const items = data.items || [];
      sel.innerHTML = '<option value="">Все</option>' + items.map(
        (item) => `<option value="${escHtml(item.action)}">${escHtml(item.label || item.action)}</option>`
      ).join("");
      auditActionsLoaded = true;
    } catch (e) {
      console.error("audit actions", e);
    }
  }

  function bindAuditControls() {
    if (auditBound) return;
    auditBound = true;
    const q = $("audit-q");
    if (q) q.oninput = () => {
      clearTimeout(auditTimer);
      auditTimer = setTimeout(() => loadAudit(true), 350);
    };
    const status = $("audit-status");
    if (status) status.onchange = () => loadAudit(true);
    const action = $("audit-action");
    if (action) action.onchange = () => loadAudit(true);
    const refresh = $("audit-refresh");
    if (refresh) refresh.onclick = () => loadAudit(true);
    const more = $("audit-more");
    if (more) more.onclick = () => loadAudit(false);
    const list = $("audit-list");
    if (list) list.onclick = (event) => {
      const btn = event.target.closest("[data-audit-id]");
      if (btn) openAuditModal(btn.dataset.auditId);
    };
    const close = $("audit-modal-close");
    if (close) close.onclick = closeAuditModal;
    const modal = $("audit-modal");
    if (modal) modal.onclick = (event) => {
      if (event.target === modal) closeAuditModal();
    };
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeAuditModal();
    });
  }

  async function loadAuditStats() {
    const el = $("audit-stats");
    if (!el) return;
    try {
      const data = await getJSON("api/admin/audit/stats");
      const total = Number(data.total_errors || 0);
      if (!total) {
        el.style.display = "none";
        return;
      }
      const models = (data.by_model || []).slice(0, 3).map((item) => {
        const provider = item.provider ? ` (${item.provider})` : "";
        return `${item.model}${provider} — ${item.count}`;
      }).join(" · ");
      el.innerHTML = `<b>Всего ошибок:</b> ${total}` + (models ? ` · по моделям: ${escHtml(models)}` : "");
      el.style.display = "block";
    } catch (e) {
      el.style.display = "none";
    }
  }

  async function loadAudit(reset = true) {
    const card = $("cabinet-audit");
    if (!card) return;
    let me = RM.state.user;
    if (!me) {
      try { me = await getJSON("api/me"); RM.state.user = me; } catch (e) { return; }
    }
    if (!me || me.role !== "admin") {
      card.style.display = "none";
      return;
    }
    card.style.display = "block";
    bindAuditControls();
    if (!auditActionsLoaded) await loadAuditActions();

    if (reset) auditOffset = 0;
    const params = new URLSearchParams({
      limit: String(AUDIT_PAGE),
      offset: String(auditOffset)
    });
    const q = $("audit-q")?.value.trim();
    const status = $("audit-status")?.value;
    const action = $("audit-action")?.value;
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    if (action) params.set("action", action);

    const summary = $("audit-summary");
    const more = $("audit-more");
    try {
      const data = await getJSON("api/admin/audit?" + params.toString());
      const items = data.items || [];
      const total = Number(data.total || 0);
      items.forEach((item) => auditCache.set(item.id, item));
      if (reset) {
        const list = $("audit-list");
        if (list) list.innerHTML = auditTable(items);
      } else if (items.length) {
        const tbody = $("audit-list")?.querySelector("tbody");
        if (tbody) tbody.insertAdjacentHTML("beforeend", items.map(auditRow).join(""));
      }
      auditOffset += items.length;
      if (summary) {
        summary.textContent = `Показано ${auditOffset} из ${total} · ${new Date().toLocaleTimeString("ru-RU")}`;
        summary.style.color = "var(--text-muted)";
      }
      if (more) more.style.display = auditOffset < total ? "block" : "none";
      if (reset) await loadAuditStats();
    } catch (e) {
      if (summary) {
        summary.textContent = "Ошибка загрузки журнала: " + e.message;
        summary.style.color = "var(--danger)";
      }
    }
  }

  RM.cabinet = { setup, load, deleteUser, loadAudit };
})(window.RM);
