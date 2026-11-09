/* Квиз подбора личного профиля питания.
 *
 * Важно: это не медицинский справочник. Квиз не диагностирует аллергию,
 * а собирает фильтр по тому, что пользователь уже знает.
 */
"use strict";
(function (RM) {
  const { $, escHtml } = RM.utils;
  const { postJSON } = RM.api;
  const state = RM.state;

  const STEPS = 5;
  const GOALS = [
    { id: "maintain", label: "Поддерживать вес", icon: "🍽", desc: "Без жёстких ограничений" },
    { id: "light", label: "Полегче", icon: "🥗", desc: "Меньше калорий, больше овощей" },
    { id: "protein", label: "Больше белка", icon: "🍗", desc: "Белок в каждом приёме пищи" },
    { id: "veggie", label: "Больше овощей", icon: "🥦", desc: "Овощи и клетчатка" },
    { id: "quick", label: "Быстро готовить", icon: "⚡", desc: "Меньше времени у плиты" },
    { id: "none", label: "Без цели", icon: "🎯", desc: "Только исключения" },
  ];
  const GOAL_MAP = {
    maintain: { max_calories: null, max_active: null, max_total: null, max_sugar: null, min_protein: null, prefer: [] },
    light: { max_calories: 400, max_active: null, max_total: null, max_sugar: 15, min_protein: null, prefer: ["овощи", "зелень"] },
    protein: { max_calories: 500, max_active: null, max_total: null, max_sugar: null, min_protein: 25, prefer: ["курица", "индейка", "рыба", "яйца", "творог"] },
    veggie: { max_calories: 500, max_active: null, max_total: null, max_sugar: 12, min_protein: null, prefer: ["овощи", "зелень", "бобовые"] },
    quick: { max_calories: null, max_active: 20, max_total: 45, max_sugar: null, min_protein: null, prefer: ["быстро"] },
    none: { max_calories: null, max_active: null, max_total: null, max_sugar: null, min_protein: null, prefer: [] },
  };
  const DISLIKES = [
    "лук", "чеснок", "грибы", "кабачки", "баклажаны", "печень",
    "кинза", "оливки", "маслины", "капуста", "тыква", "сельдерей",
  ];

  let step = 0;
  let answers = null;

  function freshAnswers() {
    return {
      goal: "maintain",
      groups: [],
      dislikes: [],
      customDislikes: "",
      activeTime: "",
      totalTime: "",
      avoidFrying: false,
      avoidOven: false,
      mealPrep: false,
      consent: false,
      name: "",
    };
  }

  function defaultName() {
    const own = (state.profiles || []).filter((p) => p && p.owner_id).length;
    return own ? `Мой профиль ${own + 1}` : "Мой профиль";
  }

  function setup() {
    const btn = $("profiles-quiz");
    if (btn) btn.addEventListener("click", open);
    const closeBtn = $("quiz-close");
    if (closeBtn) closeBtn.addEventListener("click", () => close(true));
    const back = $("quiz-back");
    if (back) back.addEventListener("click", onBack);
    const next = $("quiz-next");
    if (next) next.addEventListener("click", onNext);
    const save = $("quiz-save");
    if (save) save.addEventListener("click", onSave);
    const overlay = $("quiz-overlay");
    if (overlay) {
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) close(true);
      });
    }

    const body = $("quiz-body");
    if (body) {
      body.addEventListener("change", onBodyChange);
      body.addEventListener("input", onBodyInput);
    }
  }

  function open() {
    answers = freshAnswers();
    answers.name = defaultName();
    step = 0;
    if ($("profiles-overlay")) $("profiles-overlay").classList.remove("show");
    $("quiz-overlay").classList.add("show");
    render();
  }

  function close(showProfiles) {
    $("quiz-overlay").classList.remove("show");
    if (showProfiles && $("profiles-overlay")) {
      $("profiles-overlay").classList.add("show");
      if (RM.profiles && RM.profiles.render) RM.profiles.render();
    }
  }

  function onNext() {
    if (!answers) return;
    if (step === 0 && !answers.consent) {
      alert("Подтвердите, что понимаете ограничения фильтра.");
      return;
    }
    if (step < STEPS - 1) {
      step += 1;
      render();
    }
  }

  function onBack() {
    if (!answers) return;
    if (step > 0) {
      step -= 1;
      render();
    }
  }

  function onBodyChange(event) {
    if (!answers) return;
    const target = event.target;
    if (!target) return;
    if (target.name === "quiz-goal") {
      answers.goal = target.value;
      document.querySelectorAll(".quiz-goal").forEach((el) => {
        const input = el.querySelector('input[name="quiz-goal"]');
        el.classList.toggle("active", !!input && input.value === answers.goal);
      });
      return;
    }
    if (target.dataset && target.dataset.quizGroup) {
      const id = target.dataset.quizGroup;
      if (target.checked) {
        if (!answers.groups.includes(id)) answers.groups.push(id);
      } else {
        answers.groups = answers.groups.filter((g) => g !== id);
      }
      return;
    }
    if (target.dataset && target.dataset.quizDislike) {
      const value = target.dataset.quizDislike;
      if (target.checked) {
        if (!answers.dislikes.includes(value)) answers.dislikes.push(value);
      } else {
        answers.dislikes = answers.dislikes.filter((x) => x !== value);
      }
      return;
    }
    if (target.id === "quiz-consent") {
      answers.consent = !!target.checked;
      const next = $("quiz-next");
      if (next) next.disabled = !answers.consent;
      return;
    }
    if (target.id === "quiz-active-time") answers.activeTime = target.value;
    if (target.id === "quiz-total-time") answers.totalTime = target.value;
    if (target.id === "quiz-avoid-frying") answers.avoidFrying = !!target.checked;
    if (target.id === "quiz-avoid-oven") answers.avoidOven = !!target.checked;
    if (target.id === "quiz-meal-prep") answers.mealPrep = !!target.checked;
  }

  function onBodyInput(event) {
    if (!answers) return;
    const target = event.target;
    if (!target) return;
    if (target.id === "quiz-custom-dislikes") answers.customDislikes = target.value;
    if (target.id === "quiz-name") answers.name = target.value;
  }

  function render() {
    if (!answers) return;
    const body = $("quiz-body");
    if (!body) return;
    body.innerHTML = stepBody();
    const back = $("quiz-back");
    const next = $("quiz-next");
    const save = $("quiz-save");
    if (back) back.style.display = step === 0 ? "none" : "";
    if (next) {
      next.style.display = step === STEPS - 1 ? "none" : "";
      next.disabled = step === 0 && !answers.consent;
    }
    if (save) save.style.display = step === STEPS - 1 ? "" : "none";
    const bar = $("quiz-progress-bar");
    if (bar) bar.style.width = `${Math.round(((step + 1) / STEPS) * 100)}%`;
  }

  function stepBody() {
    if (step === 0) return stepIntro();
    if (step === 1) return stepGroups();
    if (step === 2) return stepDislikes();
    if (step === 3) return stepTime();
    return stepSummary();
  }

  function stepIntro() {
    return `
      <div class="quiz-disclaimer">
        <b>Это не медицинский справочник.</b> Квиз не определяет аллергию
        и не заменяет консультацию врача. Фильтр ищет аллергены по названиям
        ингредиентов и может ошибаться — особенно в соусах, полуфабрикатах
        и продуктах со сложным составом. При аллергии всегда проверяйте
        состав и маркировку.
      </div>
      <label class="quiz-consent">
        <input type="checkbox" id="quiz-consent" ${answers.consent ? "checked" : ""}>
        Понимаю ограничения и хочу продолжить
      </label>
      <div class="quiz-section-title">Какая цель?</div>
      <div class="quiz-goals">
        ${GOALS.map((g) => `
          <label class="quiz-goal ${answers.goal === g.id ? "active" : ""}">
            <input type="radio" name="quiz-goal" value="${g.id}" ${answers.goal === g.id ? "checked" : ""}>
            <span class="quiz-goal-icon">${g.icon}</span>
            <span><b>${escHtml(g.label)}</b><small>${escHtml(g.desc)}</small></span>
          </label>
        `).join("")}
      </div>`;
  }

  function groupsFor(section) {
    return (RM.allergenGroups || []).filter((g) => g.section === section);
  }

  function groupChecks(section) {
    return groupsFor(section).map((g) => `
      <label class="quiz-check">
        <input type="checkbox" data-quiz-group="${escHtml(g.id)}" ${answers.groups.includes(g.id) ? "checked" : ""}>
        ${escHtml(g.label)}
      </label>
    `).join("");
  }

  function stepGroups() {
    return `
      <div class="quiz-section-title">Что исключить?</div>
      <div class="quiz-hint">Если ничего не выбрано — без ограничений.</div>
      <div class="quiz-subtitle">Аллергены и непереносимость</div>
      <div class="quiz-checks">${groupChecks("allergen")}</div>
      <div class="quiz-subtitle">Мясо и птица</div>
      <div class="quiz-checks">${groupChecks("diet")}</div>
      <div class="quiz-note">
        Рыба, морепродукты, молоко и яйца находятся в разделе аллергенов
        выше — отметьте их там, если их тоже нужно исключить.
      </div>
      <div class="quiz-note">
        Фильтр работает по названиям ингредиентов. Соусы, полуфабрикаты
        и следы аллергенов могут не распознаваться.
      </div>`;
  }

  function stepDislikes() {
    return `
      <div class="quiz-section-title">Что не любите?</div>
      <div class="quiz-hint">Это не аллергены, а вкусовые предпочтения.</div>
      <div class="quiz-checks">
        ${DISLIKES.map((item) => `
          <label class="quiz-check">
            <input type="checkbox" data-quiz-dislike="${escHtml(item)}" ${answers.dislikes.includes(item) ? "checked" : ""}>
            ${escHtml(item)}
          </label>
        `).join("")}
      </div>
      <div class="field quiz-field">
        <label for="quiz-custom-dislikes">Свои продукты (через запятую)</label>
        <input type="text" id="quiz-custom-dislikes" value="${escHtml(answers.customDislikes)}" placeholder="например, оливки, кинза">
      </div>`;
  }

  function stepTime() {
    const active = [
      ["", "Не важно"], ["15", "до 15 минут"], ["30", "до 30 минут"],
      ["45", "до 45 минут"], ["60", "до 60 минут"],
    ];
    const total = [
      ["", "Не важно"], ["30", "до 30 минут"], ["45", "до 45 минут"],
      ["60", "до 60 минут"], ["90", "до 90 минут"], ["120", "до 2 часов"],
    ];
    return `
      <div class="quiz-section-title">Время и техника</div>
      <div class="row">
        <div class="field quiz-field">
          <label for="quiz-active-time">Активное время</label>
          <select id="quiz-active-time">
            ${active.map(([v, l]) => `<option value="${v}" ${answers.activeTime === v ? "selected" : ""}>${l}</option>`).join("")}
          </select>
        </div>
        <div class="field quiz-field">
          <label for="quiz-total-time">Общее время</label>
          <select id="quiz-total-time">
            ${total.map(([v, l]) => `<option value="${v}" ${answers.totalTime === v ? "selected" : ""}>${l}</option>`).join("")}
          </select>
        </div>
      </div>
      <div class="quiz-checks">
        <label class="quiz-check"><input type="checkbox" id="quiz-avoid-frying" ${answers.avoidFrying ? "checked" : ""}> Избегать жарки</label>
        <label class="quiz-check"><input type="checkbox" id="quiz-avoid-oven" ${answers.avoidOven ? "checked" : ""}> Избегать духовки</label>
        <label class="quiz-check"><input type="checkbox" id="quiz-meal-prep" ${answers.mealPrep ? "checked" : ""}> Нужны заготовки на несколько дней</label>
      </div>`;
  }

  function summaryItems() {
    const items = [];
    const goal = GOALS.find((g) => g.id === answers.goal);
    if (goal) items.push(`${goal.icon} ${goal.label}`);
    if (RM.allergenLabels) items.push(...RM.allergenLabels(answers.groups).map((x) => `без: ${x}`));
    const custom = (answers.customDislikes || "").split(",").map((x) => x.trim()).filter(Boolean);
    const dislikes = [...answers.dislikes, ...custom];
    if (dislikes.length) items.push(`не люблю: ${dislikes.join(", ")}`);
    if (answers.activeTime) items.push(`активно до ${answers.activeTime} мин`);
    if (answers.totalTime) items.push(`всего до ${answers.totalTime} мин`);
    if (answers.avoidFrying) items.push("без жарки");
    if (answers.avoidOven) items.push("без духовки");
    if (answers.mealPrep) items.push("заготовки");
    return items;
  }

  function stepSummary() {
    const items = summaryItems();
    return `
      <div class="quiz-section-title">Проверьте профиль</div>
      <div class="quiz-summary">
        ${items.length ? items.map((x) => `<span>${escHtml(x)}</span>`).join("") : "<span>Без ограничений</span>"}
      </div>
      <div class="field quiz-field">
        <label for="quiz-name">Название профиля</label>
        <input type="text" id="quiz-name" value="${escHtml(answers.name || defaultName())}" placeholder="Мой профиль">
      </div>
      ${(answers.goal === "maintain" || answers.goal === "none") ? `<div class="quiz-hint">Числовых ограничений по калориям, белку и времени нет — профиль только исключает выбранные продукты.</div>` : ""}
      <div class="quiz-disclaimer quiz-disclaimer-small">
        Фильтр не гарантирует отсутствие аллергенов и следов. Проверяйте
        состав и маркировку. Это не медицинская рекомендация.
      </div>`;
  }

  function buildConstraints() {
    const goal = GOAL_MAP[answers.goal] || GOAL_MAP.maintain;
    const methods = [];
    if (answers.avoidFrying) methods.push("жарка", "фритюр");
    if (answers.avoidOven) methods.push("запекание", "выпечка");
    const preferMethods = [];
    if (answers.mealPrep) preferMethods.push("тушение", "запекание");
    if (answers.goal === "quick") preferMethods.push("варка", "пар");
    const custom = (answers.customDislikes || "").split(",").map((x) => x.trim()).filter(Boolean);
    const dislikes = [...new Set([...answers.dislikes, ...custom])];

    return {
      max_calories_per_serving: goal.max_calories,
      max_active_time_min: answers.activeTime ? Number(answers.activeTime) : goal.max_active,
      max_total_time_min: answers.totalTime ? Number(answers.totalTime) : goal.max_total,
      max_sugar_per_serving_g: goal.max_sugar,
      min_protein_per_serving_g: goal.min_protein,
      avoid_methods: methods,
      prefer_methods: [...new Set(preferMethods)],
      avoid_ingredients: dislikes,
      avoid_groups: [...answers.groups],
      prefer_ingredients: goal.prefer,
    };
  }

  function buildDescription() {
    const goal = GOALS.find((g) => g.id === answers.goal);
    return goal ? `Квиз: ${goal.label}` : "Индивидуальный профиль из квиза";
  }

  async function onSave() {
    if (!answers) return;
    const name = ($("quiz-name")?.value || answers.name || "").trim();
    if (!name) {
      alert("Укажите название профиля.");
      return;
    }
    const btn = $("quiz-save");
    if (btn) btn.disabled = true;
    try {
      const data = await postJSON("api/profiles", {
        name,
        icon: (GOALS.find((g) => g.id === answers.goal) || {}).icon || "🍽",
        description: buildDescription(),
        goal: answers.goal,
        source: "quiz",
        quiz_version: 1,
        constraints: buildConstraints(),
      });
      const profileId = data && data.profile && data.profile.id;
      if (profileId) {
        await postJSON("api/profiles/active", { profile_id: profileId });
      }
      if (RM.profiles && RM.profiles.load) await RM.profiles.load();
      close(true);
      if (RM.recipes && RM.recipes.filterAndRender) RM.recipes.filterAndRender();
      alert("Профиль сохранён и включён. Проверьте его в списке профилей.");
    } catch (err) {
      alert("Ошибка сохранения профиля: " + err.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  RM.quiz = { setup, open };
})(window.RM);
