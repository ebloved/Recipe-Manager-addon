# YouTube-импорт: проблема и варианты решения

> **Статус:** решено — переходим на Apify.
> Актуальное решение и конфигурация: `docs/ADR-002-youtube-apify.md`.
> Этот документ оставлен как история диагностики.

Дата: 2026-10-31
Версия: 3.8.6 (dev)
Среда: локальный dev-стенд (Docker, standalone)

## 1. Что должно работать

Пайплайн импорта рецепта из YouTube Shorts:

```text
URL → POST /api/download (yt-dlp: субтитры + метаданные)
    → POST /api/generate-recipe (LLM: Markdown-рецепт)
    → POST /api/recipes (linker, нормализация, сохранение)
```

## 2. Симптом

`/api/download` стабильно возвращает 502. Пример для
`https://youtube.com/shorts/M43PoCK6eZQ`:

```text
ERROR: [youtube] M43PoCK6eZQ: Sign in to confirm you're not a bot.
This helps protect our community. Use --cookies-from-browser or --cookies
for the authentication.
```

До v3.8.3 было ещё:

```text
WARNING: [youtube] No supported JavaScript runtime could be found.
Only deno is enabled by default...
```

## 3. Диагностика (что проверено)

| Проверка | Результат |
|---|---|
| `yt-dlp 2026.10.26` | установлен, работает |
| Deno как JS runtime | добавлен (2.9.8), предупреждение EJS ушло |
| player_client: `android`, `ios`, `tv`, `web_safari`, `mweb`, `android_vr`, `web_embedded`, `tv_embedded` | у всех `Sign in to confirm you're not a bot` |
| `youtube-transcript-api` | `RequestBlocked`: YouTube блокирует IP |
| `r.jina.ai` (обход) | страница отдаётся, транскрипта нет (401/без данных) |
| oEmbed (`/oembed?url=...`) | **работает**: title, author, thumbnail |
| Сторонние transcript-сервисы (kome.ai и др.) | 522 / ошибки / требуют токен |
| SozAI (`sozai.app/transcript/<slug>/`) | транскрипт доступен в JSON-LD `about.transcript` |

Вывод: проблема не в коде и не в yt-dlp, а в **bot-check YouTube для IP
датацентра**. oEmbed проходит, потому что не требует плеера.

## 4. Причина

1. YouTube требует «proof of origin» (PO token) и/или cookies для
   воспроизведения/субтитров с «подозрительных» IP.
2. IP сервера — облачный/датацентровый, поэтому YouTube включает
   bot-check независимо от выбранного player client.
3. `yt-dlp` без cookies и без PO token не может получить субтитры.

Это не регрессия Recipe Manager: так ведёт себя YouTube для серверных IP
без аутентификации.

## 5. Что уже сделано (dev, v3.8.6)

- **Deno** добавлен в оба образа (`Dockerfile`, `standalone/Dockerfile`),
  `yt-dlp` запускается с `--js-runtimes deno`.
- Понятные ошибки: при bot-check API возвращает подсказку про cookies,
  а не сырой stderr.
- **UI для cookies** без консоли и перезапуска:
  - `GET/POST/DELETE /api/youtube/cookies`;
  - `POST /api/youtube/cookies/text` — вставка текста (мобильные);
  - файл `/data/youtube_cookies.txt`, права `600`, бэкап `.bak`,
    предупреждение при возрасте > 30 дней;
  - доступ только администратору.
- **Обложка из YouTube не подставляется**: `image_url` принудительно
  `null`, фото добавляется вручную в редакторе.
- **Feature flag**: `youtube_import_enabled` / `FEATURE_YOUTUBE_IMPORT`
  (по умолчанию `true`). При `false` вкладка скрывается, все
  YouTube-эндпоинты отдают 503.
- Добавлен рецепт `bd3d3dccd9034ad49900f57ab9f638f7`
  («Куриные бёдра в сливках с пармезоном») через публичный транскрипт —
  как разовый обход, не как интеграция.

## 6. Варианты решения

### A. Cookies из реального браузера (основной)

- Пользователь экспортирует `cookies.txt` (Netscape) и загружает в UI.
- Плюсы: штатный путь yt-dlp, работает без прокси, уже реализовано.
- Минусы: cookies привязаны к аккаунту; живут недели–месяцы; умирают при
  смене пароля/2FA/выходе; требуют ручного обновления; риск утечки.
- Стоимость: 0. Поддержка: низкая, но регулярная.

### B. Прокси/VPN с «чистым» IP

- Плюсы: не нужен аккаунт; помогает и другим интеграциям.
- Минусы: платно; нестабильно; YouTube банит пулы; нужен резидентный
  прокси; латентность.
- Стоимость: от ~$5–15/мес за резидентный трафик.

### C. PO token provider (bgutil-ytdlp-pot-provider)

- Отдельный сервис, выдающий PO tokens для yt-dlp.
- Плюсы: снижает bot-check без cookies.
- Минусы: ещё один контейнер/зависимость; YouTube меняет правила;
  не гарантия; нужен JS runtime (есть).
- Стоимость: 0 (self-hosted), поддержка средняя.

### D. Внешний transcript API (платный)

- Плюсы: стабильность, SLA.
- Минусы: деньги, зависимость от вендора, приватность.
- Стоимость: обычно $10–50/мес.

### E. SozAI как fallback (парсинг публичных страниц)

- Транскрипт лежит в JSON-LD `about.transcript`; есть markdown-твин
  `/transcript/<slug>/index.md`.
- Плюсы: бесплатно, работает с серверного IP, уже проверено.
- Минусы: не API; нет поиска по `videoId` (только по названию/каналу);
  покрытие неполное (~29.5k транскриптов); машинное качество; возможны
  блокировки; чужой контент → нужна атрибуция и кеш.
- Стоимость: 0. Поддержка: средняя (хрупкий парсинг).

### F. Отказаться от фичи

- `youtube_import_enabled: false` — вкладка исчезает, API 503.
- Остаются: импорт с сайта, Markdown, вручную.
- Стоимость: 0. Поддержка: 0.

## 7. Рекомендация

1. **Основной путь** — cookies (A), т.к. уже реализовано и не требует
   инфраструктуры. Обновление — через UI, без консоли.
2. **Опционально** — PO token provider (C), если cookies окажутся
   неудобны.
3. **SozAI (E)** — только как явно включаемый fallback с кешем,
   rate limit, проверкой videoId и атрибуцией. По умолчанию выключен.
4. **Feature flag (F)** — оставить: позволяет выключить фичу без релиза.

Не рекомендую делать SozAI основным источником: это парсинг чужого сайта
без API и гарантий.

## 8. Что нужно от владельца/архитектора

- Решение: включаем cookies (A), прокси (B), PoToken (C), fallback (E)
  или выключаем фичу (F)?
- Если A: кто и как часто обновляет cookies, где храним (уже `/data`,
  права 600), нужен ли срок жизни/ротация.
- Если E: допустима ли зависимость от `sozai.app` и атрибуция?
- Нужен ли автопостинг рецептов из YouTube или достаточно ручного
  подтверждения в UI.

## 9. Файлы и коммиты

- `app/routes/youtube.py` — эндпоинты, cookies, feature flag, ошибки.
- `app/services/ytdlp.py` — запуск yt-dlp, Deno, cookies.
- `app/static/js/youtube.js` — UI cookies и скрытие вкладки.
- `app/static/index.html` — блок 🍪, справка.
- `app/config.py` — `FEATURE_YOUTUBE_IMPORT`, `COOKIES_FILE`.
- `config.yaml`, `run.sh` — опция `youtube_import_enabled`.
- Коммиты: `45c6d31`, `77e15ef`, `9d271fd`, `51c8313`.
