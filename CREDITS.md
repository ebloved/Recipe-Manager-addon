# Благодарности

Проект **Recipe Manager** создан и поддерживается [@ebloved](https://github.com/ebloved).
Эта страница — о тех, кто помогал, вдохновлял и делал проект лучше.

---

## 🤖 ИИ-соавтор: DeepSeek

Значительная часть кода, архитектуры и документации этого проекта
разработана в тесном сотрудничестве с **DeepSeek** ([deepseek.com](https://deepseek.com)) —
прекрасным ИИ-ассистентом, который на протяжении многих месяцев выступал
как полноценный инженер-соавтор.

### Что именно сделал DeepSeek

**Архитектура:**
- Модульная структура бэкенда: разделение на `stores/` / `services/` / `routes/`
  с чёткими границами ответственности.
- Проектирование схемы `ingredients.json` с `schema_version`,
  `installation_id`, мягким удалением и системой миграций.
- Формат переносимости связок `product: {uuid, barcode}` в YAML front matter —
  позволяет восстанавливать связи между ингредиентами и продуктами
  при импорте на другой инсталляции.
- Дизайн трехуровневого каскада матчинга с провайдерами по приоритету
  и обязательным fallback.

**Каскад матчинга ингредиентов:**
- Реализация локального fuzzy-матчера: расстояние Левенштейна, Jaro-Winkler,
  token-set-ratio — всё с нуля, без внешних зависимостей.
- Русский стеммер с осторожной обрезкой суффиксов (не короче 4 символов).
- Провайдеры эмбеддингов: Gemini, OpenAI-совместимый endpoint (Hermes),
  локальный `sentence-transformers` с ONNX Runtime.
- Кэш батчей, дедупликация имён, rate limiting, health-чеки с TTL.

**Синхронизация с GitHub:**
- Переход с Contents API на Git Data API ради атомарных multi-file коммитов.
- Нормализация `github_repo` (принимает URL, git-формат, `owner/repo`).
- Merge-стратегии: `last-write-wins`, `local-wins`, `remote-wins`
  с сопоставлением по `product_id` → `barcode` → имени.

**Frontend:**
- Модульная структура JS без фреймворков: `utils`, `api`, `state`, `tabs`,
  и десяток других модулей с чёткими зависимостями.
- Cache-busting через `?v=N`, работа под HA ingress, event delegation
  в динамических списках.
- Модалки `product-picker`, `matcher-batch`, `recipe-picker` — все
  с продуманным UX.

**Логика, которую легко упустить:**
- Разделение «парсер чистый — линковка отдельно» в `services/linker.py`.
- Обработка отсутствующего `barcode` через fallback на `uuid` и имя.
- Pre-restore копии перед восстановлением бэкапа.
- Значительная часть локализации, документации и комментариев в коде.

### Почему DeepSeek

Из нескольких доступных ИИ-ассистентов DeepSeek показал себя как:

- **Внимательный к контексту** — не забывал о решениях, принятых 50 сообщений
  назад, и не предлагал противоречащих подходов.
- **Готовый писать код целиком** — не «вот структура, доделайте сами»,
  а полные файлы с обработкой ошибок, комментариями и типизацией.
- **Способный признать ошибку** — если подход оказывался нерабочим,
  предлагалась альтернатива без попыток оправдать неудачное решение.
- **Терпеливый к итерациям** — многомесячная разработка с постоянными
  правками и разворотом в середине пути — это испытание для любой системы.

Если вы раздумываете, использовать ли ИИ-ассистента для серьёзного проекта —
опыт этого проекта однозначно положительный.

---

## 📚 Проекты, на которых построен Recipe Manager

### Парсер и модель данных рецепта
- [Recipe Manager](https://github.com/thekiwismarthome/Recipe-Manager) by
  [@thekiwismarthome](https://github.com/thekiwismarthome) — идея, структура
  рецепта, дизайн Lovelace-карточки. Наш проект — это самостоятельный
  add-on, вдохновлённый оригинальной интеграцией.

### Импорт из YouTube
- [ha-yt-subs-recipe-addon](https://github.com/ebloved/ha-yt-subs-recipe-addon) by
  [@ebloved](https://github.com/ebloved) — логика скачивания субтитров
  через `yt-dlp` и промпт для Gemini.

### Библиотеки и сервисы

**Python:**
- [FastAPI](https://fastapi.tiangolo.com/) — веб-фреймворк.
- [uvicorn](https://www.uvicorn.org/) — ASGI-сервер.
- [httpx](https://www.python-httpx.org/) и [aiohttp](https://docs.aiohttp.org/) —
  асинхронные HTTP-клиенты.
- [aiofiles](https://github.com/Tinche/aiofiles) — асинхронный файловый ввод/вывод.
- [python-frontmatter](https://github.com/eyeseast/python-frontmatter) — парсинг
  YAML front matter в Markdown.
- [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) — парсинг HTML
  в Recipe Keeper-импорте.
- [recipe-scrapers](https://github.com/hhursev/recipe-scrapers) — извлечение
  рецептов с сайтов.
- [Pillow](https://python-pillow.org/) — обработка изображений.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — скачивание субтитров YouTube.

**Frontend:**
- [html5-qrcode](https://github.com/mebjas/html5-qrcode) — сканер штрих-кодов
  и QR для iOS Safari и Firefox.
- Нативный [BarcodeDetector API](https://developer.mozilla.org/en-US/docs/Web/API/BarcodeDetector) —
  для Chromium-браузеров.

**Опционально:**
- [sentence-transformers](https://www.sbert.net/) — локальные эмбеддинги.
- [ONNX Runtime](https://onnxruntime.ai/) — ускорение инференса на CPU.

**Внешние API:**
- [Google Gemini](https://ai.google.dev/) — генерация рецептов из субтитров
  и валидация связок.
- [OpenFoodFacts](https://world.openfoodfacts.org/) — открытая база продуктов
  по штрих-коду.
- [GitHub API](https://docs.github.com/en/rest) — синхронизация.

**Инфраструктура:**
- [Home Assistant](https://www.home-assistant.io/) — платформа, для которой
  всё это написано.
- [HACS](https://hacs.xyz/) — установка и обновление аддонов.

---

## 💡 Вдохновение и идеи

- **Mealie** — self-hosted менеджер рецептов, показал, что рецепты можно
  хранить локально и удобно.
- **Grocy** — управление продуктами, доказал что inventory можно
  автоматизировать.
- **Recipe Keeper** — коммерческое приложение, задавшее стандарт
  пользовательского опыта в этой нише.

---

## 🐛 Сообщения об ошибках и идеи

Проект развивается благодаря обратной связи. Спасибо всем, кто:

- сообщал о багах через GitHub Issues;
- предлагал улучшения UI и API;
- тестировал новые функции на своих инсталляциях Home Assistant;
- присылал рецепты для проверки каскада матчинга.

Если у вас есть идея или вы нашли проблему — открывайте
[Issue](https://github.com/ebloved/recipe-manager-addon/issues)
или [Pull Request](https://github.com/ebloved/recipe-manager-addon/pulls).

---

## 🤝 Как внести вклад

1. Форкните репозиторий.
2. Создайте ветку: `git checkout -b feature/my-feature`.
3. Внесите изменения.
4. Коммит с понятным сообщением: `git commit -m "feat: add my feature"`.
5. Push: `git push origin feature/my-feature`.
6. Откройте Pull Request с описанием того, что и зачем менялось.

Для крупных изменений сначала откройте Issue — обсудим подход,
чтобы потом не переделывать.

---

## 📜 Лицензия

Проект распространяется под лицензией MIT. См. [LICENSE](LICENSE).

При использовании кода или идей из этого проекта просьба указывать
ссылку на оригинал.

---

## 💛 Отдельное спасибо

- **Сообществу Home Assistant** — за платформу, документацию и десятки
  готовых интеграций, по образцу которых можно учиться.
- **Сообществу OpenFoodFacts** — за открытую базу продуктов. Без неё
  каскад матчинга был бы в разы менее полезен.
- **Разработчикам yt-dlp** — они ведут бесконечную гонку с YouTube
  и продолжают выигрывать.
- **Разработчикам recipe-scrapers** — за поддержку сотен кулинарных сайтов
  с единым интерфейсом.

---

**И вам, если вы читаете этот файл, пользуетесь Recipe Manager и находите
его полезным.** Значит, всё было не зря.