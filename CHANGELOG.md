# Changelog

Все значимые изменения проекта Recipe Manager.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии — по [Semantic Versioning](https://semver.org/lang/ru/).

---

## [1.10.9] — 2026-10-25

UI-фиксы для мобильных + умный фоновый воркер.

### Fixed

- **Мобильная шапка**: убран дублирующий заголовок «Recipe Manager»
  на узких экранах, кнопка «Кабинет» стала компактнее.
- **Удалена кнопка «Оценить N без active_time»**.
- **Защита лимитов Gemini**: фоновый воркер оценки `active_time`
  теперь берёт 1 рецепт раз в 2 часа (чтобы не съесть 20 RPD).
  Если вы генерируете рецепт или нажимаете «Оценить», воркер
  засыпает на 30 минут.

---

## [1.10.7] — 2026-10-25

Hotfix UI: восстановление стилей селектора профиля.

### Fixed

- **Вёрстка селектора профиля.** Патч v1.10.6 сломал базовые CSS-стили
  (фон, рамки, нативную стрелку). Восстановлен тёмный фон, кастомная
  SVG-стрелка и безопасный расчёт ширины через `measureText`.

---

## [1.10.6] — 2026-10-25

UI: идеальная ширина профиля.

### Fixed

- **Селектор профиля** в шапке теперь вычисляет ширину с помощью
  `Canvas.measureText()` (пиксель-в-пиксель), а не по количеству
  символов. Кастомная SVG-стрелка вместо нативной, чтобы убрать
  лишние отступы браузера.

---

## [1.10.5] — 2026-10-25

UI: адаптивный селектор профиля и управление профилями в Кабинете.

### Changed

- **Селектор профиля в шапке** теперь подстраивает ширину под выбранный
  текст (от 140 до 280 px), а не растягивается по самой длинной опции.
- **Управление профилями (⚙️)** перенесено из шапки в вкладку «Кабинет».

---

## [1.10.4] — 2026-10-25

Hotfix: надежная загрузка Кабинета.

### Fixed

- **Вечные спиннеры в «Кабинете».** `tabs.js` не подхватывал
  новый case из-за расхождения в регулярках. Теперь `cabinet.js`
  вешает прямой слушатель клика на кнопку «Кабинет» в обход `tabs.js`.

---

## [1.10.3] — 2026-10-25

Hotfix: автоматическая загрузка данных в Кабинете.

### Fixed

- **Вечные спиннеры в «Кабинете».** `tabs.js` не вызывал
  `RM.cabinet.load()` при переключении на вкладку, а `app.js`
  инициализировал `RM.sync.setup()` вместо `RM.cabinet.setup()`.
  Из-за этого данные не запрашивались при входе, хотя ручной
  вызов `RM.cabinet.load()` в консоли работал.

---

## [1.10.2] — 2026-10-25

Hotfix UI: шапка и кнопки синхронизации.

### Fixed

- **Ошибка в консоли (sync.js).** При генерации HTML для «Кабинета»
  потерялись кнопки `sync-pull` и `sync-push`, из-за чего скрипт
  падал с `null`. Восстановлен HTML и добавлена защита в JS.
- **Дизайн шапки.** Разделена на 2 ряда: верх (Заголовок, «Кабинет»,
  профиль) и низ (вкладки). Вкладки теперь не переносятся на новую
  строку, а скроллятся вбок на узких экранах.

---

## [1.10.1] — 2026-10-25

Hotfix UI после v1.10.0.

### Fixed

- **Спиннеры в «Кабинете».** При переносе HTML во вкладку «Добавить»
  потерялись ID элементов (`yt-download`, `scrape-fetch` и др.).
  `youtube.js` падал с `null`, роняя `app.js` до инициализации
  `cabinet.js`. Восстановлен HTML, а в JS добавлена защита от `null`.
- **«Кабинет» вынесен из общего ряда.** Перенесён вправо (рядом с
  селектором профиля) через `.header-right`.

---

## [1.10.0] — 2026-10-25

UI рефакторинг: объединение импорта и новый личный кабинет.

### Added

- **`GET /api/me`** — текущий пользователь. В HA читает заголовки
  `X-Remote-User-*`, в прямом доступе возвращает «Семья».
- **Вкладка «👤 Кабинет»** (заменяет «Синхронизацию»).
  Содержит: профиль пользователя, статус LLM-провайдеров (🟢/🔴),
  синхронизацию с GitHub и версию аддона. Задел под standalone.
- **Вкладка «➕ Добавить»** — объединяет старые «YouTube» и «Импорт».
  Под-табы: YouTube, Со сайта, Markdown, Вручную.

### Changed

- Навигация: 8 вкладок → 7. Убраны лишние кнопки.

---

## [1.9.5] — 2026-10-25

Hotfix UI синхронизации с GitHub.

### Fixed

- **`undefined` при pull.** API `/api/sync/pull` возвращает вложенную
  структуру `{recipes: {added, total}, ingredients: {...}}`, а фронтенд
  читал `data.added`. Теперь читается `data.recipes.added`.
- **«Файл ещё не создан» при push.** С v1.3.0 бэкенд синхронизирует
  два файла (`recipes.json` и `ingredients.json`), и статус
  возвращает объект `files`. Старый `sync.js` ожидал плоскую
  структуру (`data.path`, `data.exists`). Теперь UI показывает
  статус для обоих файлов отдельно (и SHA коммита).

---

## [1.9.4] — 2026-10-25

Hotfix UX: разъяснение временных метрик.

### Fixed

- **Пользователь путался в цифрах** после оценки `active_time`: в detail
  отображалось `🔥 15 мин` и `🎯 16м*`, но `prep_time` (30 мин) скрывался,
  если `total_time` совпадал с суммой prep+cook.
- **`detail.js`**: теперь показываются все времена с подписями:
  `🔪 30 мин подг.`, `🔥 15 мин готовки`, `⏱ 45 мин всего`,
  `🎯 16 мин акт.*`. Логика скрытия `prep_time` удалена.
- **`recipes.js` / `generator.js`**: подпись `🎯 16м` заменена на
  `🎯 16 мин акт.`; в `title` добавлено пояснение: «Активное время —
  сколько вы заняты готовкой (а не общее время по рецепту)».

---

## [1.9.2] — 2026-10-25

Hotfix: per-recipe active_time — async, как и генерация.

### Fixed

- **`POST /api/recipes/{id}/estimate-active-time`** был синхронным.
  На медленной thinking-модели Gemini (in_progress 225+ секунд)
  запрос упирался в nginx-таймаут (~60 с) → браузер получал
  HTML `504 Gateway Time-out` → `Ошибка оценки: {}`.
  Теперь `202 {job_id}` + поллинг `/api/generator/jobs/{id}`,
  как у генерации.
- **`max_tokens` 2000 → 8000** в `services/active_time.py`.
  Thinking-модели тратят `max_output_tokens` на reasoning; 2000
  уходило в thinking, ответ не приходил. Ответ короткий (JSON
  с числами), 8000 — с запасом.

### Changed

- **Frontend `onEstimateActiveTime`:** после 202 показывает
  `⏳ Оценка… Ns` в chip, поллит job каждые 2 с, по завершении
  перезагружает рецепт через `GET /api/recipes/{id}` и
  перерисовывает detail. Hard-cap 10 минут.
- При `status=error` от job — alert с текстом ошибки (не `{}`).
  При 404 (рестарт аддона) — «Задача потеряна».

---

## [1.9.1] — 2026-10-25

UX active_time: оценка из detail-view, batch — только когда нужен.

### Added

- **`POST /api/recipes/{id}/estimate-active-time`** — оценка одного
  рецепта (sync). `force=true` по умолчанию.
- **Chip `🎯 Nм*` в detail-view** — кликабельный, клик → пересчёт
  через `onEstimateActiveTime()`. Если не оценено — chip
  `🎯 Оценить` (dashed border). `*` = оценка ИИ, без звёздочки —
  точное значение.

### Changed

- **Batch-кнопка в search-row — условная.** Показывается только
  если в библиотеке **≥ 3 рецепта без `active_time`**. Текст
  `🎯 Оценить N без active_time` (число, не «все»). После успешной
  оценки кнопка исчезает.
- Для 25 рецептов это ~5 минут при Gemini 5 RPM; для 100 — ~20 минут.
  Поэтому batch — редкое действие (миграция), а per-recipe —
  повседневное.

---

## [1.9.0] — 2026-10-25

B1: оценка `active_time` через LLM. Фильтр по профилю использует
реальное активное время, а не `prep_time`.

### Added

- **`services/active_time.py`** — LLM оценивает каждый шаг как
  active/passive и суммирует active в минутах. Возвращает JSON
  `{steps: [{index, active_min}], total_active_min}`. Промпт чётко
  отделяет «нарезать» и «помешивать при обжарке» от «тушить 30 мин».
- **Поля в рецепте:** `active_time` (int, минуты), `active_time_estimated`
  (bool, true = оценка ИИ), `active_time_hash` (SHA256 от instructions),
  `active_time_at` (ISO timestamp), `active_time_error` (при сбое).
- **Sync-вызов при сохранении.** `POST /api/recipes` и
  `PATCH /api/recipes/{id}` (если в patch есть `instructions`) вызывают
  `estimate_active_time`. Hash-based инвалидация: если шаги не менялись —
  LLM не вызывается.
- **`import_recipe_md`** и **`create_from_markdown`** — пересчитывают
  active_time после замены содержимого.
- **`POST /api/recipes/estimate-active-time?force=false`** — batch-оценка
  всех рецептов через `JobsStore` (async job, поллинг через
  `/api/generator/jobs/{id}`).
- **UI: кнопка «🎯 Оценить active_time»** в поисковой строке на вкладке
  «Рецепты». Показывает прогресс, обновляет список после завершения.
- **UI: chip `🎯 Nм`** на карточке рецепта (звёздочка `*` если оценка ИИ).
  В preview сгенерированного рецепта — тоже в мета-строке.

### Changed

- **`fitsProfile` (C1): убран fallback на `prep_time`.** При заданном
  `max_active_time_min` рецепт без `active_time` не попадает в фильтр.
  Это консервативно (честно «не знаю»), но после нажатия «Оценить все»
  все рецепты получат реальную оценку.

### Notes

- Ошибка LLM **не блокирует** сохранение рецепта: `active_time`
  остаётся `null`, в `active_time_error` пишется причина. Можно повторить
  через batch.
- Стоимость: один LLM-вызов на рецепт. Для 20 рецептов — 20 вызовов,
  при Gemini 5 RPM = ~4 минуты. Batch идёт в фоне, UI не блокируется.

---

## [1.8.5] — 2026-10-25

Документация: README разделён с CHANGELOG.

### Changed

- **`README.md`** — теперь нормальный README: что умеет,
  установка как add-on, основные опции, структура проекта,
  разработка. Раньше файл дублировал CHANGELOG (начинался
  с `# Changelog`) и содержал историю до 1.3.0.
- **`## Планы`** — актуализированы: addon (active_time, ZIP,
  scheduler) и standalone (OAuth, embedding service, per-user
  LLM keys, sharing по ссылке).
- История версий — по ссылке на [`CHANGELOG.md`](CHANGELOG.md).

---

## [1.8.4] — 2026-10-25

Preview сгенерированных рецептов — модалка вместо `window.open`.

### Fixed

- **Preview не работал в мобильном приложении HA и Safari:**
  `window.open` блокируется (popup blocker, iframe sandbox,
  отсутствие user gesture после `alert` в `accept`). Заменён на
  модалку `#gen-preview-overlay` внутри страницы.

### Added

- **Рендер рецепта в preview.** Вместо голого `<pre>` — читаемая
  карточка: название, описание, мета (время, порции, теги), КБЖУ,
  ингредиенты, шаги. Не интерактивно (serving scale и чекбоксы —
  только в detail-view после accept).
- **Вкладка «📄 RAW»** в preview — сырой Markdown ответа LLM
  (для диагностики `parse_failed`).
- Закрытие: close-кнопка, клик по фону, Esc.
- Адаптивная вёрстка для узких экранов (мобильное приложение HA).

---

## [1.8.3] — 2026-10-25

Hotfix C1/C2 после v1.8.2.

### Fixed

- **`.search-row`**: не получил `display: flex` (патч v1.8.2 скипнул
  из-за ложного guard). Кнопка «🎯 Только под профиль» падала на
  новую строку под поиском. Теперь inline `flex` + `input { flex: 1 }`.
- **`profiles.js:setActive`** (смена профиля через модалку) не
  вызывала `RM.recipes.filterAndRender()`, в отличие от `onSelectActive`
  в шапке. Список не перерисовывался. Добавлен refresh.

---

## [1.8.2] — 2026-10-25

C1: фильтр рецептов по активному профилю. C2: бейдж 🎯 на карточке.

### Added

- **C1: кнопка «🎯 Только под профиль»** в поисковой строке вкладки
  «Рецепты». Показывает `fitsProfile`: `max_calories_per_serving`,
  `max_total_time_min`, `max_active_time_min` (fallback: `prep_time`),
  `min_protein_per_serving_g`, `max_sugar_per_serving_g`. Кнопка
  скрыта, если активного профиля нет; показывает «(N/M)» — сколько
  рецептов из M подходят. Клик — переключает фильтр.
- **C2: бейдж 🎯** в мета-строке карточки — рецепт подходит под
  активный профиль.
- При смене активного профиля список рецептов перерисовывается.

### Notes

- B1 (active_time через LLM) пока не реализован — при заданном
  `max_active_time_min` используется `recipe.active_time` или
  `recipe.prep_time` как fallback.

---

## [1.8.1] — 2026-10-25

Hotfix: `GeminiProvider.health()` / `embed()` ссылались на несуществующие
атрибуты инстанса — B5 это наконец показал.

### Fixed

- **`GeminiProvider`** — `self._api_key`, `self._proxy`,
  `self._generative_model` нигде не присваиваются, но используются в
  `health()`, `embed()` и ещё нескольких методах (в `complete()` были
  заменены ещё в v1.6.5). Теперь везде используется модульный конфиг:
  `GEMINI_API_KEY`, `GEMINI_PROXY`, `self.model`.
- **`[matcher] health: ...`** больше не показывает
  `gemini=unavailable('GeminiProvider' object has no attribute ...)`.
  Ожидаемо: `gemini=ok`.

---

## [1.8.0] — 2026-10-25

B2: фикс имён ингредиентов в списке покупок.
B5: health-check matcher-провайдеров на старте аддона.

### Added

- **B5: health-check провайдеров на старте.** `main.py:lifespan` после
  `provider_registry.initialize()` вызывает `await provider_registry.health_all()`
  и логирует результат: `[matcher] health: local_fuzzy=ok, gemini=ok, ...`.
  Видно в HA-логе сразу после строки `[matcher] provider=...`.

### Fixed

- **B2: имена ингредиентов в списке покупок.** При `POST /api/shopping/from-recipe`
  ингредиенты с `product_id` теперь разрешаются через `ingredients_store`:
  в shopping item попадает `product.name` (а не сырое `ingredient.name` из
  рецепта), плюс `brand`, `barcode`, `image_url`, `category`, `product_id`.
  Раньше два рецепта с одним продуктом («греческий йогурт» / «греч. йогурт»)
  создавали два item-а; теперь — один, с каноничным именем из справочника.

### Notes

- Генератор использует in-memory `JobsStore`. При рестарте аддона
  незавершённые задачи теряются; UI при поллинге получает 404 и показывает
  «задача потеряна». Это by design (v1.6.0), документация — в
  `app/stores/jobs.py`.

---

## [1.7.3] — 2026-10-24

Hotfix: обработка пустого `error` от Interactions API + восстановление
потерянных патчей (incomplete, max_tokens).

### Fixed

- **`incomplete` — терминальный статус.** Ранее `incomplete` не входил
  в список terminal, поллинг продолжался до 300–600 с, в логе копилось
  `still incomplete (78s)`, `still incomplete (355s)`.
- **`failed` с пустым `error` (`{}`) — retriable.** Google иногда
  возвращает `status="failed"` без деталей (rate limit / safety /
  транспортный сбой). Раньше это останавливало каскад с `FATAL`.
  Теперь — переключение на следующую модель.
- **Логирование полного JSON** при пустом `error` для диагностики.
- **`max_tokens` 3000 → 15000** в `generator.py`: thinking-модель
  тратит reasoning-токены внутри `max_output_tokens`, 3000 не хватало.
  `GENERATOR_MAX_TOKENS` в `config.py` (если ещё не было).

### Notes

- `_poll_interaction` возвращает 3-tuple `(out, status, err_msg)`
  (без изменений сигнатуры). Логика retriable — в `complete()`.

---

## [1.7.1] — 2026-10-24

Hotfix: авто-починка YAML (двоеточия в description/title, inline-списки).

### Fixed

- **`_clean_md`** не кавычил поля с `: ` в значении → YAML-парсер
  падал на `description: ... заготовок: при хранении ...`. Теперь
  `description` и `title` с двоеточиями автоматически оборачиваются
  в двойные кавычки.
- **`_clean_md`** теперь оборачивает элементы inline-списков в кавычки
  (`tags: [a, b]` → `tags: ["a", "b"]`).
- Удаление невидимых символов (`\u00a0`, `\u200b`).

---

## [1.7.0] — 2026-10-24

`max_tokens` вынесен в настройки аддона.

### Added

- **`generator_max_tokens`** в `config.yaml` (options: `15000`,
  schema: `int(1000,32000)`). Позволяет менять лимит
  `max_output_tokens` для Gemini прямо в Configuration аддона,
  без пересборки. Thinking-модели требуют солидного бюджета
  (reasoning + тело рецепта), но при желании можно ограничить.

### Changed

- **`generator.py`** и **`gemini_embedder.py`** больше не
  содержат магических чисел: `max_tokens` по умолчанию
  берётся из `config.GENERATOR_MAX_TOKENS`.

---

## [1.6.11] — 2026-10-24

Hotfix: принудительное применение max_tokens=15000.

### Fixed

- Скрипты v1.6.9 и v1.6.10 искали `max_tokens=8000`, но у
  пользователя в `generator.py` оставалось `max_tokens=3000`
  (v1.6.9 был пропущен). Из-за этого в логе было
  `max_tokens=3000`, и thinking-модель обрубалась по лимиту.
  Жёсткая замена `3000` → `15000` в `generator.py` и
  `gemini_embedder.py`.

---

## [1.6.10] — 2026-10-24

Увеличен бюджет токенов и лимит поллинга для thinking-моделей.

### Changed

- **`max_tokens` 8000 → 15000.** Thinking-модели Gemini тратят много
  токенов на reasoning (`thoughtsTokenCount`), из-за чего 8000
  не хватало на тело рецепта (статус `incomplete`). 15000
  гарантированно покрывает и размышления, и Markdown-ответ.
- **Лимит поллинга фронтенда 600s → 900s (15 минут).** Синхронизирован
  с бэкендом: 3 модели × 300s (`_MAX_POLL_DURATION`) = ровно 900s.
  Раньше фронт сдавался на 600s, хотя бэкенду могло оставаться
  время на последнюю модель в каскаде.
- **Cache-bust** `?v=29` → `?v=30`.

---

## [1.6.8] — 2026-10-24

Hotfix: извлечение ответа из нового формата Interactions API (steps).

### Fixed

- **`_poll_interaction`**: при `status="completed"` текст
  извлекался из `output_text` / `outputs[]`, но в новом формате
  API (Api-Revision: 2026-05-20) текст лежит внутри
  `steps[]` → `type="model_output"` → `content[]` → `type="text"`.
  Из-за этого `complete()` возвращал пустую строку, и джоб падал с
  `LLM вернул пустой ответ`. Добавлен парсинг `steps` с fallback
  на `output_text`/`outputs` для совместимости.
- Если текст не найден ни одним способом — в лог пишется
  `completed but text is empty! keys=[...]` для диагностики.

---

## [1.6.7] — 2026-10-24

Background Execution через Gemini Interactions API — никаких таймаутов на «размышления» модели.

### Added

- **Background Execution.** `GeminiProvider.complete()` теперь использует
  `/v1beta/interactions` с `"background": true`. API сразу возвращает
  `interaction_id`, после чего бэкенд опрашивает статус каждые 5 секунд
  через `GET /v1beta/interactions/{id}`. Жёсткого таймаута на одну модель
  больше нет: модель может «думать» сколько угодно (safety-предел — 10 мин).
- **Polling-логи.** Каждый опрос логирует смену статуса (`in_progress`,
  `completed`, `failed`) и промежуточный прогресс. В HA-логе видно:
  `[gemini] gemini-3.8-flash poll #3: status=in_progress (15s)`.
- **Cascade по моделям сохранён.** Если interaction завершился `failed`
  с 503/429/5xx — пробуем следующую модель из `GEMINI_MODELS`.
  Ошибка показывается пользователю только если все модели упали
  (и только если это 503/rate limit или `failed` от Gemini).

### Changed

- **UI:** индикатор выполнения показывает прошедшее время
  («Генерирую… 42s»), при завершении — «✓ Создано N предложений»,
  при ошибке — текст из `job.error`. Лимит поллинга фронтенда — 10 минут.
- **`_last_usage.attempts`** в `/diag` для фоновых задач содержит
  `model`, `status` (`ok` / `error`), `elapsed_s`, `error` (при наличии),
  `retriable` (true/false).

### Notes

- Interactions API может вернуть `HTTP 400`, если `background: true`
  передан без `store: true`. В запросе `store` не задаётся явно —
  используется серверный default (`true`).
- Если Gemini завершит interaction со статусом `requires_action`
  (запрос ввода от пользователя), это трактуется как `failed` —
  для генерации рецептов такого сценария быть не должно.

---

## [1.6.6] — 2026-10-24

Hotfix: `KeyError 'attempts'` в cascade + логи cascade не видны.

### Fixed

- **`GeminiProvider._complete_one()`** перезаписывал
  `self._last_usage` (словарь из `complete()` с ключами
  `models_tried`/`attempts`/`prompt_chars`) на `{finish_reason, usage}`.
  После успешного ответа `complete()` вызывал
  `self._last_usage["attempts"].append(...)` → `KeyError 'attempts'`.
  Исправлено: `_complete_one` использует `.update()` вместо `=`,
  `self._last_usage = {}` из начала тела удалён.
- **Логи cascade не появлялись.** `logger.info()` из
  `services.matcher.gemini_embedder` не долетает — uvicorn настраивает
  только свои логгеры, кастомные падают в `logging.lastResort`
  (уровень WARNING). `logger.info` → `print()` (как в остальном
  проекте: `[ingredients] loaded`, `[matcher] provider=...` и т.п.).
  `logger.warning/error` — оставлены, они видны.

### Changed

- `run.sh`: `bashio::addon.version` → `bashio::app.version`
  (первая задепрекейчена в текущей версии HA).

---

## [1.6.5] — 2026-10-24

Hotfix: `SyntaxError` в `gemini_embedder.py`.

### Fixed

- **Порядок imports.** v1.6.4-скрипт при добавлении `import logging`
  и `logger = ...` вставил их **перед** docstring и
  `from __future__ import annotations`. Python требует, чтобы
  future-импорт шёл первым (после docstring) → `SyntaxError:
  from __future__ imports must occur at the beginning of the
  file`. Модуль не импортировался, `providers.py` тихо превращал
  `gemini_embedder` в `None`, `/run` возвращал `503 Нет
  доступных LLM-провайдеров`. Docstring и `from __future__`
  восстановлены в начало файла; `import logging` и `logger`
  перенесены в блок imports перед `class GeminiProvider`.

### Notes

- `ast.parse()` этот класс ошибок не ловит (`PyCF_ONLY_AST`
  пропускает проверку `__future__`). Hotfix-скрипт проверяет
  через `compile()`, который ловит.

---

## [1.6.4] — 2026-10-24

Cascade теперь срабатывает на timeout + подробный лог.

### Fixed

- **`GeminiProvider.complete()`**: timeout от модели не попадал в
  `_is_retriable()` (проверялись только `HTTP 4xx/5xx` и
  `server error`) → cascade не пробовал следующую модель.
  Теперь `timeout` в списке retriable.
- **Пустое сообщение `Gemini timeout:`**: `httpx.TimeoutException`
  имеет пустой `__str__()`. Теперь любая ошибка логируется с именем
  модели и её `elapsed` (например, `gemini-3.8-flash: timeout at
  90s`).

### Changed

- **Per-model budget 90 с, общий deadline 240 с.** Каждый вызов
  `_complete_one` обёрнут в `asyncio.wait_for(timeout=90s)`. Если
  первая модель отдала 503 за 8 с — у следующих полный бюджет;
  если timeout — переключаемся на следующую, а не висим 130 с
  на первой.
- **Подробный лог cascade:** на каждую модель `try`/`ok`/
  `TIMEOUT`/`failed` с бюджетом, elapsed, retriable/fatal.
- **`/diag → last_attempt.usage.attempts`** — массив
  `{model, status, elapsed_s, error?, retriable?}` с результатом
  каждой попытки. Видно прямо в браузере, кто и почему упал.

### Notes

- Если после v1.6.4 все модели стабильно timeout на 90 с — это
  уже не про cascade, а про payload: samples=2 × ~1000 токенов
  примеров + 3000 max_tokens output. Следующий шаг диагностики —
  уменьшить samples=1 или max_tokens=2000, или проверить
  `thoughtsTokenCount` (thinking-модель тратит бюджет на reasoning).

---

## [1.6.3] — 2026-10-24

Возврат few-shot образцов по умолчанию (async делает это безопасным).

### Changed

- **`generator_default_samples` 0 → 2.** В v1.5.4 samples были
  обнулены, чтобы уложиться в nginx-таймаут ~60 с синхронного
  `/run`. С async-режимом (v1.6.0) это ограничение снято —
  few-shot образцы резко снижают долю `parse_failed` и улучшают
  соблюдение формата YAML. Ожидаемое время job: 25–45 с.

---

## [1.6.2] — 2026-10-24

Hotfix парсера: авто-починка невалидного Markdown от LLM.

### Fixed

- **`generator.py::_clean_md`**: если LLM добавляла текст перед YAML
  front matter, парсер падал. Теперь всё до первого `---` отрезается.
  Также добавлена замена `item:` на `name:` в списке ингредиентов.
- **`prompt.py`**: в `SYSTEM_PROMPT` добавлены строгие правила
  (ответ должен начинаться с `---`, использовать `name:` вместо `item:`).

---

## [1.6.1] — 2026-10-24

Hotfix UI + понятная ошибка при перегрузке Gemini.

### Fixed

- **`generator.js`**: fallback-ветка на случай `POST /run` без
  `job_id` показывала `✓ Создано undefined предложений`. Причина —
  кэш браузера с v1.5.x JS (не знает про job-модель). Фолбэк-ветка
  теперь показывает ошибку и подсказку обновить страницу. Cache-bust
  `?v=26 → ?v=27` для принудительной перезагрузки.
- **`GeminiProvider.complete()`**: если все модели из
  `GEMINI_MODELS` вернули 503/server error — выводится
  «Gemini перегружен (503) — попробуйте через 1–2 минуты» вместо
  сырого `All N models failed: ...`.

---

## [1.6.0] — 2026-10-24

Async-режим генерации + cascade по моделям Gemini.

### Added

- **Async-задания.** `POST /api/generator/run` возвращает
  `202 {job_id}` за ~200 мс и запускает `asyncio.Task` в фоне.
  Клиент поллит `GET /api/generator/jobs/{id}` каждые 2 с.
  Снимает ограничение HA ingress nginx (~60 с), из-за которого
  пользователь видел `504 Gateway Time-out` при 94-секундном
  ответе Gemini (v1.5.4).
- **`GET /api/generator/jobs?status=pending`** — фронтенд
  подхватывает незавершённую задачу при перезагрузке страницы
  (resume).
- **`JobsStore`** (`app/stores/jobs.py`) — in-memory, не
  персистится. При рестарте аддона pending теряются (клиент
  увидит 404). Завершённые старше часа чистятся лениво.
- **Cascade в `GeminiProvider.complete()`.** При
  `404`/`429`/`500`/`502`/`503` от модели провайдер пробует
  следующую из `GEMINI_MODELS`. Timeout/auth НЕ retry'ются.
  `last_attempt.usage.models_tried` в `/diag` показывает, какие
  модели уже пробовали.

### Changed

- Фронтенд: живой счётчик «Генерирую… 12s»; при done —
  «✓ Создано N предложений»; при error — текст из `job.error`.
  Hard-limit поллинга — 5 минут.

---

## [1.5.6] — 2026-10-24

Hotfix: `NameError: GEMINI_MODELS is not defined` в `generator.py`.

### Fixed

- **`generator.py`** ссылался на `GEMINI_MODELS` в `_model_name()`
  (добавлено в v1.5.5), но импорт `from config import GEMINI_MODELS`
  не был добавлен: скрипт v1.5.5 молча пропустил шаг из-за
  слишком умного условия. `NameError` срабатывал в `except`-ветке
  при любом провале провайдера и маскировал реальную ошибку
  (например, `Gemini: server error 503`).

---

## [1.5.5] — 2026-10-24

Фикс обрезанного ответа Gemini, отображения модели и наблюдаемость.

### Fixed

- **`max_tokens` 1200 → 3000.** Ответ Gemini обрезался на
  `description: "Сочное куриное филе...` — `finishReason` = `MAX_TOKENS`,
  `parse_markdown_recipe` падал с `No recipe title found`. 1200
  токенов из v1.5.4 были реакцией на таймаут, но режут тело рецепта.
- **`generator.py::_model_name`** возвращал `provider.model`
  (`gemini-2.0-flash` — class-attr fallback), хотя `complete()` уже
  с v1.5.2 ходил на `GEMINI_MODELS[0]` (`gemini-3.8-flash`).
  `last_attempt.model` в `/diag` показывал не ту модель. Теперь та же
  логика, что в `providers.py::_model_name`.

### Added

- **`_last_usage` в `GeminiProvider.complete()`** — сохраняет
  `finishReason` и `usageMetadata` (prompt/candidates/thoughts tokens)
  последнего ответа.
- **`/diag` → `last_attempt.finish_reason` и `last_attempt.usage`** —
  без shell-доступа видно, почему ответ обрезан (MAX_TOKENS /
  SAFETY / STOP) и сколько токенов потратил Gemini.

### Notes

- `elapsed_s: 94.45` (v1.5.4) — синхронный режим упирается в
  HA ingress nginx (~60 с). Async-режим (202 + polling через
  `/jobs/{id}`) — iteration D.
- `gemini_proxy_set: true` — A/B-тест без прокси намечен на
  следующий шаг диагностики.

---

## [1.5.4] — 2026-10-06

Уменьшение синхронной нагрузки + диагностика для no-shell окружения.

### Added

- **`GET /api/generator/diag`** — версия аддона, `GEMINI_MODELS`,
  флаг `GEMINI_PROXY`, таймауты `complete()`, `last_attempt`
  (provider, model, elapsed_s, error, at).
- **`/api/generator/status`** — расширен полями `version`,
  `last_attempt`.
- **`ADDON_VERSION`** — env из `bashio::addon.version` в `run.sh`.

### Changed

- `max_tokens` 2500 → 1200, `generator_default_samples` 3 → 0.
  Цель — уложиться в <50 с ответа Gemini, чтобы не упираться в
  таймаут HA ingress nginx (~60 с), который отдаёт браузеру
  `504 Gateway Time-out` раньше нашего 120-секундного таймаута.

### Notes

- Асинхронный шаблон (202 + polling через `/jobs/{id}`) —
  отдельная итерация, если синхронный режим продолжит упираться.

---

## [1.5.3] — 2026-10-06

Фикс: таймаут `GeminiProvider.complete()` увеличен с 30 до 120 секунд.

### Fixed

- **`GeminiProvider.complete()`** использовал `_TIMEOUT =
  httpx.Timeout(30.0, connect=10.0)` — общий таймаут эмбеддинг-запросов
  (200–500 мс). Генерация рецепта с `max_tokens=2500` занимает 15–60 с,
  30 с не хватало → `Gemini timeout` → `502` на `POST /api/generator/run`.
  Введена отдельная константа `_GENERATE_TIMEOUT =
  httpx.Timeout(120.0, connect=15.0)`, используется только в `complete()`.
  `embed()` / health остаются на 30-секундном `_TIMEOUT`.

### Notes

- `services/gemini.py::call_gemini` (YouTube-путь) использует 60 с. Унификация
  таймаутов + cascade по `GEMINI_MODELS` при 404/5xx — отдельная итерация.

---

## [1.5.2] — 2026-10-06

Фикс: `GeminiProvider.complete()` использовал hardcoded `gemini-2.0-flash`
вместо списка из конфига.

### Fixed

- **`GeminiProvider.complete()`** после фикса 1.5.1 корректно обращался
  к module-level конфигу, но модель брал из `self.model =
  _GENERATIVE_FALLBACK_MODEL` (`gemini-2.0-flash`), которую Gemini уже
  вывел из обращения → `404 models/gemini-2.0-flash is no longer
  available` → `502` на `POST /api/generator/run`. Теперь модель
  берётся из `GEMINI_MODELS[0]` (по умолчанию `gemini-3.8-flash` из
  `config.yaml`), с fallback на `self.model` если список пуст.
- **`/api/generator/status`** теперь показывает актуальную модель
  Gemini (`GEMINI_MODELS[0]`) вместо устаревшего class-attr.

---

## [1.5.1] — 2026-10-06

Фикс сломанного `GeminiProvider.complete()` — генератор (1.5.0) теперь
реально может вызывать Gemini.

### Fixed

- **`GeminiProvider.complete()`** ссылался на `self._api_key`,
  `self._proxy`, `self._generative_model`, которые не устанавливаются
  ни в `GeminiProvider.__init__`, ни в `EmbeddingProvider.__init__`.
  Метод никогда не вызывался матчером (использовался только
  эмбеддинг-путь), но генератор 1.5.0 дёрнул — получили
  `AttributeError: 'GeminiProvider' object has no attribute '_api_key'`
  → `502 Bad Gateway` на `POST /api/generator/run`.
  Замена внутри `complete()`: `GEMINI_API_KEY`, `GEMINI_PROXY`,
  `self.model`. Эмбеддинг-путь (`embed()`, health) не тронут.

### Known issues

- `GeminiProvider.embed()` и healthcheck используют те же
  несуществующие атрибуты (`self._api_key` / `_proxy` /
  `_generative_model`). В проде не проявляется, пока
  `matcher_provider=gemini` не активируется вручную. Починим
  отдельной итерацией.

---

## [1.5.0] — 2026-10-06

Генератор рецептов через LLM с очередью предложений.

### Added

- **Вкладка «✨ Генератор».** Генерация новых рецептов через LLM
  (Hermes / Gemini) с учётом активного профиля и few-shot образцов
  из существующей библиотеки. Очередь предложений: принять
  (→ `recipes.json`), отклонить, предпросмотр сырого Markdown.
- **Провайдеры генерации.** Каскад: Hermes (OpenAI-совместимый)
  → Gemini. Используются существующие классы из `services/matcher`.
  Эндпоинт `/api/generator/status` показывает доступность и активного
  провайдера.
- **Хранилище предложений.** `/data/suggestions.json`, схема со
  `status` (pending / accepted / rejected), сырым Markdown ответа
  и результатом `parse_markdown_recipe`.
- **API генератора.** `POST /api/generator/run`,
  `GET /api/generator/suggestions`, `POST .../{id}/accept`,
  `DELETE .../{id}`, `GET /api/generator/status`.
- **Конфиг.** `generator_max_count`, `generator_default_count`,
  `generator_samples_max`, `generator_default_samples` в
  `config.yaml` и `run.sh`.

### Notes

- Периодический запуск (cron / scheduler) — отдельная итерация.
- Фильтрация рецептов в списке по активному профилю — отдельная
  итерация.

---

## [1.3.0] — 2026-10-06

Крупный релиз: база продуктов с открытой интеграцией в OpenFoodFacts,
каскад матчинга ингредиентов, резервные копии, массовый импорт Markdown.

### Added

- **Вкладка «📦 Продукты».** Полноценный CRUD-интерфейс над локальной базой
  ингредиентов. Продукт содержит: `product_id` (UUID), `barcode` (GTIN),
  имя, бренд, категорию, изображение, КБЖУ на 100 г, вес порции, алиасы,
  источник данных (`openfoodfacts` / `manual` / `recipe`).
- **Связка ингредиента с продуктом.** Кнопка 🔗 рядом с каждым ингредиентом
  в detail-view и секция «Связки с продуктами» в редакторе рецепта.
  Модалка `product-picker` с тремя сценариями: поиск по базе, поиск
  по штрих-коду в OpenFoodFacts, создание нового продукта.
- **Автоматическое создание алиасов.** При связывании «греч. йогурт 2%»
  с продуктом «Греческий йогурт 2%» первое имя становится алиасом продукта.
- **Каскад матчинга ингредиентов.** Трёхуровневая система:
  - **Уровень A** — точное совпадение + локальный fuzzy
    (Levenshtein, Jaro-Winkler, русский стеммер). Работает без сети.
  - **Уровень B** — векторный матчинг через эмбеддинги. Провайдеры
    по приоритету: внешний OpenAI-совместимый endpoint (Hermes),
    локальный `sentence-transformers` (CPU, ONNX Runtime),
    Gemini Embeddings, OpenRouter, Groq.
  - **Уровень C** — генеративная валидация через LLM для спорных пар
    (confidence 0.80–0.95): Hermes / Gemini.
  - Ручное подтверждение через UI-очередь — всегда доступно.
- **Очередь подтверждений.** После массового импорта рецептов, если
  найдены кандидаты со средним score, открывается модалка со списком
  связок. Действия: подтвердить / выбрать другое / пропустить,
  плюс массовые кнопки.
- **Резервные копии.** Rolling-бэкапы всех JSON-файлов в `/data/backups/`
  раз в сутки. Хранение N дней (по умолчанию 7). Ручное создание,
  восстановление с pre-restore копией, принудительная ротация.
  Автоматически отключаются опцией `backup_enabled: false`.
- **Массовый импорт Markdown.** Загрузка нескольких `.md` файлов одним
  запросом. Общий кэш OpenFoodFacts между рецептами — если в 20 файлах
  один и тот же продукт, запрос идёт один раз.
- **Экспорт рецепта в `.md` с блоком `product`.** При выгрузке рецепта
  в front matter ингредиентов пишется `product: {uuid, barcode}`. Это
  обеспечивает переносимость связок между инсталляциями.
- **Эндпоинт `/api/recipes/{id}/export.md`** — скачать рецепт файлом.
- **Эндпоинт `POST /api/recipes/-/from-markdown`** — создать рецепт
  из текста Markdown без merge с явными полями.
- **Эндпоинт `POST /api/recipes/import-batch`** — массовый импорт
  нескольких файлов.
- **Диагностический эндпоинт `/api/youtube/jobs`** — список обработанных
  job'ов с информацией о субтитрах и `.md` файлах.
- **Полное логирование stderr yt-dlp** — при ошибках скачивания
  в логах аддона теперь видна причина, а не только `rc=1`.

### Changed

- **Схема `ingredients.json`** с `schema_version: 1` и `installation_id`.
  Встроенная система миграций (пока пустая, но структура готова).
- **`github_sync.py` переписан на Git Data API.** Push теперь атомарный:
  несколько файлов коммитятся одним коммитом (blobs → tree → commit →
  update ref). Contents API умеет только один файл за коммит и не даёт
  атомарности.
- **Синхронизация идёт по двум файлам** — `recipes.json` и
  `ingredients.json`. Оба заливаются одним коммитом. Параметр `what`
  в `/api/sync/push` и `/api/sync/pull` позволяет выбрать, что синкать.
- **Merge-стратегии при pull** для базы продуктов: `last-write-wins`
  (по умолчанию), `local-wins`, `remote-wins`. Сопоставление по
  `product_id` → `barcode` → имени/алиасу.
- **Парсер Markdown** (`parse_markdown_recipe`) теперь читает
  блок `product` с полями `uuid` / `barcode`. Парсер остаётся чистым:
  не ходит в `ingredients_store`, а возвращает структуру — связывание
  выполняет отдельный слой `services/linker.py`.
- **`services/linker.py`** — новый слой между парсером и store.
  Обрабатывает три сценария: `product.barcode` → `OFF lookup` → `store.add`,
  `product.uuid` → `store.get`, отсутствие данных → пропуск.
  Общий barcode-кэш между рецептами при batch-импорте.
- **`md_export.py`** — обогащает ингредиенты barcode-ами при экспорте:
  делает lazy lookup в `ingredients_store`, добавляет `product.barcode`
  в front matter.
- **`routes/imports.py`** — вынесены из `routes/recipes.py` эндпоинты
  `import-url`, `import-text`, `import-batch`. После импорта вызывается
  `matcherBatch.processAfterImport()` для фонового поиска связок.
- **`routes/recipes.py`** — CRUD + export.md + import-md.
  Все точки входа Markdown прогоняют ингредиенты через linker.
- **`routes/youtube.py`** — параметры `save` и `link` в
  `/api/generate-recipe`. Если `save=true`, рецепт сохраняется сразу,
  с прогоном через linker.
- **Порядок роутеров в `routes/__init__.py`.** `imports` идёт **до**
  `recipes`, потому что содержит подпути `/api/recipes/import-*`,
  которые иначе попали бы в `/{recipe_id}`.
- **Фронтенд: новая вкладка «📦 Продукты»** между «Покупки» и
  «Синхронизация».
- **Новая модалка `product-picker`** — используется из detail-view,
  editor-view и вкладки продуктов.
- **Новая модалка `matcher-batch`** — очередь подтверждений связок.
- **`editor.js`** — секция «🔗 Связки с продуктами» под textarea
  ингредиентов. Связки хранятся по нормализованному имени, автоматически
  очищаются при удалении ингредиента из textarea.
- **`detail.js`** — миниатюра связанного продукта у ингредиента
  (кликабельна), кнопка 🔗 для несвязанных. Кэш продуктов в
  `state.productCache` между открытиями рецептов.
- **`imports.js`** — поддержка массовой загрузки `.md` файлов,
  вызов `matcherBatch.processAfterImport()` после каждого импорта.
- **`state.js`** — добавлен `RM.RDA` для расчёта процентов БЖУ.
- **Карточки рецептов** скрывают фрейм фото, если `image_url` не задан.

### Removed

- **Интеграция с Национальным каталогом** (`catalog_source`,
  `catalog_api_key`). API-ключ выдаётся только юридическим лицам через
  УКЭП — частному лицу недоступен.
- Устаревшие CSS-классы inline-редактирования количества в shopping list
  (`.shop-qty`, `.shop-qty-editor`, `.shop-qty-input`) — заменены на
  `+ / − / select`.

### Fixed

- **Формула подсчёта калорий в планировщике.** Было `nutrition ×
  (planned / recipe.servings)`, стало `nutrition × planned_servings`.
  Теперь 320 ккал рецепта на 4 порции, добавленного как «2 порции»,
  даёт 640 ккал, а не 160.
- **Пищевая ценность помечена как «на 1 порцию»** — в detail-view и в
  планировщике. Раньше было неясно, к чему относятся значения.
- **Кнопка «+» в планировщике** открывает модалку выбора рецепта
  (раньше показывала alert).
- **GitHub PUT 404** при вводе полного URL в `github_repo` —
  исправлено нормализацией: `https://github.com/owner/repo`,
  `git@github.com:owner/repo.git` и `owner/repo` теперь эквивалентны.
- **Раздача статики через явный роут `/static/{path}`** вместо
  `StaticFiles` mount — исправляет работу под HA ingress.
- **MIME-типы CSS и JS** отдавались как `application/json` под
  HA ingress — исправлено ручной таблицей `_MIME`.
- **Кэш браузера не подхватывал обновления** — добавлен cache-busting
  через `?v=N` во всех тегах `<script>` и `<link>`.
- **Кнопка «В покупки» на карточке рецепта** не срабатывала из-за
  порядка загрузки скриптов — исправлено event delegation.
- **Сканер камерой** не давал понять, что распознавание произошло —
  добавлена визуальная индикация (зелёная рамка + плашка
  «✓ Распознано: код»).

### Dependencies

Добавлены опционально:
- `sentence-transformers>=3.2.0` — локальные эмбеддинги (CPU).
- `onnxruntime>=1.18.0` — ускорение на CPU.

Все остальные зависимости без изменений.

### Upgrade notes

- **Опции `catalog_source` и `catalog_api_key`** удалены из схемы.
  Если они остались в вашем `options.json` — Supervisor напишет warning.
  Откройте Configuration аддона и нажмите «Сохранить» (без изменений
  полей) — warning исчезнет. Если не помогает — переустановите аддон,
  данные в `/data` сохранятся.
- **Архитектуры `armv7`, `armhf`, `i386` удалены** из `config.yaml`
  (в предыдущей версии 1.2.4). Современные HA OS работают только на
  `aarch64` и `amd64`.
- **Первый запуск** создаст пустой `ingredients.json` с полем
  `installation_id` (UUID вашей инсталляции).
- **Первый авто-бэкап** произойдёт через 60 секунд после старта.
- **Синхронизация** теперь пишет два файла. При pull, если в репозитории
  ещё нет `ingredients.json`, он просто пропускается (не ошибка).

---

## [1.2.5] — 2026-10-05

Пищевая ценность на 1 порцию, добавление рецептов из планировщика.

### Added

- **Добавление рецепта из планировщика.** При клике на «+» в ячейке
  недельной сетки открывается модалка с поиском по рецептам.
- **Кнопка «+» в ячейках планировщика.** Появляется при наведении.

### Changed

- **Пищевая ценность помечена как «на 1 порцию»** — соответствует формату
  `recipe_template.md`.
- **Формула подсчёта калорий в планировщике** исправлена:
  `nutrition × planned_servings`, а не `× (planned / recipe.servings)`.

### Fixed

- Итоги дня в планировщике показывали заниженный калораж, если
  в рецепте `servings > 1`.

---

## [1.2.4] — 2026-10-05

Устойчивая синхронизация с GitHub, итоги питания в планировщике.

### Added

- **Итоги по дню в планировщике.** Строка «🥗 Итого» под неделей:
  калории, проценты от дневных норм калорий и Б/Ж/У.
- **Endpoint `/api/meal-plan`** возвращает `recipe_nutrition` и
  `recipe_servings` для каждой записи.
- **`RM.RDA` в `state.js`** — единый источник дневных норм.

### Changed

- **Нормализация `github_repo`.** Принимает `owner/repo`,
  `https://github.com/owner/repo`, `git@github.com:owner/repo.git`.
- **`github_sync.py`** — предварительная проверка доступа к репозиторию
  и ветке. Понятные сообщения об ошибках вместо голых 404.
- **`config.yaml`** — версия 1.2.4, `armv7` удалён из `arch`.

### Fixed

- `GitHub PUT 404: message: not found` при вводе полного URL
  в `github_repo` — исправлено нормализацией.
- `INFO: POST /api/sync/push HTTP/1.1 404 Not Found` при неправильно
  настроенном токене — теперь бэкенд делает предварительную проверку
  доступа и возвращает внятный текст.

### Upgrade notes

- Если в `github_repo` был указан полный URL — можно оставить,
  будет нормализовано автоматически. Для чистоты рекомендуется
  заменить на `owner/repo`.

---

## [1.2.0] — 2026-10-05

Крупный релиз: модульная переработка бэкенда, планировщик питания,
список покупок, синхронизация с GitHub, редактор Markdown внутри
приложения.

### Added

- **Планировщик питания.** Недельная сетка с приёмами пищи
  (завтрак / обед / полдник / ужин).
- **Список покупок.** Отдельная вкладка с чек-листом, inline-редактор
  количества (`−` / `+` / поле ввода / выпадающий список единиц).
- **Поиск по штрих-коду** через OpenFoodFacts. Ручной ввод или
  сканирование камерой.
- **Сканер камерой.** Нативный `BarcodeDetector` в Chromium,
  `html5-qrcode` в WebKit (iOS Safari, Firefox). Поддержка EAN-13,
  EAN-8, UPC-A, UPC-E, Code-128, Code-39 и QR.
- **Синхронизация с GitHub.** Двусторонняя (pull / push) синхронизация
  файла `recipes.json` с репозиторием.
- **Экспорт рецепта в Markdown.** Кнопка «📥 .md» в редакторе.
- **Редактирование рецепта в Markdown.** Кнопка «📝 Markdown»
  в редакторе.
- **Endpoint `/api/debug/static`** для диагностики раздачи статики.

### Changed

- **Модульная структура бэкенда.** `main.py` разбит на пакеты:
  `stores/`, `services/`, `routes/`, плюс `config.py` и `helpers.py`.
- **Модульная структура фронтенда.** Один `index.html` + модульные js:
  `utils`, `api`, `state`, `tabs`, `youtube`, `imports`, `recipes`,
  `detail`, `editor`, `plan-picker`, `planner`, `shopping`, `sync`,
  `app`.
- **Раздача статики** через явный роут `/static/{path}` вместо
  `StaticFiles` mount — исправляет работу под HA ingress.
- **Layout detail-view** — одноколоночный: ингредиенты → шаги → порции →
  пищевая ценность → заметки.
- **Карточки рецептов** скрывают фрейм фото, если `image_url` не задан.

### Removed

- **Интеграция с Национальным каталогом** (`catalog_source`,
  `catalog_api_key`).
- Неиспользуемые модули из `recipe_manager/` (`const.py`, `models.py`,
  `scraper.py`, `storage.py`).

### Fixed

- Сканер камерой не давал понять, что распознавание произошло —
  добавлена визуальная индикация.
- Кнопка «В покупки» в карточке рецепта не срабатывала — исправлено
  event delegation.
- MIME-типы CSS и JS отдавались как `application/json` под HA ingress.
- Кэш браузера не подхватывал обновления — добавлен cache-busting
  через `?v=N`.

---

## [1.1.0] — 2026-10-04

Импорт рецептов из Markdown.

### Added

- **Markdown import** — импорт рецептов из `.md` файлов с YAML front
  matter. Три режима: вставка текста, загрузка файла, загрузка по URL.
- **Парсер** `parse_markdown_recipe()` в `importer.py`. Понимает
  YAML front matter, fallback на разбор секций `## Ингредиенты` /
  `## Шаги`.
- **Расширение `recipes/add`** — принимает `markdown_content`.
  Поле `name` стало необязательным при наличии `markdown_content`.
- **Frontend** — вкладка **Markdown** в диалоге создания рецепта.

### Changed

- `manifest.json` — добавлена зависимость `python-frontmatter>=1.0.0`.

---

## [1.0.0] — 2026-09-15

Первый публичный релиз аддона.

### Added

- **Импорт из YouTube Shorts** через `yt-dlp` + Google Gemini.
- **Структурирование рецепта** в Markdown с YAML front matter.
- **Редактор рецептов** в браузере.
- **Библиотека рецептов** с поиском по названию, тегам, ингредиентам.
- **Detail-view** с ингредиентами, шагами, заметками, скалером порций
  и пищевой ценностью (SVG-кольцо + Daily RDA).
- **Поддержка nutrition** в front matter: калории, белки, жиры, углеводы,
  клетчатка, сахар, натрий, холестерин.
- **Storage** в `/data/recipes.json`.
- **Ingress UI** через панель Home Assistant.

### Dependencies

- `fastapi`, `uvicorn`, `yt-dlp`, `httpx`, `aiofiles`.

---

## Планы

- Multi-md режим синхронизации с GitHub (папка вместо одного файла).
- Экспорт всей библиотеки в ZIP-архив.
- Импорт библиотеки из ZIP.
- Интеграция с системой «Честный знак» для проверки подлинности
  (публичный endpoint ЦРПТ).

---

## Авторы

Проект создан и поддерживается [@ebloved](https://github.com/ebloved).

Архитектура, значительная часть кода и документации разработаны
совместно с **ИИ DeepSeek** ([deepseek.com](https://deepseek.com)) —
включая каскад матчинга ингредиентов, дизайн формата `product: {uuid, barcode}`
для переносимости связок, модульную структуру бэкенда, логику
синхронизации с GitHub через Git Data API с атомарными коммитами,
русский стемминг в fuzzy-матчере.