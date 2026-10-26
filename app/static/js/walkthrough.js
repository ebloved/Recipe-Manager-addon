"use strict";
(function (RM) {
  const { $ } = RM.utils;

  const mainSteps = [
    {
      target: ".tabs",
      title: "Навигация",
      text: "Здесь находятся основные разделы: рецепты, генератор, продукты, планировщик и покупки.",
      position: "bottom"
    },
    {
      target: ".search-row",
      title: "Поиск и сортировка",
      text: "Ищите рецепты по названию, ингредиентам или тегам. Справа можно выбрать сортировку (например, «Сначала быстрые»).",
      position: "bottom"
    },
    {
      target: ".profile-selector",
      title: "Профиль",
      text: "Выберите свой профиль (например, «Лёгкое» или «Высокий белок»). Рецепты будут фильтроваться под ваши цели.",
      position: "bottom-left"
    },
    {
      target: ".cabinet-tab",
      title: "Личный кабинет",
      text: "Здесь вы можете настроить свои API-ключи, управлять доступом друзей и повторить это обучение.",
      position: "bottom-left"
    }
  ];

  let currentStep = 0;
  let overlay, tooltip;


  const cabinetSteps = [
    {
      target: "#cabinet-user",
      title: "Ваш профиль",
      text: "Здесь отображается ваш аккаунт и источник входа.",
      position: "bottom"
    },
    {
      target: "#cabinet-llm-form",
      title: "Свои ключи LLM",
      text: "Без своего ключа доступно только 5 генераций в день (лимит сервера). Введите свой Gemini API Key (получить можно бесплатно на aistudio.google.com), чтобы генерировать без ограничений.",
      position: "bottom"
    },
    {
      target: "#cabinet-admin",
      title: "Управление доступом",
      text: "Здесь вы добавляете email друзей. Они смогут войти только если вы их добавите.",
      position: "bottom"
    },
    {
      target: "#cabinet-sync",
      title: "Синхронизация",
      text: "Резервное копирование ваших рецептов в GitHub.",
      position: "bottom"
    }
  ];

  function createUI() {
    if ($("walkthrough-overlay")) return;

    overlay = document.createElement("div");
    overlay.id = "walkthrough-overlay";
    overlay.className = "tour-overlay";
    overlay.style.display = "none";
    
    tooltip = document.createElement("div");
    tooltip.className = "tour-tooltip";
    tooltip.id = "walkthrough-tooltip";
    tooltip.style.display = "none";

    document.body.appendChild(overlay);
    document.body.appendChild(tooltip);
  }

  let activeSteps = mainSteps;

  function start(tourName = "main") {
    createUI();
    activeSteps = tourName === "cabinet" ? cabinetSteps : mainSteps;
    
    if (tourName === "cabinet") {
      RM.tabs.activateTab("cabinet");
      // Ждем, пока вкладка отрисуется
      setTimeout(() => {
        currentStep = 0;
        overlay.style.display = "block";
        showStep();
        window.addEventListener("resize", showStep);
      }, 300);
      return;
    }

    currentStep = 0;
    overlay.style.display = "block";
    showStep();
    
    // На мобилках скроллим к элементу
    window.addEventListener("resize", showStep);
  }

  function stop() {
    if (overlay) overlay.style.display = "none";
    if (tooltip) tooltip.style.display = "none";
    localStorage.setItem("rm_walkthrough_done", "true");
    window.removeEventListener("resize", showStep);
    
    // Снимаем выделение
    document.querySelectorAll(".tour-highlight").forEach(el => el.classList.remove("tour-highlight"));
  }

  function showStep() {
    if (currentStep >= activeSteps.length) {
      stop();
      return;
    }

    // Снимаем старое выделение
    document.querySelectorAll(".tour-highlight").forEach(el => el.classList.remove("tour-highlight"));

    const step = activeSteps[currentStep];
    const targetEl = document.querySelector(step.target);

    // Если элемента нет ИЛИ он скрыт (display: none), пропускаем шаг
    if (!targetEl || targetEl.offsetParent === null) {
      currentStep++;
      showStep();
      return;
    }

    targetEl.classList.add("tour-highlight");
    targetEl.scrollIntoView({ behavior: "smooth", block: "center" });

    setTimeout(() => {
      const rect = targetEl.getBoundingClientRect();
      tooltip.style.display = "block";
      
      let top = rect.bottom + 10;
      let left = rect.left;

      if (step.position === "bottom-left") {
        top = rect.bottom + 10;
        left = rect.right - 300; // прижимаем к правому краю
      }
      
      // Защита от вылета за экран
      if (left < 10) left = 10;
      if (left + 300 > window.innerWidth) left = window.innerWidth - 310;
      if (top + 150 > window.innerHeight) top = rect.top - 160; // показываем сверху, если не влезает

      tooltip.style.top = top + "px";
      tooltip.style.left = left + "px";
      tooltip.style.width = "280px";

      const isLast = currentStep === activeSteps.length - 1;
      
      tooltip.innerHTML = `
        <h4 style="margin-top:0; margin-bottom:8px; font-size:16px;">${step.title}</h4>
        <p style="font-size:14px; color:var(--text-secondary); margin-bottom:16px; line-height:1.4;">${step.text}</p>
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <button class="btn" id="tour-skip" style="padding:4px 8px; font-size:12px; background:transparent;">Пропустить</button>
          <button class="btn primary" id="tour-next" style="padding:6px 12px; font-size:13px;">
            ${isLast ? "Готово" : "Далее"}
          </button>
        </div>
      `;

      $("tour-next").onclick = () => { currentStep++; showStep(); };
      $("tour-skip").onclick = stop;

    }, 300); // ждем скролла
  }

  function init() {
    if (!localStorage.getItem("rm_walkthrough_done")) {
      setTimeout(start, 1000); // Запускаем через секунду после загрузки
    }
  }

  RM.walkthrough = { start, init };
})(window.RM);
