# ADR-002: YouTube-транскрипты через Apify

Дата: 2026-10-31
Статус: принято
Заменяет: подход из `YOUTUBE_IMPORT_ISSUE.md` (yt-dlp + cookies)

## Контекст

`yt-dlp` с серверного IP стабильно упирается в bot-check YouTube
(`Sign in to confirm you're not a bot`). Cookies требуют ручного обновления,
живут недели–месяцы и привязаны к аккаунту. PO-token provider и прокси
добавляют инфраструктуру и не дают гарантий.

## Решение

Единственный источник транскриптов — Apify Actor
`automationnation/youtube-transcript-scraper`.

- `POST /api/download` → `run-sync-get-dataset-items` Apify → текст.
- Гибкий парсер: `transcript_text` → `transcript` → `text` → `segments`.
- Кэш в SQLite (`youtube_transcripts`) по `video_id` — повторный импорт
  не тратит кредиты.
- `GET /api/youtube/status` → `{enabled, quota}` для всех;
  `GET /api/youtube/limits` → детали для админа.
- Блокировка при `used >= limit * APIFY_STOP_RATIO` (по умолчанию 90%):
  кнопки импорта скрываются, API отдаёт 503.
- UI: в Кабинете блок «📊 Статус Apify» (прогресс-бар, зелёный < 50%,
  жёлтый 50–80%, красный > 80%).

`yt-dlp`, Deno и cookies удалены из образов и зависимостей.

## Цена

$1.50 за 1 000 транскриптов (free $5/мес ≈ 3 300 транскриптов).
Фактический расход проверен: один Shorts = **$0.0016**.

## Последствия

Плюсы:
- работает с облачного IP без cookies и прокси;
- нет ручного обслуживания;
- кэш и лимиты снижают расход.

Минусы / риски:
- зависимость от Apify и конкретного актора;
- смена схемы ответа актора — парсер уже терпимый, но потребует проверки;
- при исчерпании $5 импорт отключается до следующего месяца или апгрейда;
- транскрипты уходят третьей стороне (Apify), это нужно учитывать в политике.

## Конфигурация

```env
APIFY_TOKEN=...
APIFY_ACTOR_ID=automationnation/youtube-transcript-scraper
APIFY_QUOTA_LIMIT_USD=5
APIFY_STOP_RATIO=0.9
FEATURE_YOUTUBE_IMPORT=true
```

## Проверено

- Реальный импорт `M43PoCK6eZQ`: 3 103 символа, `language=ru`,
  title/channel получены.
- Повторный вызов — `cached=true`, расход не увеличился.
- LLM-пайплайн на этом транскрипте отработал (custom LLM).
- Блокировка при достижении порога: `blocked=true`, `/api/download` → 503.
