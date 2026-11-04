"use strict";
(function (RM) {
  const { $, setStatus } = RM.utils;
  const { getJSON, postJSON } = RM.api;
  const state = RM.state;
  let pollTimer = null;
  let pending = null;

  async function setup() {
    const box = $("cabinet-remote");
    if (!box) return;
    const btnConnect = $("remote-connect");
    const btnDisconnect = $("remote-disconnect");
    const btnSync = $("remote-sync");
    if (btnConnect) btnConnect.addEventListener("click", connect);
    if (btnDisconnect) btnDisconnect.addEventListener("click", disconnect);
    if (btnSync) btnSync.addEventListener("click", syncNow);
    await load();
    setInterval(load, 15000);
  }

  async function load() {
    const box = $("cabinet-remote");
    const status = $("remote-status");
    if (!box || !status) return;
    try {
      const data = await getJSON("api/remote/status");
      if (!data.remote_mode) {
        box.style.display = "none";
        return;
      }
      box.style.display = "block";
      state.remoteServerUrl = data.server_url || "";
      const url = $("remote-server-url");
      if (url && !url.value) url.value = data.server_url || "";
      if (data.paired) {
        const pending = Number(data.pending_creates || 0) + Number(data.pending_shopping || 0);
        const synced = data.last_sync ? new Date(data.last_sync).toLocaleString("ru-RU") : "—";
        setStatus(status, `✓ Подключено к ${data.server_url}. Кэш: ${synced}`, "success");
        const banner = $("remote-banner");
        if (banner) {
          if (!data.online) {
            banner.style.display = "block";
            banner.textContent = "Сервер недоступен — работаем из локального кэша.";
          } else if (pending > 0) {
            banner.style.display = "block";
            banner.textContent = `Офлайн-изменения ожидают отправки: ${pending}. Нажмите «Обновить кэш».`;
          } else {
            banner.style.display = "none";
          }
        }
      } else {
        setStatus(status, "Сервер не подключён.", "info");
        const banner = $("remote-banner");
        if (banner) banner.style.display = "none";
      }
    } catch (e) {
      box.style.display = "none";
    }
  }

  async function connect() {
    const url = ($("remote-server-url") && $("remote-server-url").value || "").trim();
    const status = $("remote-status");
    if (!url) {
      setStatus(status, "Укажите адрес сервера.", "error");
      return;
    }
    const btn = $("remote-connect");
    if (btn) btn.disabled = true;
    try {
      const data = await postJSON("api/remote/pair/init", { server_url: url });
      pending = { server_url: url, device_code: data.device_code };
      $("remote-pair-box").style.display = "block";
      $("remote-user-code").textContent = data.user_code || "";
      const link = $("remote-verify-link");
      if (link) link.href = (data.verification_url || (url + "/device")) + "?code=" + encodeURIComponent(data.user_code || "");
      setStatus(status, "Введите код на странице подтверждения…", "info");
      startPolling();
    } catch (e) {
      setStatus(status, "Ошибка: " + e.message, "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      if (!pending) return;
      try {
        const data = await postJSON("api/remote/pair/poll", pending);
        if (data.status === "approved") {
          clearInterval(pollTimer);
          pollTimer = null;
          setStatus($("remote-status"), "✓ Подключено. Перезагрузка…", "success");
          setTimeout(() => window.location.reload(), 800);
        } else if (data.status === "expired" || data.status === "denied") {
          clearInterval(pollTimer);
          pollTimer = null;
          setStatus($("remote-status"), "Код истёк. Попробуйте снова.", "error");
        }
      } catch (e) {
        // временная ошибка сети — продолжаем polling
      }
    }, 5000);
  }

  async function syncNow() {
    const status = $("remote-status");
    const btn = $("remote-sync");
    if (btn) btn.disabled = true;
    setStatus(status, "Синхронизация…", "info");
    try {
      const data = await postJSON("api/remote/sync", {});
      if (data.status === "ok") {
        setStatus(status, `Синхронизировано: ${data.revision ?? "—"}`, "success");
      } else if (data.status === "offline") {
        setStatus(status, "Сервер недоступен — изменения остались в очереди.", "error");
      } else if (data.status === "partial") {
        setStatus(status, "Часть изменений не отправлена, повторите позже.", "error");
      } else {
        setStatus(status, `Синхронизация: ${data.status}`, "info");
      }
      await load();
    } catch (e) {
      setStatus(status, "Ошибка синхронизации: " + e.message, "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function disconnect() {
    if (!confirm("Отключить сервер? Локальные данные останутся.")) return;
    const banner = $("remote-banner");
    if (banner) banner.style.display = "none";
    try {
      await postJSON("api/remote/disconnect", {});
      await load();
    } catch (e) {
      setStatus($("remote-status"), "Ошибка: " + e.message, "error");
    }
  }

  RM.remote = { setup, load };
})(window.RM);
