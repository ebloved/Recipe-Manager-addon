"""Публичная страница рецепта (/share/<token>).

Рендерится на сервере, без SPA и без доступа к внутренним полям рецепта.
Всё пользовательское содержимое экранируется; markdown — только безопасный
мини-набор (**жирный**, *курсив*, простые списки).
"""
from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse

# Поля, которые можно показывать публично.
_PUBLIC_FIELDS = (
    "name",
    "description",
    "image_url",
    "tags",
    "courses",
    "categories",
    "collections",
    "cuisine",
    "category",
    "servings",
    "servings_text",
    "prep_time",
    "cook_time",
    "time",
    "total_time",
    "ingredients",
    "instructions",
    "notes",
    "nutrition",
    "source_url",
)


def public_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    """Whitelist полей: без owner_id, share_token, normalization_* и т.п."""
    out: dict[str, Any] = {}
    for key in _PUBLIC_FIELDS:
        if key in recipe:
            out[key] = recipe[key]

    out["ingredients"] = [
        {
            "name": ing.get("name"),
            "amount": ing.get("amount"),
            "unit": ing.get("unit"),
            "notes": ing.get("notes"),
        }
        for ing in (recipe.get("ingredients") or [])
        if isinstance(ing, dict)
    ]
    out["instructions"] = [
        str(s) for s in (recipe.get("instructions") or []) if str(s).strip()
    ]
    for key in ("image_url", "source_url"):
        if key in out:
            out[key] = _safe_url(out.get(key))
    return out


def _safe_url(url: Any) -> str | None:
    """Только http(s) или относительный /media/..., без javascript:/data:."""
    if not isinstance(url, str) or not url.strip():
        return None
    raw = url.strip()
    if raw.startswith("/") and not raw.startswith("//"):
        return raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return None
    return url.strip()


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _inline_md(text: str) -> str:
    """Экранирует текст и применяет только **bold** / *italic*."""
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", escaped)
    return escaped


def render_md_block(text: Any) -> str:
    """Безопасный мини-markdown для шага/заметки."""
    raw = "" if text is None else str(text)
    lines = raw.splitlines() or [raw]
    html_parts: list[str] = []
    list_type: str | None = None
    for line in lines:
        stripped = line.strip()
        m_ul = re.match(r"^[-*]\s+(.*)$", stripped)
        m_ol = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if m_ul or m_ol:
            wanted = "ul" if m_ul else "ol"
            if list_type != wanted:
                if list_type:
                    html_parts.append(f"</{list_type}>")
                html_parts.append(f"<{wanted}>")
                list_type = wanted
            html_parts.append(f"<li>{_inline_md((m_ul or m_ol).group(1))}</li>")
        else:
            if list_type:
                html_parts.append(f"</{list_type}>")
                list_type = None
            if stripped:
                html_parts.append(f"<p>{_inline_md(stripped)}</p>")
    if list_type:
        html_parts.append(f"</{list_type}>")
    return "".join(html_parts)


def _fmt_minutes(value: Any) -> str | None:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    if minutes <= 0:
        return None
    if minutes < 60:
        return f"{minutes} мин"
    hours, rest = divmod(minutes, 60)
    return f"{hours} ч" + (f" {rest} мин" if rest else "")


_CSS = """
:root{--bg:#faf9f7;--surface:#fff;--text:#1f1c19;--muted:#6b6560;--border:#e7e1da;--accent:#b45309}
@media(prefers-color-scheme:dark){:root{--bg:#141210;--surface:#1d1a17;--text:#f2ece5;--muted:#a69d93;--border:#2e2924;--accent:#f59e0b}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:24px 18px 48px}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}
.brand{font-weight:700;letter-spacing:.2px;color:var(--muted);font-size:14px;text-decoration:none}
.card{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:20px}
h1{font-size:26px;line-height:1.25;margin:0 0 8px}
.desc{color:var(--muted);margin:0 0 12px;white-space:pre-line}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px}
.chip{background:var(--bg);border:1px solid var(--border);border-radius:999px;padding:3px 10px;font-size:13px;color:var(--muted)}
.hero{width:100%;max-height:340px;object-fit:cover;border-radius:12px;margin:4px 0 14px}
h2{font-size:18px;margin:22px 0 8px}
ul.ing{list-style:none;padding:0;margin:0}
ul.ing li{padding:8px 0;border-bottom:1px solid var(--border);display:flex;gap:8px;justify-content:space-between}
ul.ing li:last-child{border-bottom:0}
.amount{color:var(--muted);white-space:nowrap}
.note{color:var(--muted);font-size:13px}
.steps{padding-left:0;list-style:none;margin:0;counter-reset:s}
.steps li{position:relative;padding:10px 0 10px 40px;border-bottom:1px solid var(--border)}
.steps li:last-child{border-bottom:0}
.steps li:before{counter-increment:s;content:counter(s);position:absolute;left:0;top:10px;width:28px;height:28px;border-radius:50%;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700}
.steps p{margin:0}
.sharebox{margin-top:22px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.sharebox input{flex:1;min-width:220px;padding:10px 12px;border-radius:10px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:14px}
button{padding:10px 16px;border-radius:10px;border:0;background:var(--accent);color:#fff;font-size:14px;font-weight:600;cursor:pointer}
button.secondary{background:transparent;color:var(--text);border:1px solid var(--border)}
a{color:var(--accent)}
.foot{margin-top:18px;font-size:12px;color:var(--muted);text-align:center}
"""


def _page_shell(title: str, body: str, *, extra_head: str = "") -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta name="referrer" content="no-referrer">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
{extra_head}
</head>
<body>
<div class="wrap">
<div class="top"><span class="brand">Recipe Manager</span></div>
{body}
<div class="foot">Публичная ссылка. Страница доступна только по этой ссылке.</div>
</div>
</body>
</html>"""


def render_share_page(recipe: dict[str, Any], share_url: str = "") -> str:
    r = public_recipe(recipe)
    title = r.get("name") or "Рецепт"

    meta: list[str] = []
    total = _fmt_minutes(r.get("total_time") or r.get("time"))
    if total:
        meta.append(f"⏱ {total}")
    if r.get("servings"):
        meta.append(f"👥 {_esc(r['servings'])}")
    if r.get("cuisine"):
        meta.append(f"🍽 {_esc(r['cuisine'])}")
    for tag in (r.get("tags") or [])[:4]:
        meta.append(f"#{_esc(tag)}")

    image = _safe_url(r.get("image_url"))
    image_html = (
        f'<img class="hero" src="{_esc(image)}" alt="{_esc(title)}" loading="lazy">'
        if image else ""
    )

    ings = r.get("ingredients") or []
    ing_html = "".join(
        f"<li><span>{_esc(ing.get('name'))}"
        + (f' <span class="note">— {_esc(ing.get("notes"))}</span>' if ing.get("notes") else "")
        + "</span>"
        + (
            f'<span class="amount">{_esc(ing.get("amount"))} {_esc(ing.get("unit") or "")}</span>'
            if ing.get("amount") is not None or ing.get("unit") else ""
        )
        + "</li>"
        for ing in ings
    )
    ing_section = (
        f"<h2>Ингредиенты</h2><ul class='ing'>{ing_html}</ul>" if ing_html else ""
    )

    steps = r.get("instructions") or []
    steps_html = "".join(f"<li>{render_md_block(s)}</li>" for s in steps)
    steps_section = (
        f"<h2>Шаги</h2><ol class='steps'>{steps_html}</ol>" if steps_html else ""
    )

    notes_section = (
        f"<h2>Заметки</h2><div class='note'>{render_md_block(r.get('notes'))}</div>"
        if (r.get("notes") or "").strip() else ""
    )

    source = _safe_url(r.get("source_url"))
    source_html = (
        f"<p style='margin-top:18px'>Источник: "
        f"<a href='{_esc(source)}' rel='noopener noreferrer nofollow'>открыть</a></p>"
        if source else ""
    )

    body = f"""
<div class="card">
  <h1>{_esc(title)}</h1>
  {f'<p class="desc">{_esc(r.get("description"))}</p>' if r.get("description") else ""}
  {'<div class="meta">' + ''.join(f'<span class="chip">{m}</span>' for m in meta) + '</div>' if meta else ""}
  {image_html}
  {ing_section}
  {steps_section}
  {notes_section}
  {source_html}
  <div class="sharebox">
    <input id="share-url" value="{_esc(share_url)}" readonly aria-label="Ссылка на рецепт">
    <button id="copy-link">Скопировать</button>
  </div>
</div>
<script src="../static/js/share.js?v=88" defer></script>
"""
    return _page_shell(title, body)


def render_share_not_found() -> str:
    body = """
<div class="card">
  <h1>Рецепт не найден</h1>
  <p class="desc">Ссылка недействительна или была отозвана автором.</p>
</div>
"""
    return _page_shell("Рецепт не найден", body)


def share_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, max-age=0",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": (
            "default-src 'none'; img-src https: data:; style-src 'unsafe-inline'; "
            "script-src 'self'; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'"
        ),
    }
