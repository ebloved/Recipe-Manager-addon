# Recipe Manager for Home Assistant

A Home Assistant custom integration that gives you a full recipe management system — store, search, scrape, and meal-plan your recipes, all inside Home Assistant.

> **This is the backend integration.** To use it you also need the [Recipe Manager Card](https://github.com/thekiwismarthome/Recipe-Manager-Card) frontend, which is installed separately via HACS.

---

## Features

- **Recipe library** — store unlimited recipes with ingredients, directions, nutrition facts, images, notes, tags, courses, categories and collections
- **Web scraping** — import recipes directly from any major recipe website by pasting a URL
- **Markdown import** — import recipes from `.md` files with YAML front matter, either by pasting text, loading a file, or fetching a raw URL (e.g. a GitHub link)
- **Recipe Keeper import** — bulk-import your existing collection from a Recipe Keeper HTML export
- **Meal planner** — plan breakfast, lunch, dinner and snacks across a weekly calendar
- **Image management** — upload images from your device or download and cache remote images locally
- **Shopping list** — add recipe ingredients to a shopping list (works with [Shopping List Manager Card](https://github.com/thekiwismarthome/shopping-list-manager-card))
- **Real-time updates** — WebSocket event stream keeps every dashboard in sync instantly
- **Fully local** — all data stored on your Home Assistant instance, no cloud required

---

## Requirements

- Home Assistant **2024.8.0** or newer
- HACS installed ([hacs.xyz](https://hacs.xyz))

---

## Installation

### Step 1 — Add via HACS

Click the button below to add this repository directly to HACS:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=thekiwismarthome&repository=Recipe-Manager&category=integration)

<details>
<summary>Manual HACS steps</summary>

1. Open HACS in your Home Assistant sidebar
2. Click **Integrations**
3. Click the three-dot menu (top right) → **Custom repositories**
4. Paste `https://github.com/thekiwismarthome/Recipe-Manager` and select category **Integration**
5. Click **Add**, then search for **Recipe Manager** and click **Download**

</details>

### Step 2 — Restart Home Assistant

Go to **Settings → System → Restart** and wait for HA to come back up.

### Step 3 — Add the Integration

Click the button below to add the integration to your Home Assistant:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=recipe_manager)

<details>
<summary>Manual steps</summary>

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Recipe Manager** and click it
3. Follow the setup wizard (no credentials needed — it runs fully locally)

</details>

### Step 4 — Install the Card

Install the [Recipe Manager Card](https://github.com/thekiwismarthome/Recipe-Manager-Card) to get the full UI. See that repo for card installation instructions.

---

## Adding the Card to Your Dashboard

Once both are installed:

1. Go to any dashboard and enter **Edit mode**
2. Click **Add Card** → search for **Custom: Recipe Manager Card**
3. Add it and save

---

## Importing Recipes

### From a website

Paste the URL of a recipe page into the **From URL** tab of the *New Recipe* dialog and click **Fetch**. Recipe Manager extracts the recipe automatically from over 1000 supported sites, with a JSON-LD fallback for the rest.

### From Recipe Keeper

Export your recipes from the Recipe Keeper app (*Menu → Export → Recipe Keeper File*), then upload the resulting `.zip` in the **Import** tab of the *New Recipe* dialog.

### From Markdown

The **Markdown** tab of the *New Recipe* dialog accepts recipes stored as Markdown files with YAML front matter — useful when you generate recipes with an LLM, keep them in a Git repository, or export them from a notes app.

Two modes are available:

- **Paste** — paste the recipe text directly or load a `.md` file from disk.
- **URL** — fetch a Markdown file from any direct link, e.g. a raw GitHub URL:
  `https://raw.githubusercontent.com/<user>/<repo>/main/recipes/borsch.md`

Optionally tick **Download image from front matter locally** to have Recipe Manager fetch the image referenced in `image_url` and store it in `/config/www/images/recipe_manager/`.

#### File format

The file consists of two parts: **YAML front matter** (optional but recommended) and a **Markdown body**. The front matter holds metadata used for search and filtering, while the body holds the human-readable recipe.

~~~markdown
---
title: Borsch with beef
description: Hearty Ukrainian borsch with beef and sour cream.
tags: [soup, ukrainian, winter, beef]
courses: [soup, main]
categories: [ukrainian cuisine, home cooking]
collections: [for winter, festive table]
cuisine: ukrainian
servings: 4
servings_text: 4 servings
prep_time: 20
cook_time: 100
time: 120
source_url: https://example.com/borsch
image_url: https://example.com/images/borsch.jpg
rating: 5
is_favourite: true
ingredients:
  - name: Beef on the bone
    amount: 500
    unit: g
  - name: Beetroot
    amount: 2
    unit: pcs
  - name: Cabbage
    amount: 300
    unit: g
---

## Ingredients

- Beef on the bone — 500 g
- Beetroot — 2 pcs
- Cabbage — 300 g

## Steps

1. Cover the beef with cold water and bring to a boil. Skim the foam and
   simmer for **1 hour 30 minutes** with a bay leaf and a whole onion.
2. Take out the meat, separate it from the bone, and cut into pieces.
3. Shred the beetroot, carrot, and onion. Fry the onion and carrot until
   golden, about **5 minutes**.
4. Add the beetroot and tomato paste, simmer for **10 minutes**.
5. Add the diced potato to the boiling broth and cook for **10 minutes**.
6. Add the shredded cabbage and cook for another **5 minutes**.
7. Add the fried vegetables and meat, season, and simmer for **10 minutes**.
8. Add the minced garlic, remove from heat, and let it rest for **20 minutes**.

## Notes

- Serve with sour cream and fresh herbs.
- Borsch tastes even better the next day.
~~~

#### Front matter fields

| Field | Type | Purpose |
|---|---|---|
| `title` | string | Recipe name. **Required** unless the body starts with `# Heading`. |
| `description` | string | Short description shown in the recipe card. |
| `tags` | list of strings | Primary search and filter key. |
| `courses` | list of strings | Course category (soup, main, dessert…). |
| `categories` | list of strings | Additional categorisation. |
| `collections` | list of strings | User-defined collections (e.g. "for winter"). |
| `cuisine` | string | Cuisine of the world. |
| `category` | string | Single category label. |
| `servings` | integer | Number of servings. |
| `servings_text` | string | Free-form servings label (e.g. "4 servings"). |
| `prep_time` | integer (minutes) | Preparation time. |
| `cook_time` | integer (minutes) | Cooking time. |
| `time` / `total_time` | integer (minutes) | Total time. |
| `source_url` | string | Link to the original source. |
| `image_url` | string | Link to the recipe photo. |
| `rating` | integer 1–5 | Personal rating. |
| `is_favourite` | boolean | Favourite flag. |
| `ingredients` | list | Either list of strings or list of `{name, amount, unit, notes}` objects. |
| `instructions` | list of strings | Optional. If omitted, steps are parsed from the body. |
| `nutrition` | dict | Nutritional info (`calories`, `protein`, `fat`, `carbohydrates`, `fiber`, `sugar`, `sodium`). |
| `notes` | string | Free-form notes. |

#### Body parsing

If a field is not present in the front matter, Recipe Manager falls back to parsing the body:

- **Title** — the first `# Heading` if `title` is missing.
- **Ingredients** — bullet list under `## Ingredients` / `## Ингредиенты`.
- **Instructions** — numbered or bulleted list under `## Steps`, `## Directions`, `## Method`, `## Шаги`, `## Приготовление`.

Instructions can mention durations in plain text ("cook for 15 minutes", "simmer 1 hour 30 minutes") — the recipe card automatically turns them into tap-to-start timers.

---

## Updating

Updates are managed through HACS. When a new version is available you will see a notification in the HACS panel. Click **Update** then restart Home Assistant.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Integration not found after install | Make sure you restarted Home Assistant |
| Recipe scraping fails | The site may block bots — try a different recipe site |
| Markdown import fails | Ensure the file has valid YAML front matter. If importing from a URL, make sure it points to a **raw** Markdown file (GitHub raw links start with `raw.githubusercontent.com`) |
| Markdown import: "python-frontmatter is required" | Home Assistant failed to install the dependency. Remove the `config/deps/` folder and restart HA |
| Images not loading | Check that `/config/www/images/recipe_manager/` exists and is writable |
| Card not appearing | Make sure Recipe Manager Card is also installed via HACS |

---

## Related

- [Recipe Manager Card](https://github.com/thekiwismarthome/Recipe-Manager-Card) — the Lovelace frontend UI
- [Shopping List Manager Card](https://github.com/thekiwismarthome/shopping-list-manager-card) — optional shopping list integration

---

## License

MIT License — see [LICENSE](LICENSE)