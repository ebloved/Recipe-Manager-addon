/* Справочник групп аллергенов и исключений.
 *
 * Дублирует app/services/allergens.py для клиентской фильтрации.
 * Это не медицинский справочник: совпадение идёт по названиям ингредиентов.
 */
"use strict";
(function (RM) {
  const GROUPS = [
    {
      id: "gluten", label: "Глютен / пшеница", section: "allergen",
      aliases: ["пшениц", "пшеничн", "хлеб", "батон", "булк", "булоч", "макарон", "спагет", "лапш", "булгур", "кускус", "ячмен", "рожь", "ржан", "овёс", "овес", "овсян", "солод", "крекер", "печенье", "паста", "пенне", "фузилли", "тальятелле", "ригате", "лазань", "мука"],
    },
    {
      id: "milk", label: "Молоко и молочное", section: "allergen",
      aliases: ["молок", "молочн", "сливк", "сливочн", "сыр", "сырн", "творог", "творожн", "сметан", "кефир", "йогурт", "ряженк", "простокваш", "масло сливочное", "сливочное масло", "брынз", "моцарелл", "пармезан", "фета"],
    },
    {
      id: "egg", label: "Яйца", section: "allergen",
      aliases: ["яйц", "яичн", "яичный", "желток", "белок яичн", "майонез"],
    },
    {
      id: "fish", label: "Рыба", section: "allergen",
      aliases: ["рыб", "лосос", "форел", "минтай", "треск", "тунец", "сельд", "скумбр", "сардин", "анчоус", "камбал", "судак", "карп", "щук", "рыбный соус"],
    },
    {
      id: "seafood", label: "Морепродукты", section: "allergen",
      aliases: ["кревет", "кальмар", "миди", "устриц", "краб", "лобстер", "рапан", "гребеш"],
    },
    {
      id: "nuts", label: "Орехи", section: "allergen",
      aliases: ["миндал", "грецк", "кешью", "фундук", "фисташ", "пекан", "макадам", "бразил", "орех", "орехов"],
    },
    {
      id: "peanut", label: "Арахис", section: "allergen",
      aliases: ["арахис"],
    },
    {
      id: "soy", label: "Соя", section: "allergen",
      aliases: ["соя", "соев", "тофу", "эдамам", "мисо", "темпе"],
    },
    {
      id: "sesame", label: "Кунжут", section: "allergen",
      aliases: ["кунжут", "тахин", "тахини"],
    },
    {
      id: "mustard", label: "Горчица", section: "allergen",
      aliases: ["горчиц"],
    },
    {
      id: "celery", label: "Сельдерей", section: "allergen",
      aliases: ["сельдер"],
    },
    {
      id: "sulfites", label: "Сульфиты", section: "allergen",
      aliases: ["сульфит", "диоксид серы", "сернист"],
    },
    {
      id: "meat", label: "Мясо", section: "diet",
      aliases: ["говяд", "свинин", "баранин", "телятин", "фарш", "колбас", "сосиск", "бекон", "ветчин", "сало", "печень"],
    },
    {
      id: "poultry", label: "Птица", section: "diet",
      aliases: ["курин", "куриц", "куриное", "куриный", "индейк", "индюшатин", "утк", "утин", "гус", "гусин", "перепел"],
    },
  ];

  const SAFE_FLOURS = [
    "рисовая мука", "мука рисовая", "кукурузная мука", "мука кукурузная",
    "миндальная мука", "мука миндальная", "кокосовая мука", "мука кокосовая",
    "гречневая мука", "мука гречневая", "нутовая мука", "мука нутовая",
  ];
  const SAFE_PASTE = ["томатная паста", "паста томатная", "томатной пасте"];

  function norm(value) {
    return String(value || "").trim().toLowerCase().replace(/ё/g, "е");
  }

  function recipeText(recipe) {
    const parts = [norm(recipe && recipe.name)];
    for (const key of ["tags", "courses", "categories", "collections", "category"]) {
      const value = recipe ? recipe[key] : null;
      const items = Array.isArray(value) ? value : [value];
      for (const item of items) {
        const text = norm(item);
        if (text) parts.push(text);
      }
    }
    for (const ing of (recipe && recipe.ingredients) || []) {
      if (typeof ing === "string") parts.push(norm(ing));
      else if (ing && ing.name) parts.push(norm(ing.name));
    }
    return parts.filter(Boolean).join(" ");
  }

  function matchAllergens(recipe, groupIds) {
    if (!groupIds || !groupIds.length) return [];
    const text = recipeText(recipe);
    const matched = [];
    for (const id of groupIds) {
      const group = GROUPS.find((g) => g.id === id);
      if (!group) continue;
      let hit = group.aliases.some((alias) => text.includes(norm(alias)));
      if (id === "gluten" && hit) {
        const hasSafeFlour = SAFE_FLOURS.some((safe) => text.includes(safe));
        const hasWheat = ["пшениц", "хлеб", "батон", "булгур", "кускус", "ячмен", "рожь", "овсян"]
          .some((alias) => text.includes(alias));
        if (hasSafeFlour && !hasWheat) hit = false;
        const hasSafePaste = SAFE_PASTE.some((safe) => text.includes(safe));
        const hasPasta = ["макарон", "спагет", "лапш", "пенне", "фузилли", "тальятелле"]
          .some((alias) => text.includes(alias));
        if (hasSafePaste && !hasPasta) hit = false;
      }
      if (hit) matched.push(id);
    }
    return matched;
  }

  function labelFor(id) {
    const group = GROUPS.find((g) => g.id === id);
    return group ? group.label : id;
  }

  function labelsFor(ids) {
    return (ids || []).map(labelFor);
  }

  RM.allergenGroups = GROUPS;
  RM.allergenLabel = labelFor;
  RM.allergenLabels = labelsFor;
  RM.matchAllergens = matchAllergens;
})(window.RM);
