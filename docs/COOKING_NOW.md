# «Готовлю сейчас» (Cooking Now)

## Модель

SQLite-таблица `current_cooking_sessions`:

```text
id                  UUID (PK)
user_id             владелец (family / Google sub)
main_recipe_id      nullable
side_recipe_id      nullable
checked_ingredients JSON-массив ключей
created_at / updated_at
```

Рецепты остаются в JSON (`recipes.json`), поэтому FK на `recipes` нет —
это осознанная адаптация ТЗ под текущую архитектуру.

Одна активная сессия на пользователя (`UNIQUE(user_id)`).

## API

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/cooking/current` | сессия + объединённые ингредиенты + шаги |
| POST | `/api/cooking/current` | установить `main_recipe_id` / `side_recipe_id` |
| PATCH | `/api/cooking/current/check` | `{"checked_ingredients": [...]}` |
| DELETE | `/api/cooking/current` | завершить готовку |
| POST | `/api/cooking/current/send-to-plan` | добавить в Meal Plan на сегодня |
| POST | `/api/cooking/current/send-to-shopping` | добавить неотмеченные ингредиенты в покупки |

`GET` возвращает:

```json
{
  "active": true,
  "main_recipe": {...},
  "side_recipe": {...},
  "ingredients": [
    {"key":"творог|пачка","name":"Творог","amount":2,"unit":"пачка",
     "sources":["main"],"checked":false}
  ],
  "main_steps": ["..."],
  "side_steps": ["..."]
}
```

## Объединение ингредиентов

- ключ: `normalize_for_connector(name)|unit`;
- одинаковые ключи суммируются по количеству;
- `optional` остаётся true, только если обе позиции optional;
- `sources`: `main` / `side`.

Шаги не смешиваются: `main_steps` и `side_steps` отдельно.

## UI

- фильтр-табы: Все / Основные / Гарниры / Салаты / Готовлю сейчас;
- кнопка `🍳 На кухню` на карточке и в деталях;
- после основного блюда — модалка выбора гарнира (можно «Без гарнира»);
- экран готовки: чек-лист, шаги, таймеры, «Отправить в Сегодня»,
  «Отправить в покупки», «Завершить готовку»;
- никаких confirm-попапов.

## Классификация рецептов

- `салат` в tags/courses/category → Салаты;
- `гарнир` → Гарниры;
- `десерт/выпечка/завтрак` → не Основные;
- остальные → Основные.
