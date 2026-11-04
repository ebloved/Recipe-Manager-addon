"use strict";
(function (RM) {
  let hasPending = false;
  let trackedJobIds = new Set();

  function setup() {
    setInterval(checkJobs, 4000);
  }

  async function checkJobs() {
    try {
      const data = await RM.api.getJSON("api/generator/jobs?status=pending");
      const pending = data.jobs || [];
      const indicator = document.getElementById("global-job-indicator");

      if (pending.length > 0) {
        hasPending = true;
        pending.forEach(j => trackedJobIds.add(j.id));
        if (indicator) {
          indicator.style.display = "flex";
          indicator.style.color = "var(--text-secondary)";
          indicator.innerHTML = `<span class="spinner"></span> В процессе (${pending.length})`;
        }
      } else {
        if (hasPending) {
          hasPending = false;
          trackedJobIds.clear();
          
          if (indicator) {
            indicator.style.display = "flex";
            indicator.style.color = "var(--success)";
            indicator.innerHTML = "\u2705 Готово"; // Unicode checkmark
            setTimeout(() => { indicator.style.display = "none"; }, 3000);
          }
          if (RM.recipes) RM.recipes.load();
        }
      }
    } catch (e) { console.warn("Jobs poll error", e); }
  }

  RM.jobs = { setup };
})(window.RM);
