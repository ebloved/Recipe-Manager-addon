# Магазины: чек-лист проверки на dev

**Стенд:** локальный тестовый домен (контейнер `recipe-manager`, `:8099`).  
**Prod не трогаем** до подтверждения dev.

## 1. OAuth ВкусВилла

1. Войти в dev под своим Google-аккаунтом.
2. Открыть вкладку **🏪 Магазины**.
3. Нажать **Подключить** у ВкусВилла.
4. Пройти логин/согласие ВкусВилла.
5. Вернуться в RM — статус должен стать **🟢 Подключён**.
6. Нажать **Проверить** — должно вернуться `OAuth и MCP работают`.

Проверка в БД:

```bash
docker exec recipe-manager python -c \
  "import sqlite3; c=sqlite3.connect('/data/rm.sqlite3'); \
   print(c.execute('select owner_id, store_id, access_token_enc is not null, refresh_token_enc is not null, expires_at from user_store_credentials').fetchall())"
```

Токены должны лежать в `*_enc`, не в открытом виде.

## 2. Fast path (SKU уже известен)

1. Добавить в список покупок товар, для которого уже есть `product_offers`.
2. Нажать **🛒 Собрать корзину**.
3. Ожидаемо: ссылка `https://vkusvill.ru/mobile?basket&share=...`,
   `matched_items[].status = "linked_by_sku"`.

Проверено вручную: OAuth + MCP + `cart_link_create` работают.
Slow path проверен на 4 позициях: 3 сматчились, 1 ушёл в warnings
(«белый хлеб без корки» — в кандидатах не было подходящего товара).

## 3. Slow path (SKU нет)

1. Добавить товар без кеша, например «Сыр» или «Мука».
2. Нажать **🛒 Собрать корзину**.
3. Ожидаемо: MCP search → LLM-матчинг через `call_llm_cascade` →
   `matched_items[].status = "matched_by_llm"`, SKU сохраняется в `product_offers`.

Если своих LLM-ключей нет, используется admin Gemini; он может отвечать
дольше 2 минут. В `matcher.py` стоит таймаут `VKUSVILL_LLM_TIMEOUT=120`.
Для быстрой проверки лучше добавить свой Custom/Orca-ключ в Кабинете.

## 4. Refresh token

Токен ВкусВилла живёт ограниченное время. При истечении
`get_valid_access_token` обновляет его через refresh token и сохраняет
новый в SQLite. Проверено вручную: refresh работает.

## 5. Отключение

Кнопка **Отключить** вызывает revoke (если VV поддерживает) и удаляет
запись из `user_store_credentials`.

## 6. Ограничения текущей версии

- В HA-аддоне `owner_id = "family"` для всех HA-учёток — это согласованное
  решение: одна инсталляция = один владелец.
- В standalone OAuth `owner_id` — Google `sub`, токены per-user.
- TTL для `product_offers` пока не задан: SKU переиспользуется до ошибки
  MCP; при ошибке запись удаляется и позиция уходит в slow path.
- Персональные LLM-ключи перенесены в SQLite (`user_llm_configs`) и
  шифруются; `users.json` остаётся для профилей и allowlist.
