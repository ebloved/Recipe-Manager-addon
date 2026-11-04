"use strict";
(function () {
  const btn = document.getElementById("copy-link");
  const input = document.getElementById("share-url");
  if (!btn || !input) return;

  async function copy() {
    const text = input.value || window.location.href;
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      input.focus();
      input.select();
      try { document.execCommand("copy"); } catch (_) { /* ignore */ }
    }
    const old = btn.textContent;
    btn.textContent = "Скопировано";
    setTimeout(() => { btn.textContent = old; }, 2000);
  }

  btn.addEventListener("click", copy);
})();
