# Recipe Manager

Home Assistant add-on для управления рецептами, планирования питания
и покупок. Импорт из YouTube Shorts, Markdown и веб-страниц; генерация
рецептов через LLM; каскадный матчинг ингредиентов; синхронизация
с GitHub.

## Что умеет

### Импорт и создание
- **YouTube Shorts** — `yt-dlp` + Google Gemini → структурированный Markdown
- **Markdown** с YAML front matter (одиночный файл или массовый batch)
- **Веб-страницы** — JSON-LD / microdata
- **Вручную** — встроенный редактор
- **Генерация через LLM** — Gemini / Hermes / любой OpenAI-совместимый endpoint

### Организация
- **Библиотека рецептов** с поиском по названию, тегам, ингредиентам
- **Профили генерации** — ограничения по калориям, времени, ингредиентам
- **Фильтр «🎯 Только под профиль»** — рецепты, которые тебе подходят
- **Бейдж соответствия** на карточке рецепта

### Планирование и покупки
- **Планировщик питания** — недельная сетка с итогами КБЖУ по дню
- **Список покупок** — объединение дубликатов, поиск по штрих-коду
  (OpenFoodFacts), сканер камерой

### Данные и синхронизация
- **База продуктов** — локальная, с каскадным матчингом ингредиентов
  (fuzzy → embeddings → LLM-валидация)
- **Резервные копии** — rolling-бэкапы всех JSON-файлов в `/data/backups/`
- **Синхронизация с GitHub** — `recipes.json` + `ingredients.json`
  атомарным коммитом (Git Data API)

## Установка как HA add-on

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Добавить `https://github.com/ebloved/recipe-manager-addon`
3. Найти **Recipe Manager** → **Install**
4. **Configuration** — указать минимум `gemini_api_key` (или
   `matcher_external_*` для Hermes / другого OpenAI-совместимого endpoint)
5. **Start**

После старта появится панель **Recipe Manager** в левом меню Home Assistant.

## Основные опции

Все параметры — в **Configuration** аддона (YAML / UI). Полный список
со `schema` — в [`config.yaml`](config.yaml).

| Опция | Назначение |
|---|---|
| `runtime_mode` | `minimal` / `standard` / `full` — что включено |
| `gemini_api_key` | Gemini: генерация, эмбеддинги, валидация |
| `gemini_models` | Список моделей (fallback в cascade) |
| `matcher_external_*` | OpenAI-совместимый endpoint (Hermes, OpenRouter, Ollama…) |
| `local_embedder_enabled` | sentence-transformers на CPU (без сети) |
| `github_*` | Синхронизация рецептов и продуктов с репозиторием |
| `generator_*` | Параметры генератора (лимиты, samples, max_tokens) |
| `off_*` | OpenFoodFacts (поиск штрих-кодов) |

## Структура проекта

```text
app/
├── main.py              # FastAPI app, lifespan, ingress middleware
├── config.py            # env-переменные и пути
├── routes/              # эндпоинты по доменам
├── services/            # бизнес-логика (matcher, generator, youtube…)
├── stores/              # JSON-хранилища (in-memory + /data)
├── recipe_manager/      # импортёры, парсеры
└── static/              # vanilla JS + CSS (без сборки)

config.yaml              # HA add-on схема (options + schema)
run.sh                   # entrypoint для HA Supervisor
Dockerfile
```

## Разработка

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
DOWNLOAD_DIR=/tmp/rm_dl DATA_DIR=/tmp/rm_data \
  .venv/bin/uvicorn app.main:app --reload --port 8099
```

Фронтенд — vanilla JS без сборки. Изменения в `app/static/` подхватываются
сразу, cache-busting через `?v=N` в `index.html`.

## История версий

См. [CHANGELOG.md](CHANGELOG.md) — все релизы с 1.0.0, включая hotfix-серии.

---

## Планы

### Ближайшее (addon)
- Оценка `active_time` через LLM — точный фильтр по профилю.
- Экспорт и импорт всей библиотеки в ZIP.
- Scheduler — автогенерация рецептов по расписанию.

### Standalone (Docker + OAuth)
- Развёртывание отдельным сервисом с Google OAuth для совместного
  использования с друзьями.
- Standalone embedding service — addon ходит в него за эмбеддингами
  (снимает 80 МБ модели из HA).
- Публикация рецептов по ссылке с fork в личную библиотеку.
- Per-user LLM keys в личном кабинете.

### Позже
- Multi-md режим синхронизации с GitHub (папка вместо одного файла).
- Интеграция с «Честный знак» (публичный endpoint ЦРПТ).

---

## Авторы

Проект создан и поддерживается [@ebloved](https://github.com/ebloved).

Архитектура, значительная часть кода и документации разработаны
совместно с **ИИ DeepSeek** ([deepseek.com](https://deepseek.com)).