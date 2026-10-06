"""Пакет парсеров Recipe Manager.

Содержит:
  - importer.py — парсер Recipe Keeper HTML и Markdown-рецептов

Пакет сознательно минимален: только чистые парсеры без доступа к stores
или внешним сервисам. Связывание (product.barcode → product_id) делается
в `services/linker.py`.
"""