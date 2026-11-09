"use strict";
(function (RM) {
  const BASE = window.location.pathname.replace(/\/+$/, "") + "/";
  const api = (p) => BASE + p.replace(/^\/+/, "");

  function errorText(data, resp) {
    const detail = data && data.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const parts = detail.map((item) => {
        if (typeof item === "string") return item;
        if (item && (item.msg || item.message)) return item.msg || item.message;
        try { return JSON.stringify(item); } catch (_) { return String(item); }
      }).filter(Boolean);
      if (parts.length) return parts.join("; ");
    }
    if (detail && typeof detail === "object") {
      if (detail.message || detail.error) return detail.message || detail.error;
      try { return JSON.stringify(detail); } catch (_) { /* ignore */ }
    }
    if (data && (data.error || data.message)) return data.error || data.message;
    return `HTTP ${resp.status}`;
  }

  async function getJSON(url) {
    const resp = await fetch(api(url));
    const data = await resp.json().catch(() => ({}));
    if (resp.status === 401) { window.location.href = 'api/auth/login'; throw new Error('Unauthorized'); }
    if (!resp.ok) throw new Error(errorText(data, resp));
    return data;
  }

  async function postJSON(url, payload) {
    const resp = await fetch(api(url), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json().catch(() => ({}));
    if (resp.status === 401) { window.location.href = 'api/auth/login'; throw new Error('Unauthorized'); }
    if (!resp.ok) throw new Error(errorText(data, resp));
    return data;
  }

  async function postForm(url, formData) {
    const resp = await fetch(api(url), { method: "POST", body: formData });
    const data = await resp.json().catch(() => ({}));
    if (resp.status === 401) { window.location.href = 'api/auth/login'; throw new Error('Unauthorized'); }
    if (!resp.ok) throw new Error(errorText(data, resp));
    return data;
  }

  async function patchJSON(url, payload) {
    const resp = await fetch(api(url), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json().catch(() => ({}));
    if (resp.status === 401) { window.location.href = 'api/auth/login'; throw new Error('Unauthorized'); }
    if (!resp.ok) throw new Error(errorText(data, resp));
    return data;
  }

  async function del(url) {
    const resp = await fetch(api(url), { method: "DELETE" });
    const data = await resp.json().catch(() => ({}));
    if (resp.status === 401) { window.location.href = 'api/auth/login'; throw new Error('Unauthorized'); }
    if (!resp.ok) throw new Error(errorText(data, resp));
    return data;
  }

  RM.api = { BASE, api, getJSON, postJSON, postForm, patchJSON, del };
})(window.RM);