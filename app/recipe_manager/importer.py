"""Recipe Manager parser.

Содержит два независимых парсера:

1. **Recipe Keeper HTML** — парсер экспорта из приложения Recipe Keeper
   (.rkeeper / .zip). Не изменялся.

2. **Markdown recipe** — парсер .md-файлов с YAML front matter.

Ключевое дополнение в Markdown-парсере:
  Ингредиенты могут содержать опциональный блок `product` с полями
  `uuid` (локальный ID продукта) и `barcode` (GTIN из OpenFoodFacts).
  Парсер возвращает эти поля в результирующем dict ингредиента, но
  НЕ ходит в ingredients_store — связывание с базой продуктов делает
  отдельный слой (services/linker.py). Это сохраняет парсер чистым
  и тестируемым.

Формат, который понимает Markdown-парсер:

    ---
    title: Греческий салат
    servings: 2
    ingredients:
      - name: Греческий йогурт 2%
        amount: 200
        unit: г
        product:
          uuid: 3f8a12bc-...
          barcode: 4607123456789
      - name: Огурец
        amount: 2
        unit: шт
    ---

    ## Ингредиенты
    - Греческий йогурт 2% — 200 г
    - Огурец — 2 шт

    ## Шаги
    1. Нарезать.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)


# ===========================================================================
# Публичный API: Recipe Keeper
# ===========================================================================

def parse_recipe_keeper_html(
    html_content: str,
    images: Optional[Dict[str, bytes]] = None,
) -> List[Dict[str, Any]]:
    """Parse Recipe Keeper HTML and return a list of recipe dicts.

    html_content — the HTML text from recipebook.html (or equivalent)
    images       — optional map of filename → raw bytes for embedding photos.
                   When omitted, recipes include ``_image_filename`` (the src
                   reference from the HTML) so the caller can supply images
                   separately (e.g. uploaded one-by-one from the browser).
    """
    if images is None:
        images = {}

    try:
        from bs4 import BeautifulSoup  # type: ignore[import]
    except ImportError as exc:
        raise ValueError(
            "BeautifulSoup4 is required for Recipe Keeper import"
        ) from exc

    soup = BeautifulSoup(html_content, "html.parser")

    # Strategy 1: standard Recipe Keeper class
    containers = soup.find_all(class_="recipe-details")
    _LOGGER.info("Recipe Keeper import: found %d containers with class='recipe-details'", len(containers))

    # Strategy 2: any block that contains a recipe-name child
    if not containers:
        containers = [
            el for el in soup.find_all(["article", "section", "div"])
            if el.find(class_=re.compile(r"recipe-name", re.I))
        ]
        _LOGGER.info("Recipe Keeper import: fallback found %d containers with recipe-name child", len(containers))

    if not containers:
        sample = html_content[:1000].replace("\n", " ")
        _LOGGER.warning("Recipe Keeper import: no recipe containers found. HTML sample: %s", sample)
        raise ValueError(
            "No recipe containers found — check this is a valid Recipe Keeper export"
        )

    _LOGGER.info(
        "Recipe Keeper import: first container HTML sample: %s",
        str(containers[0])[:600].replace("\n", " "),
    )

    recipes: List[Dict[str, Any]] = []
    for container in containers:
        try:
            recipe = _parse_recipe_container(container, images)
            if recipe and recipe.get("name"):
                recipes.append(recipe)
            elif recipe:
                _LOGGER.warning("Recipe Keeper import: skipping container with no name")
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Recipe Keeper import: skipping unparseable container: %s", exc)

    _LOGGER.info(
        "Parsed %d recipes from Recipe Keeper HTML (%d images available)",
        len(recipes),
        len(images),
    )
    return recipes


def parse_recipe_keeper_bytes(
    data: bytes,
) -> Tuple[List[Dict[str, Any]], Dict[str, bytes]]:
    """Parse a .rkeeper ZIP and return (recipes, images).

    recipes  — list of recipe dicts ready for storage.add_recipe()
    images   — map of original filename → raw image bytes
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("Not a valid .rkeeper archive (bad ZIP)") from exc

    with zf:
        html_file = next(
            (n for n in zf.namelist() if n.endswith(".html")), None
        )
        if not html_file:
            raise ValueError("No HTML file found inside .rkeeper archive")

        html_content = zf.read(html_file).decode("utf-8", errors="replace")

        image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
        images: Dict[str, bytes] = {
            n: zf.read(n)
            for n in zf.namelist()
            if any(n.lower().endswith(ext) for ext in image_extensions)
        }

    recipes = parse_recipe_keeper_html(html_content, images)
    return recipes, images


# ===========================================================================
# Публичный API: Markdown
# ===========================================================================

def parse_markdown_recipe(content: str) -> Dict[str, Any]:
    """Parse a Markdown recipe with YAML front matter into a recipe dict.

    Возвращает dict, пригодный для storage.add_recipe().

    Ингредиенты могут содержать (опционально) вложенный блок product:

        ingredients:
          - name: Греческий йогурт 2%
            amount: 200
            unit: г
            product:
              uuid: 3f8a12bc-...      # локальный ID (опционально)
              barcode: 4607123456789  # GTIN (опционально)

    Парсер возвращает этот блок как есть — он не ходит в ingredients_store.
    Связывание (product_id) выполняется на уровне routes/services, где
    доступен store. Это сохраняет чистоту парсера.

    При ошибке YAML возвращает детальную диагностику с номером строки
    и подсказкой про кавычки.
    """
    try:
        import frontmatter  # type: ignore[import]
    except ImportError as exc:
        raise ValueError(
            "python-frontmatter is required for Markdown import — "
            "add 'python-frontmatter>=1.0.0' to requirements"
        ) from exc

    # --- Парсинг front matter с детальной диагностикой ----------------
    try:
        post = frontmatter.loads(content)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(_format_yaml_error(content, exc)) from exc

    metadata: Dict[str, Any] = dict(post.metadata or {})
    body: str = post.content or ""

    # --- Name ---
    name = metadata.get("title") or metadata.get("name")
    if not name:
        m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if m:
            name = m.group(1).strip()
    if not name:
        raise ValueError(
            "No recipe title found: add 'title:' to YAML front matter "
            "or start the file with '# Название'"
        )

    # --- Ingredients ---
    ingredients = _parse_md_ingredients(metadata, body)

    # --- Instructions ---
    instructions = _parse_md_instructions(metadata, body)

    # --- Times ---
    prep_time = _parse_time(str(metadata["prep_time"])) if metadata.get("prep_time") else None
    cook_time = _parse_time(str(metadata["cook_time"])) if metadata.get("cook_time") else None

    total_time = None
    for key in ("total_time", "time"):
        if metadata.get(key):
            total_time = _parse_time(str(metadata[key]))
            if total_time is not None:
                break

    # --- Servings ---
    servings_text = metadata.get("servings_text")
    servings: Optional[int] = None
    raw_servings = metadata.get("servings")
    if raw_servings is not None:
        if isinstance(raw_servings, int):
            servings = raw_servings
            if not servings_text:
                servings_text = str(raw_servings)
        else:
            m = re.search(r"\d+", str(raw_servings))
            if m:
                servings = int(m.group())
                if not servings_text:
                    servings_text = str(raw_servings)

    # --- Lists ---
    tags = _to_str_list(metadata.get("tags"))
    courses = _to_str_list(metadata.get("courses"))
    categories = _to_str_list(metadata.get("categories"))
    collections = _to_str_list(metadata.get("collections"))

    # --- Nutrition ---
    nutrition = metadata.get("nutrition")
    if not isinstance(nutrition, dict):
        nutrition = None

    return {
        "name": str(name).strip(),
        "description": metadata.get("description") or metadata.get("notes"),
        "image_url": metadata.get("image_url") or metadata.get("image"),
        "source_url": metadata.get("source_url") or metadata.get("source"),
        "ingredients": ingredients,
        "instructions": instructions,
        "prep_time": prep_time,
        "cook_time": cook_time,
        "total_time": total_time,
        "servings": servings,
        "servings_text": servings_text,
        "cuisine": metadata.get("cuisine"),
        "category": metadata.get("category"),
        "tags": [t.lower() for t in tags],
        "courses": courses,
        "categories": categories,
        "collections": collections,
        "nutrition": nutrition,
        "notes": metadata.get("notes"),
        "rating": metadata.get("rating"),
        "is_favourite": bool(metadata.get("is_favourite", False)),
    }


# ===========================================================================
# YAML error formatter
# ===========================================================================

def _format_yaml_error(content: str, exc: Exception) -> str:
    """Строит человекочитаемое сообщение об ошибке YAML.

    Извлекает номер строки и колонки, показывает проблемную строку,
    подчёркивает позицию и даёт подсказку.
    """
    msg = str(exc)

    line_no: Optional[int] = None
    col_no: Optional[int] = None
    m = re.search(r"line (\d+), column (\d+)", msg)
    if m:
        line_no = int(m.group(1))
        col_no = int(m.group(2))

    fm_lines = content.splitlines()

    hint = (
        "Проверьте строку на спецсимволы: ':', '#', '{', '}', '[', ']', ',', "
        "'&', '*', '!', '|', '>', '%', '@'. Если значение содержит такие символы — "
        "оберните его в двойные кавычки: ключ: \"значение: с двоеточием\"."
    )

    detail = ["Invalid YAML front matter."]
    if line_no is not None:
        detail.append(f"Строка {line_no}" + (f", колонка {col_no}" if col_no else "") + ".")
        # front matter в content идёт после первого '---', поэтому +1 к индексу
        idx = line_no
        if 0 <= idx < len(fm_lines):
            bad = fm_lines[idx]
            detail.append("Вот эта строка:")
            detail.append(f"    {bad}")
            if col_no and 0 < col_no <= len(bad) + 1:
                detail.append("    " + " " * (col_no - 1) + "^")
    else:
        detail.append(msg)

    detail.append("")
    detail.append(hint)

    return "\n".join(detail)


# ===========================================================================
# Markdown helpers
# ===========================================================================

def _to_str_list(value: Any) -> List[str]:
    """Coerce a YAML value to a list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,;]", value) if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]


def _extract_md_section(body: str, heading_pattern: str) -> str:
    """Return text between a heading matching pattern and the next heading."""
    pattern = rf"^#+\s*(?:{heading_pattern})\s*:?\s*$"
    match = re.search(pattern, body, re.MULTILINE | re.IGNORECASE)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^#+\s", body[start:], re.MULTILINE)
    if next_heading:
        return body[start : start + next_heading.start()].strip()
    return body[start:].strip()


def _extract_product_link(raw: Any) -> Optional[Dict[str, Any]]:
    """Извлекает блок product из сырого значения ингредиента.

    Ожидает либо dict {'uuid': ..., 'barcode': ...}, либо отдельные поля
    верхнего уровня 'product_id' / 'barcode'. Возвращает None, если ничего нет.

    Не делает lookup в store — только нормализует данные.
    """
    if not isinstance(raw, dict):
        return None

    result: Dict[str, Any] = {}

    # Явный вложенный блок product
    nested = raw.get("product")
    if isinstance(nested, dict):
        if nested.get("uuid"):
            result["uuid"] = str(nested["uuid"]).strip()
        if nested.get("barcode"):
            result["barcode"] = str(nested["barcode"]).strip()
        if nested.get("name"):
            result["name"] = str(nested["name"]).strip()

    # Верхнеуровневые поля (для краткости ручного набора)
    if not result.get("uuid") and raw.get("product_id"):
        result["uuid"] = str(raw["product_id"]).strip()
    if not result.get("barcode") and raw.get("barcode"):
        result["barcode"] = str(raw["barcode"]).strip()

    # Дополнительные поля — если присутствуют, они не обязательны,
    # но могут быть использованы linker'ом для более точной подстановки.
    for key in ("brand", "category", "image_url", "nutrition_per_100g", "serving_size_g"):
        if raw.get(key) is not None and key not in result:
            result[key] = raw[key]

    return result or None


def _parse_md_ingredients(
    metadata: Dict[str, Any], body: str
) -> List[Dict[str, Any]]:
    """Parse ingredients from front matter (preferred) or body section.

    Каждый ингредиент — dict с полями:
        name, amount, unit, notes, is_heading?, product?

    Блок `product` (если был в front matter) сохраняется как есть:
        {"uuid": "...", "barcode": "...", ...}

    Парсер НЕ пытается связать ингредиент с базой продуктов — это делает
    вызывающий код. Здесь только структура.
    """
    # Preferred: structured list in front matter
    raw = metadata.get("ingredients")
    if isinstance(raw, list):
        result: List[Dict[str, Any]] = []
        for item in raw:
            if isinstance(item, str):
                result.append(_parse_ingredient_line(item))
            elif isinstance(item, dict):
                # Определяем, является ли это подзаголовком
                is_heading = bool(item.get("is_heading")) or str(item.get("name", "")).startswith("#")

                parsed: Dict[str, Any] = {
                    "name": str(item.get("name", "")).strip(),
                }
                if is_heading:
                    parsed["is_heading"] = True
                else:
                    parsed["amount"] = item.get("amount")
                    parsed["unit"] = item.get("unit")
                    parsed["notes"] = item.get("notes")

                    # Блок product — если есть
                    product = _extract_product_link(item)
                    if product:
                        parsed["product"] = product

                result.append(parsed)
        return [r for r in result if r.get("name")]

    # Fallback: bullet list under "## Ингредиенты" / "## Ingredients"
    section = _extract_md_section(body, r"ингредиенты|ingredients")
    if not section:
        return []

    result = []
    for line in section.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^[-*+]\s+(.+)$", line)
        if not m:
            continue
        txt = m.group(1).strip()
        if _is_ingredient_heading(txt):
            result.append({
                "name": txt.rstrip(":"),
                "is_heading": True,
            })
        else:
            result.append(_parse_ingredient_line(txt))
    return result


def _parse_md_instructions(
    metadata: Dict[str, Any], body: str
) -> List[str]:
    """Parse instructions from front matter (preferred) or body section."""
    raw = metadata.get("instructions")
    if isinstance(raw, list):
        return [str(s).strip() for s in raw if str(s).strip()]
    if isinstance(raw, str) and raw.strip():
        return _split_instructions(raw)

    section = _extract_md_section(
        body,
        r"шаги|приготовление|инструкции|способ|"
        r"steps|directions|method|instructions",
    )
    if not section:
        return []

    instructions: List[str] = []
    for line in section.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\d+[.)]\s*(.+)$", line)
        if m:
            instructions.append(m.group(1).strip())
            continue
        m = re.match(r"^[-*+]\s+(.+)$", line)
        if m:
            instructions.append(m.group(1).strip())
            continue
        instructions.append(line)
    return [s for s in instructions if s]


# ===========================================================================
# Recipe Keeper per-recipe parsing
# ===========================================================================

def _text(container: Any, *class_names: str) -> Optional[str]:
    for cls in class_names:
        el = container.find(class_=re.compile(rf"\b{re.escape(cls)}\b", re.I))
        if el:
            t = el.get_text(" ", strip=True)
            if t:
                return t
    return None


def _itemprop(container: Any, prop: str) -> Optional[str]:
    el = container.find(attrs={"itemprop": prop})
    if not el:
        return None
    if el.name == "meta":
        return el.get("content", "").strip() or None
    return el.get_text(" ", strip=True) or None


def _itemprop_all(container: Any, prop: str) -> List[str]:
    values = []
    for el in container.find_all(attrs={"itemprop": prop}):
        if el.name == "meta":
            v = el.get("content", "").strip()
        else:
            v = el.get_text(" ", strip=True)
        if v:
            values.append(v)
    return values


def _parse_iso_duration(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    iso = iso.strip()
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", iso, re.I)
    if not m:
        return None
    hours = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    return hours * 60 + mins or None


def _parse_recipe_container(
    container: Any, images: Dict[str, bytes]
) -> Dict[str, Any]:
    """Parse one recipe <div class="recipe-details"> block."""

    name = (_itemprop(container, "name")
            or _text(container, "recipe-name"))
    if not name:
        for tag in ("h2", "h3", "h1"):
            el = container.find(tag)
            if el:
                name = el.get_text(strip=True)
                break
    if not name:
        return {}

    description = (_itemprop(container, "description")
                   or _text(container, "recipe-description"))

    servings_text = (_itemprop(container, "recipeYield")
                     or _text(container, "recipe-serving-size", "recipe-yield", "recipe-servings"))
    servings: Optional[int] = None
    if servings_text:
        m = re.search(r"\d+", servings_text)
        servings = int(m.group()) if m else None

    prep_meta  = _itemprop(container, "prepTime")
    cook_meta  = _itemprop(container, "cookTime")
    total_meta = _itemprop(container, "totalTime")

    prep_time  = _parse_iso_duration(prep_meta)  or _parse_time(_text(container, "recipe-prep-time",  "recipe-preptime"))
    cook_time  = _parse_iso_duration(cook_meta)  or _parse_time(_text(container, "recipe-cook-time",  "recipe-cooktime"))
    total_time = _parse_iso_duration(total_meta) or _parse_time(_text(container, "recipe-total-time", "recipe-totaltime"))

    courses: List[str] = _itemprop_all(container, "recipeCourse")
    if not courses:
        course_text = _text(container, "recipe-course", "recipe-courses")
        if course_text:
            courses = [c.strip() for c in re.split(r"[,;/]", course_text) if c.strip()]

    categories: List[str] = _itemprop_all(container, "recipeCategory")
    if not categories:
        cat_text = _text(container, "recipe-categories", "recipe-category")
        if cat_text:
            categories = [c.strip() for c in re.split(r"[,;/]", cat_text) if c.strip()]

    collections: List[str] = _itemprop_all(container, "recipeCollection")
    if not collections:
        coll_text = _text(container, "recipe-collections", "recipe-collection")
        if coll_text:
            collections = [c.strip() for c in re.split(r"[,;/]", coll_text) if c.strip()]

    tags: List[str] = [c.lower() for c in categories]

    cuisine = _text(container, "recipe-cuisine")

    source_url = (_itemprop(container, "recipeSource")
                  or _text(container, "recipe-source", "recipe-url", "recipe-source-url"))
    if not source_url:
        src_el = container.find(class_=re.compile(r"recipe-source", re.I))
        if src_el:
            a = src_el.find("a")
            if a:
                source_url = a.get("href", "").strip() or None
    if source_url and not source_url.startswith("http"):
        source_url = None

    notes = _text(container, "recipe-notes", "recipe-note")

    image_bytes: Optional[bytes] = None
    image_src: Optional[str] = None
    photo_el = container.find(class_=re.compile(r"recipe-photo", re.I))
    if photo_el:
        img = photo_el if photo_el.name == "img" else photo_el.find("img")
        if img:
            image_src = img.get("src") or img.get("data-src")
    if not image_src:
        img = container.find("img")
        if img:
            src = img.get("src", "")
            if not any(skip in src.lower() for skip in ("logo", "icon", "banner")):
                image_src = src
    if image_src:
        image_bytes = images.get(image_src)
        if not image_bytes:
            basename = image_src.split("/")[-1]
            for k, v in images.items():
                if k.split("/")[-1] == basename:
                    image_bytes = v
                    break

    ingredients: List[Dict[str, Any]] = []
    ing_el = (
        container.find(attrs={"itemprop": "recipeIngredients"})
        or container.find(class_=re.compile(
            r"recipe-ingredients?|p-ingredients?|ingredient-list|ingredients-list", re.I
        ))
    )
    if ing_el:
        raw_items = ing_el.find_all("li") or ing_el.find_all("p") or ing_el.find_all("span")
        if raw_items:
            for item in raw_items:
                is_bold = bool(item.find(["b", "strong"]))
                txt = item.get_text(" ", strip=True)
                if not txt:
                    continue
                if is_bold and _is_ingredient_heading(txt):
                    ingredients.append({"name": txt.rstrip(":"), "is_heading": True})
                elif _is_ingredient_heading(txt) and not re.search(r"\d", txt):
                    ingredients.append({"name": txt.rstrip(":"), "is_heading": True})
                else:
                    ingredients.append(_parse_ingredient_line(txt))
        else:
            for line in ing_el.get_text("\n", strip=True).split("\n"):
                line = line.strip()
                if line:
                    ingredients.append(_parse_ingredient_line(line))

    instructions: List[str] = []
    method_el = (
        container.find(attrs={"itemprop": "recipeDirections"})
        or container.find(attrs={"itemprop": "recipeInstructions"})
        or container.find(class_=re.compile(
            r"recipe-method-directions|recipe-method|recipe-directions?"
            r"|recipe-instructions?|recipe-steps?"
            r"|e-instructions?|directions?-list|steps?-list"
            r"|method|directions?",
            re.I,
        ))
    )

    if not method_el:
        for el in container.find_all(["ol", "ul"]):
            if el.find("li"):
                first_li = el.find("li")
                first_text = first_li.get_text(strip=True) if first_li else ""
                if len(first_text) > 10:
                    if el is not ing_el:
                        method_el = el
                        _LOGGER.debug("Recipe Keeper import: using fallback <ol/ul> for directions")
                        break

    if method_el:
        items = method_el.find_all("li") or method_el.find_all("p")
        if items:
            for item in items:
                txt = item.get_text(" ", strip=True)
                txt = re.sub(r"^(?:Step\s*)?\d+[.):\s]+", "", txt, flags=re.I).strip()
                if txt:
                    instructions.append(txt)
        else:
            raw_text = method_el.get_text("\n", strip=True)
            for line in raw_text.split("\n"):
                line = re.sub(r"^(?:Step\s*)?\d+[.):\s]+", "", line.strip(), flags=re.I).strip()
                if line:
                    instructions.append(line)
    else:
        _LOGGER.warning(
            "Recipe Keeper import: no directions element found for recipe '%s'", name
        )

    nutrition: Optional[Dict[str, str]] = None

    _NUTR_ITEMPROP_MAP = {
        "calories":              "calories",
        "fatContent":            "fat",
        "saturatedFatContent":   "saturated_fat",
        "transFatContent":       "trans_fat",
        "cholesterolContent":    "cholesterol",
        "sodiumContent":         "sodium",
        "carbohydrateContent":   "carbohydrates",
        "fiberContent":          "fiber",
        "sugarContent":          "sugar",
        "proteinContent":        "protein",
    }

    nutr_el = (
        container.find(attrs={"itemprop": "nutrition"})
        or container.find(class_=re.compile(r"recipe-nutrition", re.I))
    )

    direct_nutr: Dict[str, str] = {}
    for ip, key in _NUTR_ITEMPROP_MAP.items():
        val = _itemprop(container, ip)
        if val:
            num_m = re.search(r"[\d.]+", val)
            if num_m:
                direct_nutr[key] = num_m.group()

    if nutr_el:
        nutrition = {}
        for ip, key in _NUTR_ITEMPROP_MAP.items():
            val = _itemprop(nutr_el, ip)
            if val:
                num_m = re.search(r"[\d.]+", val)
                if num_m:
                    nutrition[key] = num_m.group()
        if not nutrition:
            for item in nutr_el.find_all(["li", "span", "div", "td", "p"]):
                txt = item.get_text(" ", strip=True)
                m = re.match(r"(.+?):\s*(.+)", txt)
                if m:
                    key = m.group(1).strip().lower().replace(" ", "_")
                    nutrition[key] = m.group(2).strip()
        if not nutrition:
            nutrition = None

    if direct_nutr:
        nutrition = {**(nutrition or {}), **direct_nutr} or None

    if not nutrition and notes:
        parsed_nutrition, cleaned_notes = _extract_nutrition_from_notes(notes)
        if parsed_nutrition:
            nutrition = parsed_nutrition
            notes = cleaned_notes

    return {
        "name": name.strip(),
        "description": description,
        "servings": servings,
        "servings_text": servings_text,
        "prep_time": prep_time,
        "cook_time": cook_time,
        "total_time": total_time,
        "cuisine": cuisine,
        "courses": courses,
        "categories": categories,
        "collections": collections,
        "tags": tags,
        "source_url": source_url,
        "notes": notes,
        "ingredients": ingredients,
        "instructions": instructions,
        "nutrition": nutrition,
        "_image_bytes": image_bytes,
        "_image_filename": image_src,
    }


# ===========================================================================
# Ingredient / time helpers
# ===========================================================================

def _is_ingredient_heading(text: str) -> bool:
    stripped = text.rstrip(":").strip()
    if not stripped:
        return False
    if stripped == stripped.upper() and re.search(r"[A-Z]", stripped):
        return True
    if re.match(r"^For\s+", stripped, re.I) and not re.search(r"\d", stripped):
        return True
    return False


def _parse_time(text: Optional[str]) -> Optional[int]:
    """Parse human time strings to minutes."""
    if not text:
        return None
    t = text.strip().lower()
    m = re.match(r"(\d+)\s*h(?:ours?)?\s*(?:and\s*)?(\d+)\s*m(?:in(?:utes?)?)?", t)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.match(r"(\d+)\s*m(?:in(?:utes?)?)?$", t)
    if m:
        return int(m.group(1))
    m = re.match(r"(\d+)\s*h(?:ours?)?$", t)
    if m:
        return int(m.group(1)) * 60
    m = re.match(r"^(\d+)$", t)
    if m:
        return int(m.group(1))
    return None


_UNIT_NORMALIZE: Dict[str, str] = {
    "teaspoon":           "tsp",
    "teaspoons":          "tsp",
    "tablespoon":         "Tbsp",
    "tablespoons":        "Tbsp",
    "ounce":              "oz",
    "ounces":             "oz",
    "fluid ounce":        "fl oz",
    "fluid ounces":       "fl oz",
    "pound":              "lb",
    "pounds":             "lb",
    "lbs":                "lb",
    "gram":               "g",
    "grams":              "g",
    "gramme":             "g",
    "grammes":            "g",
    "kilogram":           "kg",
    "kilograms":          "kg",
    "kilogramme":         "kg",
    "kilogrammes":        "kg",
    "millilitre":         "ml",
    "millilitres":        "ml",
    "milliliter":         "ml",
    "milliliters":        "ml",
    "centilitre":         "cl",
    "centilitres":        "cl",
    "centiliter":         "cl",
    "centiliters":        "cl",
    "decilitre":          "dl",
    "decilitres":         "dl",
    "deciliter":          "dl",
    "deciliters":         "dl",
    "litre":              "L",
    "litres":             "L",
    "liter":              "L",
    "liters":             "L",
    "pint":               "pt",
    "pints":              "pt",
    "quart":              "qt",
    "quarts":             "qt",
    "gallon":             "gal",
    "gallons":            "gal",
}


def _normalize_unit(unit: Optional[str]) -> Optional[str]:
    if not unit:
        return unit
    return _UNIT_NORMALIZE.get(unit.lower(), unit)


_INGREDIENT_RE = re.compile(
    r"^"
    r"(?P<amount>\d+(?:[.,/]\d+)?(?:\s*[-–]\s*\d+(?:[.,/]\d+)?)?"
    r"(?:\s+\d+/\d+)?)?"
    r"\s*"
    r"(?P<unit>"
    r"tsp|tbsp|fl\.?\s*oz"
    r"|tablespoons?|teaspoons?"
    r"|(?:milli|centi|deci)?lit(?:re|er)s?"
    r"|ml|cl|dl|L"
    r"|kilo(?:gramme|gram)s?|(?:gramme|gram)s?"
    r"|kg|g"
    r"|cups?|oz|lbs?|pints?|quarts?|gallons?"
    r"|cans?|bunches?|heads?|cloves?|slices?|pieces?|sheets?"
    r"|pinch(?:es)?|dash(?:es)?|handfuls?|sprigs?|stalks?"
    r")?\.?"
    r"\s*"
    r"(?P<name>.+?)$",
    re.IGNORECASE,
)


_UNICODE_FRACTIONS: Dict[str, str] = {
    "\u00bd": "1/2",
    "\u00bc": "1/4",
    "\u00be": "3/4",
    "\u2153": "1/3",
    "\u2154": "2/3",
    "\u215b": "1/8",
    "\u215c": "3/8",
    "\u215d": "5/8",
    "\u215e": "7/8",
}


def _normalize_fractions(text: str) -> str:
    for char, replacement in _UNICODE_FRACTIONS.items():
        text = re.sub(rf"(\d){re.escape(char)}", rf"\1 {replacement}", text)
        text = text.replace(char, replacement)
    return text


def _parse_ingredient_line(raw: str) -> Dict[str, Any]:
    """Split an ingredient string into {amount, unit, name, notes}."""
    raw = _normalize_fractions(raw.strip())
    m = _INGREDIENT_RE.match(raw)
    if not m:
        return {"name": raw, "amount": None, "unit": None, "notes": None}

    amount = (m.group("amount") or "").strip() or None
    unit = _normalize_unit((m.group("unit") or "").strip() or None)
    rest = (m.group("name") or "").strip()

    rest = re.sub(r"^of\s+(?:the\s+)?", "", rest, flags=re.I).strip()

    name, notes = rest, None
    if "," in rest:
        parts = rest.split(",", 1)
        name = parts[0].strip()
        notes = parts[1].strip()
    return {"name": name, "amount": amount, "unit": unit, "notes": notes}


_NUTRITION_PATTERNS: List[Tuple[str, str]] = [
    (r"calories?\s*[:\-]\s*(\d+(?:\.\d+)?)\s*(?:kcal)?",                  "calories"),
    (r"total\s+fat\s*[:\-]\s*(\d+(?:\.\d+)?)\s*g?",                       "fat"),
    (r"saturated\s+fat\s*[:\-]\s*(\d+(?:\.\d+)?)\s*g?",                   "saturated_fat"),
    (r"trans\s+fat\s*[:\-]\s*(\d+(?:\.\d+)?)\s*g?",                       "trans_fat"),
    (r"cholesterol\s*[:\-]\s*(\d+(?:\.\d+)?)\s*mg?",                      "cholesterol"),
    (r"sodium\s*[:\-]\s*(\d+(?:\.\d+)?)\s*mg?",                           "sodium"),
    (r"(?:total\s+)?carb(?:ohydrate)?s?\s*[:\-]\s*(\d+(?:\.\d+)?)\s*g?",  "carbohydrates"),
    (r"(?:dietary\s+)?fiber\s*[:\-]\s*(\d+(?:\.\d+)?)\s*g?",              "fiber"),
    (r"(?:total\s+)?sugars?\s*[:\-]\s*(\d+(?:\.\d+)?)\s*g?",              "sugar"),
    (r"protein\s*[:\-]\s*(\d+(?:\.\d+)?)\s*g?",                           "protein"),
]


def _extract_nutrition_from_notes(
    notes_text: str,
) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    if not notes_text:
        return None, notes_text

    nutrition: Dict[str, str] = {}
    remaining_lines: List[str] = []

    for line in notes_text.splitlines():
        matched = False
        for pattern, key in _NUTRITION_PATTERNS:
            m = re.search(pattern, line, re.I)
            if m:
                nutrition[key] = m.group(1)
                matched = True
                break
        if not matched:
            remaining_lines.append(line)

    if not nutrition:
        return None, notes_text

    cleaned = "\n".join(remaining_lines).strip() or None
    return nutrition, cleaned