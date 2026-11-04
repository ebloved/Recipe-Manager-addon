"use strict";
(function (RM) {
  const { $ } = RM.utils;

  function open() {
    const overlay = $("help-overlay");
    if (!overlay) return;
    overlay.classList.add("show");
    document.body.style.overflow = "hidden";
  }

  function close() {
    const overlay = $("help-overlay");
    if (!overlay) return;
    overlay.classList.remove("show");
    document.body.style.overflow = "";
  }

  function setup() {
    const btn = $("btn-cabinet-help");
    if (btn) btn.addEventListener("click", open);
    const closeBtn = $("help-close");
    if (closeBtn) closeBtn.addEventListener("click", close);
    const overlay = $("help-overlay");
    if (overlay) {
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) close();
      });
    }
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
    });
  }

  RM.help = { setup, open, close };
})(window.RM);
