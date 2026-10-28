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
  }

  async function load() {
    try { await loadUser(); } catch (e) { console.error("loadUser", e); }
    try { await loadSettings(); } catch (e) { console.error("loadSettings", e); }
    try { await loadAdmin(); } catch (e) { console.error("loadAdmin", e); }
    try { await loadLLMForm(); } catch (e) { console.error("loadLLMForm", e); }
    if (RM.sync) {
      try { await RM.sync.load(); } catch (e) { console.error("sync", e); }
    }
    try { await loadVersion(); } catch (e) { console.error("loadVersion", e); }
    try { await loadPendingWeights(); } catch (e) { console.error("loadPendingWeights", e); }
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
        </div>`;
    } catch (err) {
      box.innerHTML = `<div class="hint" style="color:var(--danger)">Ошибка: ${escHtml(err.message)}</div>`;
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

        const btnSys = $("btn-save-sys-settings");
        if (btnSys) {
          btnSys.onclick = async () => {
            btnSys.disabled = true;
            try {
              await postJSON("api/settings", {
                gemini_poll_duration: parseFloat($("setting-poll-duration").value),
                generator_max_tokens: parseInt($("setting-gen-tokens").value),
                adapter_max_tokens: parseInt($("setting-adapt-tokens").value)
              });
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
      if (me.role !== "admin") {
        const syncCard = $("cabinet-sync");
        if (syncCard) syncCard.style.display = "none";
        return;
      }

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
      if (!data.product) { box.style.display = "none"; return; }
      box.style.display = "block";
      document.getElementById("weights-question").textContent = `Сколько грамм в 1 шт: ${data.product}?`;
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

  RM.cabinet = { setup, load, deleteUser };
})(window.RM);
