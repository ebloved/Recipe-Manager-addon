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

  function openLlm() {
    close();
    const modal = $("llm-help-modal");
    if (!modal) return;
    modal.classList.add("show");
    document.body.style.overflow = "hidden";
  }

  function closeLlm() {
    const modal = $("llm-help-modal");
    if (!modal) return;
    modal.classList.remove("show");
    if (!$("help-overlay")?.classList.contains("show")) {
      document.body.style.overflow = "";
    }
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

    const llmBtn = $("btn-llm-help");
    if (llmBtn) llmBtn.addEventListener("click", openLlm);
    const helpLlmBtn = $("help-llm-open");
    if (helpLlmBtn) helpLlmBtn.addEventListener("click", openLlm);
    const llmClose = $("llm-help-close");
    if (llmClose) llmClose.addEventListener("click", closeLlm);
    const llmOk = $("llm-help-ok");
    if (llmOk) llmOk.addEventListener("click", closeLlm);
    const llmModal = $("llm-help-modal");
    if (llmModal) {
      llmModal.addEventListener("click", (e) => {
        if (e.target === llmModal) closeLlm();
      });
    }

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if ($("llm-help-modal")?.classList.contains("show")) closeLlm();
      else close();
    });
  }

  RM.help = { setup, open, close, openLlm, closeLlm };
})(window.RM);
