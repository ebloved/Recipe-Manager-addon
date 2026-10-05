# Recipe Manager

Home Assistant add-on that combines two recipe workflows in one place:

- **YouTube Shorts → recipe** — paste a link, the add-on downloads subtitles
  with `yt-dlp` and uses Google Gemini to turn them into a structured Markdown
  recipe.
- **Markdown import** — bring in recipes stored as `.md` files with YAML
  front matter, either by pasting text or fetching them from a raw URL
  (e.g. a GitHub link).
- **Recipe library** — a built-in web UI, served through HA ingress, that
  lets you browse, search, and manage all your recipes without leaving the
  Home Assistant sidebar.

Everything is local: recipes live in `/data/recipes.json` inside the add-on,
and nothing is sent anywhere except the YouTube subtitle request and the
Gemini API call for recipe generation.

---

## Features

- **YouTube Shorts importer** — paste any Shorts (or regular YouTube) URL,
  download auto-generated subtitles, and generate a recipe in Markdown with
  YAML front matter.
- **Gemini-powered structuring** — the add-on sends the subtitle transcript
  to Google Gemini along with a template and gets back a clean, structured
  recipe.
- **Markdown importer** — import recipes from `.md` files, either by pasting
  the content or fetching a raw URL.
- **Built-in web UI** — served via Home Assistant ingress, accessible from
  the sidebar. Search by name, tags, courses, categories, and ingredients.
- **Recipe library** — persistent storage in `/data/recipes.json`, survives
  add-on restarts and updates.
- **Multi-language subtitles** — configurable subtitle language preference
  (defaults to `ru.*`).

---

## Installation

### Step 1 — Add the repository to Home Assistant

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https://github.com/dnvorobev/recipe-manager-addon)

<details>
<summary>Manual steps</summary>

1. Go to **Settings → Add-ons → Add-on Store**.
2. Click the three-dot menu (top right) → **Repositories**.
3. Paste `https://github.com/dnvorobev/recipe-manager-addon` and click
   **Add**.
4. Close the dialog and refresh the Add-on Store page.

</details>

### Step 2 — Install the add-on

1. In the Add-on Store, find **Recipe Manager** and click it.
2. Go to the **Info** tab and click **Install**.
3. Wait for the add-on to build and start (may take 2–5 minutes on first
   install).

### Step 3 — Configure

Open the **Configuration** tab and fill in at least the Gemini API key:

| Option | Required | Description |
|---|---|---|
| `gemini_api_key` | ✅ | Google Gemini API key. Get one at [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey). |
| `gemini_models` | | Comma-separated list of models to try, in order. Defaults to `gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash`. |
| `gemini_proxy` | | Optional HTTP(S) proxy for Gemini requests. |
| `sub_langs` | | Subtitle language preference for `yt-dlp`. Defaults to `ru.*`. Use `en.*` for English, `.*` for any. |
| `cookies_file` | | Optional path to a `cookies.txt` file (for age-restricted or private videos). Must be inside the add-on container. |
| `log_level` | | Uvicorn log level: `trace`, `debug`, `info`, `notice`, `warning`, `error`, `fatal`. Defaults to `info`. |

Click **Save**, then go to the **Info** tab and click **Start**.

### Step 4 — Open the UI

After the add-on starts, click **Open Web UI** on the Info tab, or find
**Recipe Manager** in the Home Assistant sidebar.

---

## Usage

### Import a recipe from YouTube Shorts

1. Open the **YouTube** tab.
2. Paste a link to a Shorts video (or a regular YouTube video) into the
   input field.
3. Click **1. Download subtitles**. The add-on runs `yt-dlp` to fetch the
   auto-generated subtitles. This may take 10–60 seconds depending on the
   video.
4. Click **2. Generate recipe**. The subtitles are sent to Gemini, which
   returns a structured Markdown recipe. The result appears in the preview
   box below.
5. Review the generated Markdown, edit if needed, and click **Save to
   recipes**.

The recipe is now in your library and searchable from the **Recipes** tab.

### Import a recipe from Markdown

1. Open the **Import** tab.
2. Either:
   - Paste a raw URL to a `.md` file (e.g. a GitHub raw link) and click
     **Fetch and save**, or
   - Paste Markdown content directly into the textarea and click **Save
     recipe**.

The parser understands YAML front matter and falls back to parsing
`## Ingredients` / `## Steps` sections from the body if the front matter is
missing.

#### Markdown file format

~~~markdown
---
title: Borsch with beef
description: Hearty Ukrainian borsch with beef and sour cream.
tags: [soup, ukrainian, winter, beef]
courses: [soup, main]
categories: [ukrainian cuisine, home cooking]
cuisine: ukrainian
servings: 4
prep_time: 20
cook_time: 100
time: 120
source_url: https://example.com/borsch
image_url: https://example.com/images/borsch.jpg
rating: 5
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

Supported front matter fields:

| Field | Type | Purpose |
|---|---|---|
| `title` | string | Recipe name. **Required** unless the body starts with `# Heading`. |
| `description` | string | Short description. |
| `tags` | list of strings | Primary search key. |
| `courses` | list of strings | Course category. |
| `categories` | list of strings | Additional categorisation. |
| `collections` | list of strings | User-defined collections. |
| `cuisine` | string | Cuisine of the world. |
| `servings` | integer | Number of servings. |
| `servings_text` | string | Free-form servings label. |
| `prep_time` | integer (minutes) | Preparation time. |
| `cook_time` | integer (minutes) | Cooking time. |
| `time` / `total_time` | integer (minutes) | Total time. |
| `source_url` | string | Link to the original source. |
| `image_url` | string | Link to the recipe photo. |
| `rating` | integer 1–5 | Personal rating. |
| `ingredients` | list | Either list of strings or list of `{name, amount, unit, notes}` objects. |
| `instructions` | list of strings | Optional. If omitted, steps are parsed from the body. |
| `nutrition` | dict | Nutritional info. |
| `notes` | string | Free-form notes. |

### Browse and search recipes

1. Open the **Recipes** tab.
2. Use the search box at the top to filter by name, tags, courses,
   categories, and ingredients.
3. Click any recipe card to open it in a detail view. From there you can
   delete the recipe or toggle a raw-Markdown view.

---

## Data storage

Recipes are stored in `/data/recipes.json` inside the add-on container.
The `/data` directory is persistent — it survives add-on restarts, updates,
and reinstalls. To back up your recipes, use the Home Assistant **Backups**
feature (the add-on's `/data` folder is included automatically), or copy the
file out manually.

---

## How it works

The add-on runs a small FastAPI server inside its container. Home Assistant
proxies it through ingress, so the UI is available at
`/api/hassio_ingress/<token>/` without any additional port or reverse-proxy
configuration.

**Endpoints:**

| Endpoint | Purpose |
|---|---|
| `POST /api/download` | Download subtitles for a YouTube video. |
| `POST /api/generate-recipe` | Send subtitles to Gemini, get Markdown back. |
| `GET /api/recipes` | List all recipes (supports `?q=` search). |
| `GET /api/recipes/{id}` | Get a single recipe. |
| `POST /api/recipes` | Create a recipe from Markdown or explicit fields. |
| `POST /api/recipes/import-url` | Fetch a Markdown file from a URL and save it. |
| `PATCH /api/recipes/{id}` | Update a recipe. |
| `DELETE /api/recipes/{id}` | Delete a recipe. |
| `GET /api/tags` | List all unique tags. |
| `GET /api/health` | Health check. |

---

## Requirements

- Home Assistant OS or Supervised (add-ons are not available on Container
  or Core installations).
- Google Gemini API key ([get one free](https://aistudio.google.com/app/apikey)).
- Internet access from the add-on container for YouTube subtitle download and
  Gemini API calls.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `GEMINI_API_KEY not set` | Open the add-on Configuration tab, paste your API key, save, and restart the add-on. |
| Subtitle download fails | Check the add-on logs. Some videos have no auto-generated subtitles — try a different video. |
| Gemini returns "all models unavailable" | You may have hit the free tier rate limit. Wait a few minutes or add a proxy. |
| Web UI returns 404 | Make sure the add-on is started and the `ingress_port` in `config.yaml` matches the port in `run.sh` (default `8099`). |
| Recipes disappeared after update | They should not. Check `/data/recipes.json` in the container via the add-on's terminal. If the file is missing, restore from a HA backup. |

### Viewing add-on logs

**Settings → Add-ons → Recipe Manager → Log** tab. Errors from `yt-dlp`,
`httpx`, and FastAPI all show up there.

---

## Related projects

This add-on bundles logic from two sources:

- **Recipe Manager integration** — the Markdown parser and recipe data model
  come from the [Recipe Manager](https://github.com/thekiwismarthome/Recipe-Manager)
  Home Assistant custom integration by
  [@thekiwismarthome](https://github.com/thekiwismarthome).
- **YT Subs → Recipe add-on** — the YouTube subtitle downloader and Gemini
  prompt come from [ha-yt-subs-recipe-addon](https://github.com/ebloved/ha-yt-subs-recipe-addon)
  by [@ebloved](https://github.com/ebloved).

---

## License

MIT License — see [LICENSE](LICENSE)