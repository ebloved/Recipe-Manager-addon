"use strict";
(function (RM) {
  const { $, escHtml } = RM.utils;
  const { getJSON } = RM.api;

  function setup() {
    // Синхронизация управляется своим модулем
    if (RM.sync) RM.sync.setup();
    
    // Принудительный вызов загрузки при клике на вкладку (в обход tabs.js)
    const cabTab = document.querySelector('.cabinet-tab');
    if (cabTab) {
      cabTab.addEventListener('click', () => {
        load();
      });
    }
  }

  async function load() {
    loadUser();
    loadLLM();
    loadSettings();
    if (RM.sync) RM.sync.load();
    loadVersion();
  }

  async function loadUser() {
    const box = $("cabinet-user");
    try {
      const data = await getJSON("api/me");
      box.innerHTML = `
        <div class="hint">
          <div style="font-size:16px; font-weight:600; margin-bottom:4px">
            👤 ${escHtml(data.name)}
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
      const data = await RM.api.getJSON("api/settings");
      const chk = $("setting-auto-time");
      if (chk) {
        chk.checked = !!data.generator_auto_active_time;
        chk.addEventListener("change", async (e) => {
          try {
            await RM.api.postJSON("api/settings", {
              generator_auto_active_time: e.target.checked
            });
          } catch (err) {
            alert("Ошибка сохранения: " + err.message);
            e.target.checked = !e.target.checked;
          }
        });
      }
    } catch (e) { console.warn("Settings load error:", e); }
  }
  async function loadVersion() {
    try {
      const data = await getJSON("api/generator/status");
      if (data.version) {
        $("cabinet-version").textContent = data.version;
      }
    } catch (_) {}
  }

  RM.cabinet = { setup, load };
})(window.RM);
