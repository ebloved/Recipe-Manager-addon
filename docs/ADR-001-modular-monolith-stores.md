# ADR-001: модульный монолит для магазинов (RM + ВкусВилл)

**Статус:** принято 2026-10-31  
**Контекст:** Recipe Manager (HA add-on + standalone), MCP Connector ВкусВилла.

## Решение

Интеграцию с магазинами держим **внутри RM**, а не отдельным сервисом:

```text
app/
  db.py                         # SQLAlchemy 2.0 + aiosqlite
  integrations/stores/
    vkusvill/
      oauth.py                  # OAuth 2.0 + PKCE, refresh, revoke
      mcp_client.py             # JSON-RPC к mcp.vkusvill.ru
      client.py                 # search / details / barcode / cart
      matcher.py                # LLM-матчинг через call_llm_cascade
      cart.py                   # fast path + slow path + merge
      models.py
  stores/
    db_models.py                # shopping_items, product_offers,
                                # user_store_credentials, oauth_states
    shopping.py                 # SQLite + read cache
    store_credentials.py        # шифрованные токены per-user
    product_offers.py           # кеш SKU per-user/store
  routes/
    stores.py                   # /api/stores/*
```

`mcp_service` остаётся отдельным проектом как optional-adapter для внешних
потребителей. RM его не вызывает: для HA-аддона один контейнер важнее
микросервисной чистоты.

## Почему не отдельный сервис

1. **Per-user LLM-каскад** уже реализован в `services/llm_cascade.py`
   (Custom → Orca → Gemini → admin Gemini → Hermes). Отдельный MCP либо
   дублирует каскад, либо получает один провайдер и теряет fallback.
2. **HA-аддон** должен оставаться одним контейнером; второй сервис
   усложняет установку и сеть.
3. **Секреты** (LLM-ключи и OAuth-токены) не покидают RM. В отдельном
   сервисе их пришлось бы передавать по сети и держать в памяти MCP.
4. **Мульти-магазинность** не страдает: адаптеры лежат в
   `integrations/stores/<store>/`, общий интерфейс можно выделить позже.

## Безопасность

- OAuth: `authorization_code` + PKCE (`S256`), `state` хранится на сервере
  в `oauth_states` (не в cookie), TTL 10 минут.
- Токены магазинов: SQLite, поля `*_enc`, Fernet-ключ производный от
  `SECRET_KEY` с отдельным контекстом (`:store-credentials`).
- LLM-ключи перенесены в SQLite (`user_llm_configs`) и шифруются
  отдельным Fernet-ключом. `users.json` остаётся только для профилей,
  ролей и allowlist; ключи из него удаляются после миграции.
- Все запросы к `shopping_items`, `product_offers`,
  `user_store_credentials` фильтруются по `owner_id`.
- В HA-аддоне `owner_id = "family"` для всех HA-учёток: по решению
  заказчика аддон считается одной инсталляцией на одну семью/владельца.
  В standalone OAuth `owner_id` — Google `sub`, поэтому там токены
  действительно per-user.
- Cookie сессии: `HttpOnly`, `SameSite=Lax`, `Secure` при HTTPS.

## Данные

- `shopping_items` — список покупок (миграция из `shopping_list.json`).
- `product_offers` — кеш SKU:
  `UNIQUE(owner_id, store_id, item_key)`,
  `item_key = product:<rm_product_id>` или `name:<normalized_name>`.
- `user_store_credentials` — per-user OAuth-токены.
- `user_llm_configs` — персональные LLM-ключи (JSON, Fernet).
- `oauth_states` — короткоживущее состояние OAuth.

JSON-файлы не удаляются: перед миграцией копируются в
`/data/backups/pre_sqlite_<timestamp>/`.

## Про UUID ВкусВилла

MCP не возвращает UUID товара. В ответах есть:

- `id` (int) — стабильный идентификатор товара, используем как `sku`;
- `slug` (str) — человекочитаемый, может меняться;
- UUID только у картинок.

Поэтому кеш хранит int `id`, а `item_key` строится из `product_id` RM
или нормализованного имени.

## Последствия

- Один деплой для dev/prod/HA.
- Меньше сетевых и конфигурационных сущностей.
- Ответственность за таймауты и изоляцию ошибок внешних API — на RM.
- При появлении внешних потребителей MCP можно выделить обратно,
  переиспользовав `integrations/stores/vkusvill` как пакет.
