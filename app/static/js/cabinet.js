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
    try { await loadLLM(); } catch (e) { console.error("loadLLM", e); }
    try { await loadSettings(); } catch (e) { console.error("loadSettings", e); }
    try { await loadAdmin(); } catch (e) { console.error("loadAdmin", e); }
    try { await loadLLMForm(); } catch (e) { console.error("loadLLMForm", e); }
    if (RM.sync) {
      try { await RM.sync.load(); } catch (e) { console.error("sync", e); }
    }
    try { await loadVersion(); } catch (e) { console.error("loadVersion", e); }
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

  async function loadLLM() {
    const box = $("cabinet-llm");
    if (!box) return;
    try {
      const data = await getJSON("api/generator/status");
      const p = data.providers || [];
      const items = p.map((prov) => `
        <div style="display:flex; justify-content:space-between; font-size:14px; margin-bottom:6px;">
          <span>${prov.name === 'hermes' ? '🤖 Hermes (OpenAI)' : '✨ Gemini'}</span>
          ${prov.available 
            ? '<span style="color:var(--success)">🟢 Доступен</span>' 
            : '<span style="color:var(--text-muted)">🔴 Недоступен</span>'}
        </div>`).join("");
      
      const active = data.active_provider ? `Активный: <b>${data.active_provider}</b>` : "Нет активного провайдера";
      
      box.innerHTML = `
        <div class="hint">
          <div style="font-size:14px; font-weight:600; margin-bottom:10px">Генерация рецептов</div>
          ${items}
          <div style="font-size:12px; color:var(--text-secondary); margin-top:8px">${active}</div>
        </div>`;
    } catch (err) {
      box.innerHTML = `<div class="hint" style="color:var(--danger)">Ошибка LLM: ${escHtml(err.message)}</div>`;
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
      
      // Загружаем текущий статус
      const conf = await getJSON("api/me/llm");
      const statusDiv = $("llm-save-status");
      const badge = $("llm-gemini-badge");
      const gKeyInput = $("user-gemini-key");
      const eUrlInput = $("user-ext-url");
      const eKeyInput = $("user-ext-key");
      
      if (conf.external_llm_url) eUrlInput.value = conf.external_llm_url;
      
      if (conf.gemini_api_key_set) {
        gKeyInput.placeholder = "•••••••• (сохранён)";
        if (badge) {
          badge.innerHTML = "🟢 Ваш ключ активен";
          badge.style.color = "var(--success)";
        }
      } else {
        gKeyInput.placeholder = "AIzaSy...";
        if (badge) {
          badge.innerHTML = "🟡 Встроенный ключ (лимит 5/день)";
          badge.style.color = "#f5a623";
        }
      }
      
      if (conf.external_llm_key_set) {
        eKeyInput.placeholder = "•••••••• (сохранён)";
      } else {
        eKeyInput.placeholder = "sk-...";
      }
      
      const btn = $("btn-save-llm");
      if (btn) {
        btn.onclick = async () => {
          btn.disabled = true;
          
          const gKey = gKeyInput.value.trim();
          const eKey = eKeyInput.value.trim();
          const eUrl = eUrlInput.value.trim();
          
          // Если введен новый Gemini ключ, сначала проверяем его
          if (gKey) {
            if (badge) {
              badge.innerHTML = "⏳ Проверка ключа...";
              badge.style.color = "var(--text-secondary)";
            }
            try {
              await postJSON("api/me/llm/validate", { key: gKey });
            } catch (err) {
              if (badge) {
                badge.innerHTML = "🔴 Ошибка: " + err.message;
                badge.style.color = "var(--danger)";
              }
              btn.disabled = false;
              return; // Прерываем сохранение, если ключ невалидный
            }
          }
          
          if (statusDiv) statusDiv.innerHTML = '⏳ Сохранение...';
          
          const payload = {
            external_llm_url: eUrl || null,
            preferred_provider: "auto"
          };
          
          if (gKey) payload.gemini_api_key = gKey;
          if (eKey) payload.external_llm_key = eKey;
          
          try {
            await postJSON("api/me/llm", payload);
            
            if (statusDiv) {
              statusDiv.innerHTML = '✅ Сохранено!';
              statusDiv.style.color = 'var(--success)';
            }
            
            // Если сохранили ключ, меняем бейдж на зеленый
            if (gKey || conf.gemini_api_key_set) {
              if (badge) {
                badge.innerHTML = "🟢 Ваш ключ активен";
                badge.style.color = "var(--success)";
              }
              gKeyInput.value = "";
              gKeyInput.placeholder = "•••••••• (сохранён)";
            }
            
            if (eKey) {
              eKeyInput.value = "";
              eKeyInput.placeholder = "•••••••• (сохранён)";
            }
            
            setTimeout(() => { if (statusDiv && statusDiv.innerHTML === '✅ Сохранено!') statusDiv.innerHTML = ''; }, 3000);
          } catch(e) {
            if (statusDiv) {
              statusDiv.innerHTML = '❌ Ошибка сохранения: ' + e.message;
              statusDiv.style.color = 'var(--danger)';
            }
          } finally {
            btn.disabled = false;
          }
        };
      }
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

  RM.cabinet = { setup, load, deleteUser };
})(window.RM);
