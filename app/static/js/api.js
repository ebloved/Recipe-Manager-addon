"use strict";
(function (RM) {
  const BASE = window.location.pathname.replace(/\/+$/, "") + "/";
  const api = (p) => BASE + p.replace(/^\/+/, "");

  async function getJSON(url) {
    const resp = await fetch(api(url));
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || JSON.stringify(data));
    return data;
  }

  async function postJSON(url, payload) {
    const resp = await fetch(api(url), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || JSON.stringify(data));
    return data;
  }

  async function postForm(url, formData) {
    const resp = await fetch(api(url), { method: "POST", body: formData });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail?.error || data.detail || data.error || JSON.stringify(data));
    return data;
  }

  async function patchJSON(url, payload) {
    const resp = await fetch(api(url), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || JSON.stringify(data));
    return data;
  }

  async function del(url) {
    const resp = await fetch(api(url), { method: "DELETE" });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || JSON.stringify(data));
    return data;
  }

  RM.api = { BASE, api, getJSON, postJSON, postForm, patchJSON, del };
})(window.RM);