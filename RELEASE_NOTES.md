# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] — Unreleased

Adds **Markdown recipe import** — bring recipes in from `.md` files with YAML
front matter, either by pasting text, loading a file from disk, or fetching a
raw URL (including GitHub raw links).

### Added

- **Markdown import tab** in the *New Recipe* dialog with two modes:
  - **Paste** — paste Markdown text or load a `.md` file from disk.
  - **URL** — fetch a Markdown file from any direct link (e.g. a raw GitHub
    URL). Optionally downloads the image referenced in `image_url` locally.
- **YAML front matter support** for all recipe metadata: title, description,
  tags, courses, categories, collections, cuisine, servings, times, source,
  image, rating, nutrition, notes, and more. See the
  [README](README.md#importing-recipes) for the full field reference.
- **Body parsing fallback** — if a field is missing from the front matter, the
  parser looks for `## Ingredients` / `## Ингредиенты` bullet lists and
  `## Steps` / `## Directions` / `## Method` / `## Шаги` numbered or bulleted
  lists.
- **Timers from text** — durations mentioned in direction steps ("cook for
  15 minutes", "simmer 1 hour 30 minutes") are automatically turned into
  tap-to-start timer chips by the card.
- **Explicit field override** — when calling `recipe_manager/recipes/add`
  with a `markdown_content` payload, any other fields passed in the same
  message take precedence over the parsed values.
- New WebSocket commands:
  - `recipe_manager/import/markdown` — import a single recipe from Markdown
    content.
  - `recipe_manager/import/markdown_url` — fetch a Markdown file from a URL
    and import it.
- New `parse_markdown_recipe()` parser in `importer.py`.
- New helper `async_fetch_markdown()` in `scraper.py` for fetching raw
  Markdown content from a URL.

### Changed

- `recipe_manager/recipes/add` now accepts an optional `markdown_content`
  field. When present, the payload is parsed and merged with any explicit
  fields. The `name` field is now optional on this command when
  `markdown_content` is supplied. Existing callers that pass `name`
  explicitly are unaffected.
- `manifest.json` — added `python-frontmatter>=1.0.0` to `requirements`.

### Frontend

- New **Markdown** tab in the *New Recipe* dialog (requires Recipe Manager
  Card v1.1.0 or newer).

### Upgrade notes

- Home Assistant will install `python-frontmatter` automatically on the first
  start after upgrading. If the dependency fails to install, remove the
  `config/deps/` folder and restart Home Assistant.
- No breaking changes. Existing recipes, WebSocket clients, and automations
  continue to work unchanged.

### Dependencies

- `python-frontmatter>=1.0.0` — YAML front matter parsing.

### Example

A minimal Markdown recipe file:

~~~markdown
---
title: Borsch with beef
tags: [soup, ukrainian, winter]
servings: 4
time: 120
ingredients:
  - name: Beef on the bone
    amount: 500
    unit: g
  - name: Beetroot
    amount: 2
    unit: pcs
---

## Ingredients

- Beef on the bone — 500 g
- Beetroot — 2 pcs

## Steps

1. Cover the beef with cold water and bring to a boil. Simmer for
   **1 hour 30 minutes**.
2. Take out the meat, separate it from the bone, and cut into pieces.
~~~

---

## [1.0.0] — Initial release

First public release of the Recipe Manager Home Assistant integration.

### Added

#### Recipe Storage
- Full recipe data model: name, description, ingredients, directions,
  nutrition, notes, images, tags, courses, categories and collections
- Rating (1–5 stars) and favourites
- UUID-based recipe IDs with creation/update timestamps
- JSON storage via Home Assistant's built-in `Store` class (no external
  database needed)

#### Recipe Scraping
- Import recipes from any major recipe website by URL
- Extracts title, description, ingredients, directions, nutrition, images
  and metadata automatically
- Improved browser-like request headers to work with Cloudflare-protected
  sites
- Falls back to JSON-LD extraction for sites that hide structured data
- Ingredient parser correctly separates amount, unit and name

#### Image Management
- Upload images from the Lovelace card (base64 transfer, saved as WebP)
- Download and cache remote images locally
  (`/config/www/images/recipe_manager/`)
- Images resized to max 400 px and converted to WebP on save

#### Recipe Keeper Import
- Bulk import from a Recipe Keeper HTML export file
- Imports all recipes including images in a single operation

#### Meal Planner
- Weekly meal plan storage with breakfast, lunch, dinner and snack slots
- Get/set plan entries via WebSocket

#### WebSocket API
- Full real-time WebSocket API for the Lovelace card
- Event subscriptions: `recipe_added`, `recipe_updated`, `recipe_deleted`,
  `meal_plan_updated`
- Commands: get all recipes, get recipe, add, update, delete, toggle
  favourite, scrape URL, upload image, download image, get tags,
  get/update meal plan, import Recipe Keeper

#### Tags
- Tags computed on-the-fly from all recipes — no separate tag storage needed

### Installation

See the [README](README.md) for full HACS installation instructions.

> **Also install:** [Recipe Manager Card](https://github.com/thekiwismarthome/Recipe-Manager-Card)
> to get the Lovelace UI frontend.

---

## Legend

- **Added** — new features.
- **Changed** — changes in existing functionality.
- **Deprecated** — soon-to-be removed features.
- **Removed** — removed features.
- **Fixed** — bug fixes.
- **Security** — security fixes and improvements.

[1.1.0]: https://github.com/thekiwismarthome/Recipe-Manager/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/thekiwismarthome/Recipe-Manager/releases/tag/v1.0.0