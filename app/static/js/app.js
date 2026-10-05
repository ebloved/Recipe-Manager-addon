"use strict";
(function (RM) {
  function init() {
    RM.tabs.setupTopTabs();
    RM.tabs.setupSubTabs();
    RM.youtube.setup();
    RM.imports.setup();
    RM.recipes.setup();
    RM.detail.setup();
    RM.planPicker.setup();
    RM.planner.setup();
    RM.recipePicker.setup();
    RM.shopping.setup();
    RM.sync.setup();
    RM.liveSync.setup();

    RM.recipes.load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window.RM);