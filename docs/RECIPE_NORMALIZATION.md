# Нормализация рецептов

Стандарт: `app/recipe_template.md`.  
Код: `app/services/recipe_standard.py`, `recipe_linter.py`,
`recipe_normalizer.py`, `recipe_enricher.py`, `recipe_normalizer_worker.py`.

## Слои

1. **Linter** — быстрые проверки без LLM:
   - обязательные поля, типы, единицы, дубли, `amount`/`unit`;
   - `total_time`, `servings_text`, пустые списки, `active_time_error`;
   - MD round-trip через `md_export.recipe_to_md` + `importer.parse_markdown_recipe`.

2. **Normalizer** — детерминированные фиксы:
   - количества внутри имени (`3 яйца`, `Мягкий творог 2шт по 125гр`,
     `Крахмал 1ст ложка`, `Мука 1 ст.ложка`);
   - единицы (`гр`, `чл`, `ст.`, `банки`, `веточки` → канонические);
   - дубли (сахар/ванилин);
   - `optional` для соли/специй/зелени/«по вкусу»;
   - `total_time`, `servings_text`, `schema_version`;
   - `normalization_status`, `normalization_issues`, `normalization_hash`.

3. **Enricher** — локальный fuzzy-матчер (`local_fuzzy_matcher`):
   - проставляет `product_id`/`barcode`/`brand` при score ≥ `MATCHER_AUTO_THRESHOLD`;
   - `suggest`/`not_found` уходят в `info`-issues (не warning);
   - без сети и без LLM, поэтому быстрый.

4. **Worker** — фон:
   - старт через `RECIPE_NORMALIZER_START_DELAY`;
   - раз в `RECIPE_NORMALIZER_INTERVAL` берёт один рецепт с
     `needs_normalization()`;
   - при активности пользователя (`activity.is_active(1800)`) спит 300 с;
   - сохраняет через `recipe_store.patch_if_unchanged()` — если рецепт
     изменился, патч не применяется;
   - `print()`-логи `[normalizer] ...`.

## Флаги

```env
RECIPE_NORMALIZER_ENABLED=true
RECIPE_ENRICHER_ENABLED=true
RECIPE_NORMALIZER_START_DELAY=60
RECIPE_NORMALIZER_INTERVAL=300
```

В HA-аддоне — опции `recipe_normalizer_enabled`,
`recipe_enricher_enabled`, `recipe_normalizer_interval`.

## Dry-run

```bash
docker exec -i rm-standalone python - < build/normalize_dry_run.py
```

Скрипт ничего не сохраняет: показывает issues и нормализованные ингредиенты
для ватрушек и котлет.

## Текущее состояние dev

- 29 рецептов, `schema_version=7`.
- **29 — `ok`, 0 warnings/errors.**
- «Луковый суп»: `servings=4`, багет `0.5 шт`, грюйер `50 г`.
- «Тушеная говядина с красной фасолью»: ингредиенты восстановлены по
  инструкции через LLM (13 позиций), помечены info-issue
  `ingredients_estimated` — количества стоит проверить.
- Хлеб: «белый хлеб без корки» → `Хлеб белый`; во ВкусВилле матчится на
  `Батон нарезной, половинка` (sku 34217). «Тостовый» и «цельнозерновой»
  остаются отдельными правилами.
- Ватрушки и котлеты — `ok`; product links: 5/9 и 4/7.

## Warning-политика

- `error` — рецепт структурно неполный (нет ингредиентов/шагов).
- `warning` — можно и нужно исправить (нет количества, servings).
- `info` — обогащение/подсказка (нет КБЖУ, категорий, продукт не найден
  в базе RM, кандидат на подтверждение).

`product_not_found` — **info**, а не warning: отсутствие продукта в базе RM
не мешает искать его во ВкусВилле.
